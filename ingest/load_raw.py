"""Thin EL loader: land producer JSON into DuckDB raw.* with run metadata.

Extract-and-load only — no rename/status/'N/A' normalization. Staging (#4)
owns transform, including ISO-8601 → timestamptz casts. Timestamps land as
verbatim VARCHAR (see read_json timestampformat pin below) so raw never
materializes a naive TIMESTAMP. Honors EVIDENCE_DB_PATH with the same
semantics as profiles.yml (D8).
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

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def load_source(conn: duckdb.DuckDBPyConnection, path: Path, run_id: str, loaded_at: datetime) -> int:
    """
    Load one JSON file into raw.<stem>, or skip if absent/empty.

    Returns number of rows loaded (0 if skipped).
    """
    # If path does not exist, return 0.
    if not path.exists():
        return 0

    # If file size is 0, return 0.
    if path.stat().st_size == 0:
        return 0

    # Empty array => absent source (interim #14 representation — keep skip).
    # Non-list => hard error (contract violation, not "absent").
    data = _load_json(path)

    if not isinstance(data, list):
        sys.exit(f"{path}: expected a JSON array of findings, got {type(data).__name__}")
    if len(data) == 0:
        return 0

    table = path.stem
    if not _TABLE_NAME_RE.fullmatch(table):
        sys.exit(f"Refusing unsafe table name from file stem: {table!r}")

    # Source-agnostic land: DuckDB infers columns from JSON keys; we stamp
    # run_id + loaded_at only. timestampformat is a deliberate never-match pin
    # so ISO-8601 strings (collected_at / event_time) land as VARCHAR verbatim
    # instead of naive TIMESTAMP — staging owns the timestamptz cast (B1 / D9).
    # sample_size=-1: type from the full file, not the 20_480-row sample window (F2).
    conn.execute(
        f"""
        CREATE OR REPLACE TABLE raw.{table} AS
        SELECT *, ? AS run_id, ?::TIMESTAMPTZ AS loaded_at
        FROM read_json(
            ?,
            format='array',
            timestampformat='%m/%d/%Y %H:%M:%S',
            sample_size=-1
        )
        """,
        [run_id, loaded_at, str(path)],
    )
    return len(data)


def _validate_landing_file(path: Path) -> None:
    """Parse + stem-check one landing file; abort before any schema mutation."""
    table = path.stem
    if not _TABLE_NAME_RE.fullmatch(table):
        sys.exit(f"Refusing unsafe table name from file stem: {table!r}")
    data = _load_json(path)
    if not isinstance(data, list):
        sys.exit(f"{path}: expected a JSON array of findings, got {type(data).__name__}")


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
    # Pre-validate before DROP so a bad file cannot wipe prior raw.* (S4 / F1).
    for path in landing_files:
        if path.exists() and path.stat().st_size > 0:
            _validate_landing_file(path)

    conn = duckdb.connect(db_path)
    try:
        # Idempotent rebuild (S2): clear prior raw.* so absent sources leave no table.
        conn.execute("DROP SCHEMA IF EXISTS raw CASCADE")
        conn.execute("CREATE SCHEMA raw")

        total = 0
        for path in landing_files:
            n = load_source(conn, path, run_id, loaded_at)
            total += n
            print(f"{path.name}: {n} rows -> raw.{path.stem}" if n else f"{path.name}: skipped (absent/empty)")

        print(f"run_id={run_id} loaded_at={loaded_at.isoformat()} rows={total} db={db_path}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
