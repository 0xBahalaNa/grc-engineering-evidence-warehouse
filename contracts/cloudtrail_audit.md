# cloudtrail_audit contract

Producer: `cloudtrail-audit` (AU-2 / AC-6(9) evidence). Extends the common core in `_core.md`.

## Status vocabulary (raw in fixtures → staging)

| Raw (fixture) | Normalized (staging) |
|---------------|----------------------|
| CRITICAL      | FAIL                 |
| WARN          | WARN                 |
| INFO          | WARN                 |

Lossy by design: `INFO` is benign-but-noteworthy, not a control PASS — do not map to `PASS`.
`native_severity` (extension) preserves the original so the map stays reversible.
No `PASS` rows — detection-oriented producer. By design.

## Check catalog

| check_id | Raw severity | Meaning |
|----------|--------------|---------|
| `root-account-usage` | CRITICAL | Root account activity in the lookup window |
| `failed-api-call` | WARN | API call that returned an error |
| `sensitive-api-call` | INFO | Sensitive API invoked |
| `console-login` | INFO | Console login event |

**Emission grain:** the producer's four checks are independent, non-exclusive `if`s —
one CloudTrail event can emit up to four finding rows. In particular, `ConsoleLogin`
is also in `SENSITIVE_EVENTS`, so one real login emits **both** a `sensitive-api-call`
row and a `console-login` row (same `event_time` / principal). The fixture models
that double-emission intentionally.

**Population cap:** the producer calls `lookup_events(MaxResults=50)` and reads only
the first page — no `NextToken` pagination. `LookupEvents` returns events
reverse-chronologically, so on any account with more than 50 events in the 24-hour
window the producer analyzes the **newest 50** and the **oldest events in the window
are silently dropped**. Findings from this source are a truncated slice, **not the
population**.

This gap is invisible to the warehouse's own completeness test:
`completeness_expected_sources` proves the source **reported** in a given `run_id` —
it does not prove the source reported **everything**. A run where root activity fell
outside the newest-50 slice still builds green. Gaps of this class are recorded
throughout `contracts/` — e.g. `sg_audit.md` (IPv4-only rule reads), `evidence_logger.md`
(undetected wildcard forms) — because producer-side coverage is outside what this
warehouse's tests can assert. Recorded here, not fixed: pagination belongs to the producer's `--json`
retrofit (`cloudtrail-audit`), and until then `cloudtrail_audit` evidence is complete
only with respect to its page-one window.

## resource_id semantics

CloudTrail findings often have **no AWS resource**. Fallback chain (settled 2026-07-15):

1. `principal` where **present** (non-null **and** not the string `'N/A'`)
2. else `event_source`
3. else literal `'ACCOUNT'`

**Exception — `root-account-usage`:** always set `resource_id` to `'ACCOUNT'`
(account-level subject), even when `event_source` is populated.

Primary subject = account/principal/event source — consistent with `_core.md`'s
subject-identifier wording.

## Extension fields (mandatory)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `event_time` | timestamptz | yes | CloudTrail `EventTime`. **Keep separate from `collected_at`.** |
| `event_name` | string | yes | API / event name. Populated on all four checks — root / failed / sensitive carry it from the producer dict; `console-login` rows are always the literal `ConsoleLogin`. No legal null case. |
| `event_source` | string, nullable | no | Service source when the producer's dict stores it (root, sensitive). **Null on failed-api-call and console-login** — those dicts omit it, though the producer has the value in scope for every event (`cloudtrail_audit.py:110`). Promoting it to required is a candidate contract revision at `--json` retrofit time. |
| `principal` | string, nullable | no | Short CloudTrail `Username`; producer defaults to the literal `'N/A'` when absent (`cloudtrail_audit.py:111`), or the field is absent entirely on root findings. Sentinel handling below. |
| `error_code` | string, nullable | no | Present on failed API calls only |
| `source_ip` | string, nullable | no | Present on console-login findings; null on other checks. Producer defaults to the literal `'N/A'` when CloudTrail omits `sourceIPAddress` (`cloudtrail_audit.py:155`). Sentinel handling below. |
| `native_severity` | string | yes | Raw `CRITICAL` / `WARN` / `INFO` before normalization |

**Sentinel handling (`principal`, `source_ip`).** These fields go absent two different
ways, and the distinction matters to an emitter:

- **Key omitted.** Where a check does not capture the field, it is absent from the
  producer's dict entirely — `principal` on `root-account-usage` (the root dict has no
  user key at all), `source_ip` on every check except `console-login`.
- **Defaulted to a sentinel.** Where a check *does* capture it, the producer defaults a
  missing value to the literal string `'N/A'` rather than to a null
  (`cloudtrail_audit.py:111`, `:155`).

One rule covers both: fixtures store the **producer value verbatim** where it exists
(fidelity — the `sensitive-api-call` row carries `"principal": "N/A"` to exercise this)
and `null` where the key is absent; **staging normalizes `'N/A'` → `NULL`** for both
fields. That is the same raw-in / normalized-out treatment `status` gets. Nothing
downstream of staging should read `'N/A'` as a real principal or origin IP. The
`resource_id` fallback chain above states the guard explicitly for `principal`, so the
rule holds regardless of normalization order.

Producer controls travel via `dim_controls` on `check_id` — not restated as this repo's
controls. The source is **AU-2** evidence overall; `root-account-usage` additionally
evidences **AC-6(9)** (log use of privileged functions). That check is why the seed's
`check_id` → control mapping is one-to-many.
