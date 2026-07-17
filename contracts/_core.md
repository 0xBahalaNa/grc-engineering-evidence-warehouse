# Findings contract — common core

Every finding from every producer carries this common core. The warehouse **owns**
this contract: none of the four producers emits structured JSON today, so every
**stored** field below is authored by the warehouse and synthesized at
**fixture-authoring time** (later: in producer `--json` emitters). `control_ids`
is the one exception — it is **derived**, never stored in a fixture and never
producer-emitted (see its row). The loader stamps only `run_id` / `loaded_at`;
staging does not invent core fields. The core is a **normalization target**, not
a lift from producer code.

Per-source **extension fields** are mandatory (see `contracts/<source>.md`).
A bare core silently drops real evidence (encryption algorithm, port/CIDR,
event metadata, policy attribute).

**Type column note:** in `_core.md` and fixture JSON, Type describes the
**JSON/fixture shape** (e.g. string). Per-source contracts may also name the
**DuckDB cast target** after staging (e.g. `timestamptz`, `VARCHAR`) — that is
the warehouse column type, not a different logical field.

## Core fields (fixture shape)

| Field | Grain | Type | Required | Notes |
|-------|-------|------|----------|-------|
| `source` | per-finding | string | yes | Producer id (`s3_audit`, `sg_audit`, `cloudtrail_audit`, `evidence_logger`). Stored in each fixture (self-describing); not injected in staging. |
| `check_id` | per-finding | string | yes | Contract-authored check catalog id. **Only control key in the fixture** — join key into `dim_controls`. Kebab-case across all sources. |
| `resource_id` | per-finding | string | yes | Finding's **primary subject** identifier (resource ARN/name today; identity/principal later). Not "the resource." See per-source semantics. |
| `status` | per-finding | string | yes | **Outcome of the check/rule**, not resource health. Fixtures carry **raw** producer vocab; staging normalizes to `PASS` / `WARN` / `FAIL`. |
| `collected_at` | per-finding | string (ISO-8601 Zulu) → `timestamptz` | yes | Producer collection time (**not** load time — that is the loader's `loaded_at`). Authored in fixtures / stamped at producer emit time. Staging casts to **`timestamptz`** — same cast target as CloudTrail `event_time`, so the two never compare across a naive/aware boundary. **Not** `event_time` (that is a separate extension). |
| `control_ids` | derived | — | — | **Not stored in fixtures.** Joined output of `fct_findings` × `dim_controls` on `check_id`. Authoritative in the seed. |

## Forward-fit (v1.0 prose only — no schema change)

- **`resource_id`** = primary subject of the finding. Seats CloudTrail root findings
  (subject = account/principal) and the August `iam-access-review` UAR source
  (identities + entitlements) without reshaping the core.
- **`status`** = check/rule outcome. Detection-only producers may emit no `PASS`
  rows; that is by design.
- **`resource_type`** — name **reserved** here for a future additive column.
  Not materialized in v1.0.
- **`iam-access-review`** — anticipated fifth source (UAR-shaped). Documented
  here only; no `contracts/iam_access_review.md` and no fixture in v1.0.

## What does not belong on a finding row

Account- or file-level aggregates (`compliant_count`, `total_buckets`,
`issues_count`) are wrong grain. The mart derives them via `COUNT` / `GROUP BY`.

## Fixture rules (all sources)

- Pretty-printed JSON array in `fixtures/<source>.json`
- At least one row that **normalizes to FAIL** per source. Prefer also ≥1 row that
  **normalizes to WARN** when the producer emits a WARN-class outcome; FAIL-only
  producers (e.g. `evidence_logger`) are exempt from the WARN requirement — mirror
  the existing "no PASS rows by design" exemption
- Status is stored **unbracketed** (`FAIL` / `WARN` / `CRITICAL` / …); brackets in
  producer print output are display formatting only
- No `run_id` / `loaded_at` inside fixtures (loader stamps those)
- Status stays raw; normalization happens in staging
