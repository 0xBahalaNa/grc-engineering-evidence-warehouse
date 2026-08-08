"""Thin EL loader: land producer JSON into DuckDB raw.* with run metadata.

Extract-and-load only — no rename/status/'N/A' normalization. Staging (#4)
owns transform, including ISO-8601 → timestamptz casts. Finding columns land
as VARCHAR (D11): validate parses JSON once, then CREATE TABLE + INSERT from
that in-memory list — no second disk read after DROP SCHEMA (AU-12(3)/AU-9).
Honors EVIDENCE_DB_PATH with the same semantics as profiles.yml (D8).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

# File stem -> raw.<stem>; must be a bare DuckDB identifier (unquoted in SQL).
_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Keys spliced into CREATE TABLE column lists — allowlist only (B1).
# Permits hyphen / dot / colon / reserved-word keys from prior B4/B5 cases;
# rejects quote, brace, comma, whitespace, and control characters.
_SAFE_JSON_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
# Loader-owned stamps — must not appear in landing JSON (_core.md), any case (B2).
_RESERVED_STAMP_KEYS = frozenset({"run_id", "loaded_at"})
_RESERVED_STAMP_FOLDS = frozenset(k.casefold() for k in _RESERVED_STAMP_KEYS)
# Loader-owned raw table — a landing file with this stem would collide (D2 / #14).
# Compare with casefold — DuckDB unquoted identifiers are case-insensitive (B1).
_RESERVED_TABLE_NAME = "load_manifest"
_RESERVED_TABLE_FOLD = _RESERVED_TABLE_NAME.casefold()


class DuplicateKeyError(ValueError):
    """Raised by object_pairs_hook when a JSON object repeats a key."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """object_pairs_hook: reject duplicate keys before dict collapse (F1)."""
    seen: set[str] = set()
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise DuplicateKeyError(key)
        seen.add(key)
        out[key] = value
    return out


def _load_json(path: Path) -> Any:
    """UTF-8 JSON load at least as strict as DuckDB read_json (gate parity)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f, object_pairs_hook=_reject_duplicate_keys)
    except UnicodeDecodeError as e:
        sys.exit(f"{path}: not valid UTF-8: {e}")
    except DuplicateKeyError as e:
        sys.exit(f"{path}: duplicate JSON key: {e.key!r}")
    except json.JSONDecodeError as e:
        sys.exit(f"{path}: invalid JSON: {e}")


def resolve_db_path() -> str:
    """Match profiles.yml: absent -> default; set-but-empty -> abort loudly."""
    if "EVIDENCE_DB_PATH" in os.environ:
        db_path = os.environ["EVIDENCE_DB_PATH"]
        if db_path == "":
            sys.exit(
                "EVIDENCE_DB_PATH is set but empty; unset it to use the default "
                "or provide a non-empty path (same semantics as profiles.yml)."
            )
        return db_path
    return "evidence_warehouse.duckdb"


def _finding_keys(path: Path, data: list[Any]) -> list[str]:
    """Validate finding rows/keys (B1/B2/B4/B5); return sorted unique keys."""
    keys: set[str] = set()
    folded: dict[str, str] = {}
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            sys.exit(
                f"{path}: expected finding objects (JSON objects), "
                f"got {type(row).__name__} at index {i}"
            )
        for key in row:
            if not _SAFE_JSON_KEY_RE.fullmatch(key):
                sys.exit(
                    f"{path}: refusing JSON key outside safe-identifier "
                    f"allowlist: {key!r}"
                )
            if key.casefold() in _RESERVED_STAMP_FOLDS:
                sys.exit(
                    f"{path}: reserved stamp key {key!r} must not appear in "
                    "landing data (loader stamps run_id / loaded_at)"
                )
            fold = key.casefold()
            prior = folded.get(fold)
            if prior is not None and prior != key:
                sys.exit(
                    f"{path}: case-colliding JSON keys {prior!r} and {key!r}"
                )
            folded[fold] = key
            keys.add(key)
    if not keys:
        sys.exit(f"{path}: finding objects have no keys")
    return sorted(keys)


def _varchar_column_defs(keys: list[str]) -> str:
    """Build CREATE TABLE column defs with double-quoted keys (D11 / B4 / B5)."""
    return ", ".join(f'"{key}" VARCHAR' for key in keys)


def _row_values(row: dict[str, Any], keys: list[str]) -> list[Any]:
    """Coerce one finding to VARCHAR-pinned param values (D11); None stays NULL."""
    vals: list[Any] = []
    for key in keys:
        value = row.get(key)
        if value is None:
            vals.append(None)
        elif isinstance(value, str):
            vals.append(value)
        else:
            vals.append(str(value))
    return vals


def load_source(
    conn: duckdb.DuckDBPyConnection,
    path: Path,
    run_id: str,
    loaded_at: datetime,
    data: list[Any],
) -> int:
    """
    Load validated findings into raw.<stem> from the in-memory list.

    Returns number of rows loaded. Caller must pass the list returned by
    _validate_landing_file — this path never re-reads disk after DROP (S1/B1).
    """
    if not isinstance(data, list):
        raise TypeError(
            f"load_source requires data=list of findings, got {type(data).__name__}"
        )

    table = path.stem
    if not _TABLE_NAME_RE.fullmatch(table):
        sys.exit(f"Refusing unsafe table name from file stem: {table!r}")

    # Source-agnostic land: pin every finding key to VARCHAR (D11) and INSERT
    # from the validated in-memory list — not a second read_json of path.
    # Keys are double-quoted so reserved words / hyphen / dot / colon keys land;
    # validation already enforced the allowlist, reserved stamps
    # (case-insensitive), and case collisions. Stamp run_id + loaded_at only —
    # no transform.
    keys = _finding_keys(path, data)
    col_defs = _varchar_column_defs(keys)
    conn.execute(
        f"""
        CREATE OR REPLACE TABLE raw.{table} (
            {col_defs},
            run_id VARCHAR,
            loaded_at TIMESTAMPTZ
        )
        """
    )
    col_list = ", ".join(f'"{key}"' for key in keys) + ", run_id, loaded_at"
    placeholders = ", ".join(["?"] * (len(keys) + 2))
    insert_sql = f"INSERT INTO raw.{table} ({col_list}) VALUES ({placeholders})"
    params = [
        _row_values(row, keys) + [run_id, loaded_at]
        for row in data
    ]
    conn.executemany(insert_sql, params)
    return len(data)


