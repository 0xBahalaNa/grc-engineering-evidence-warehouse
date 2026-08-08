# evidence_logger contract

Producer: `evidence-logger` (AC-6 / AC-3 evidence). Extends the common core in `_core.md`.

## Status vocabulary (raw in fixtures → staging)

| Raw (fixture) | Normalized (staging) |
|---------------|----------------------|
| FAIL          | FAIL                 |

Producer today writes only `[FAIL]` finding lines to the evidence file via
`f.write` (no PASS or WARN path); the confirmation line is the only `print`.
Fixtures store unbracketed `FAIL` (brackets are display formatting). FAIL-only
is by design — exempt from the ≥1 WARN fixture rule in `_core.md`.
The summary line `Result: N issues found` is **not** a finding — drop it (wrong grain;
see `_core.md`).

## Check catalog

| check_id | Meaning |
|----------|---------|
| `wildcard-action` | Policy `Action` is the exact scalar `*` |
| `wildcard-resource` | Policy `Resource` is the exact scalar `*` |

The producer tests only `Action` / `Resource` against the exact scalar `"*"`, and never
reads `Effect`. Known blind spots, at least:

- **List-form** wildcards (`["*"]`) — an array is never equal to the scalar. Missed.
- **Scalar partial** wildcards (`"s3:*"`, `"iam:*"`) — service-prefixed, not a bare star. Missed.
- **`NotAction` / `NotResource`** grants — legal IAM, and can be as broad as a wildcard. Missed.
- **`Effect: Deny`** statements — a `Deny` on `Action: "*"` is a *guardrail*, but the
  producer flags it `FAIL` identically to an `Allow`. A **false positive** — the opposite
  direction from the misses above.

Closing one does not close the others. All are out of scope for this contract; fixtures
reflect what the producer actually detects against `test_policy.json`.

## resource_id semantics

Policy statement `Sid` when present; otherwise the producer renders optional Sid
as the literal string `'None'` (an f-string artifact of `statement.get('Sid')`
returning Python `None`). **Fixtures store that sentinel verbatim** (raw-in);
**staging normalizes `'None'` → `NULL`** via `nullif` — the same
raw-in / normalized-out doctrine CloudTrail applies to `'N/A'`. A Sid-less
statement genuinely has no primary subject identifier; forcing a non-null value
collapses every Sid-less finding onto one shared subject.

The v1.0 fixtures include both shapes: two rows from `DangerousAdmin` on
`test_policy.json` (`resource_id: DangerousAdmin`), and one Sid-less row on
`no_sid_policy.json` (`resource_id: "None"` → `NULL` after staging).
Weak/synthetic identifier when present — the real audited artifact is
`policy_file` (extension). Natural key is
`(check_id, resource_id, policy_file, violated_attribute)` (see `_core.md`
Finding identity). **Known limit:** two Sid-less statements that fail the same
check in one file are distinct findings but share that key after `'None'` →
`NULL`, so `tests/unique_stg_evidence_logger.sql` red-builds on valid evidence.
Fixing it needs a producer-side statement index at `--json` retrofit; a
synthetic ordinal is rejected.

## Extension fields (mandatory)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `policy_file` | string | yes | Audited artifact (v1.0 fixture: `test_policy.json`) |
| `violated_attribute` | string | yes | `Action` or `Resource` — which attribute failed the check |
| `raw_message` | string, optional | no | Human-readable finding line; prefer producer-verbatim when available. |

Producer controls (AC-6 / AC-3) travel via `dim_controls` on `check_id` — not restated as this repo's controls.
