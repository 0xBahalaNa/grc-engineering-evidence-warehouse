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

Policy statement `Sid` when present; otherwise the string `'None'` (producer renders
optional Sid that way). The v1.0 fixture's `test_policy.json` has two statements
(`AllowS3Read`, `DangerousAdmin`); both findings come from the **single**
`DangerousAdmin` statement failing two checks (`Action` and `Resource`), so both
fixture rows carry `resource_id: DangerousAdmin`. Weak/synthetic identifier — the
real audited artifact is `policy_file` (extension). See also issue #11 for Sid-less
grain risk.

## Extension fields (mandatory)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `policy_file` | string | yes | Audited artifact (v1.0 fixture: `test_policy.json`) |
| `violated_attribute` | string | yes | `Action` or `Resource` — which attribute failed the check |
| `raw_message` | string, optional | no | Human-readable finding line; prefer producer-verbatim when available. |

Producer controls (AC-6 / AC-3) travel via `dim_controls` on `check_id` — not restated as this repo's controls.