def write_manifest(
    conn: duckdb.DuckDBPyConnection,
    run_id: str,
    loaded_at: datetime,
    counts: dict[str, int],
) -> None:
    """
    Write raw.load_manifest — one row per landing file processed.

    counts maps source stem -> findings landed (0 is valid). Same run_id /
    loaded_at as the finding rows from this invocation.
    """
    conn.execute("""
        CREATE TABLE raw.load_manifest (
            run_id VARCHAR,
            source VARCHAR,
            row_count BIGINT,
            loaded_at TIMESTAMPTZ
        )
    """)

    for source, row_count in counts.items():
        conn.execute(
            """
            INSERT INTO raw.load_manifest (run_id, source, row_count, loaded_at)
            VALUES (?, ?, ?, ?)
            """,
            [run_id, source, row_count, loaded_at],
        )


def _validate_landing_file(path: Path) -> list[Any] | None:
    """
    Full landing gate — MUST run before DROP SCHEMA so a bad file cannot wipe raw.*.

    Returns the parsed findings list for load_source to reuse (S1), or None when
    the file is an empty array (caller records row_count=0 in the manifest; no
    key checks — an empty array carries no keys).
    """
    table = path.stem
    if not _TABLE_NAME_RE.fullmatch(table):
        sys.exit(f"Refusing unsafe table name from file stem: {table!r}")
    if table.casefold() == _RESERVED_TABLE_FOLD:
        sys.exit(
            f"{path}: reserved table name {_RESERVED_TABLE_NAME!r} "
            "(loader-owned manifest; refuse landing file that would collide)"
        )
    data = _load_json(path)
    if not isinstance(data, list):
        sys.exit(f"{path}: expected a JSON array of findings, got {type(data).__name__}")
    # Empty array = reported-with-zero-findings; no key checks (no keys to check).
    if len(data) == 0:
        return None
    _finding_keys(path, data)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Land raw finding JSON into DuckDB raw.* (EL only)."
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        required=True,
        help="Directory of *.json landing files (one table per file stem)",
    )
    args = parser.parse_args(argv)

    raw_dir: Path = args.raw_dir
    if not raw_dir.is_dir():
        sys.exit(f"--raw-dir is not a directory: {raw_dir}")

    db_path = resolve_db_path()
    loaded_at = datetime.now(timezone.utc)
    run_id = loaded_at.strftime("%Y%m%dT%H%M%SZ")

    landing_files = sorted(raw_dir.glob("*.json"))

    # Pre-DROP stem gate (R-2): reserved name + case-insensitive stem collisions.
    seen_stems: dict[str, Path] = {}
    for path in landing_files:
        folded = path.stem.casefold()

        # B1 — reserved loader table name, any casing
        if folded == _RESERVED_TABLE_FOLD:
            sys.exit(
                f"{path}: reserved table name {_RESERVED_TABLE_NAME!r} "
                "(loader-owned manifest; refuse landing file that would collide)"
            )

        # B2 — two files that DuckDB would collapse into one table
        prior = seen_stems.get(folded)
        if prior is not None:
            sys.exit(
                f"case-colliding landing file stems {prior.name!r} and {path.name!r} "
                "(DuckDB table names are case-insensitive; refuse before DROP)"
            )
        seen_stems[folded] = path

    # Pre-validate before DROP so a bad file cannot wipe prior raw.* (S4 / F1).
    # Keep parsed payloads so load_source does not re-read after DROP (S1).
    # None value = empty array → manifest row_count=0, no raw.<source> table.
    validated: dict[Path, list[Any] | None] = {}
    for path in landing_files:
        if path.exists() and path.stat().st_size > 0:
            validated[path] = _validate_landing_file(path)

    conn = duckdb.connect(db_path)
    try:
        # Idempotent rebuild (S2): clear prior raw.* so absent sources leave no table.
        conn.execute("DROP SCHEMA IF EXISTS raw CASCADE")
        conn.execute("CREATE SCHEMA raw")

        total = 0
        # source stem -> rows landed; 0 is a real signal (clean account), not a skip.
        counts: dict[str, int] = {}
        for path in landing_files:
            if path not in validated:
                # Zero-byte / unreadable-by-size gate — not a JSON empty array.
                print(f"{path.name}: skipped (absent/empty)")
                continue
            data = validated[path]
            if data is None:
                counts[path.stem] = 0
                print(f"{path.name}: 0 rows -> manifest only")
                continue
            n = load_source(conn, path, run_id, loaded_at, data=data)
            counts[path.stem] = n
            total += n
            print(f"{path.name}: {n} rows -> raw.{path.stem}")

        write_manifest(conn, run_id, loaded_at, counts)
        print(f"run_id={run_id} loaded_at={loaded_at.isoformat()} rows={total} db={db_path}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
