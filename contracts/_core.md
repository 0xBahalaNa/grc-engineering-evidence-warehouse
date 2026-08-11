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
| `resource_id` | per-finding | string (nullable after staging) | yes in fixtures | Finding's **primary subject** identifier (resource ARN/name today; identity/principal later). Not "the resource." Fixtures always carry the field; staging may null sentinels (e.g. evidence_logger `'None'`). See per-source semantics. |
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

## Run semantics

`raw.*` is a **rebuild-per-load snapshot**. Each loader invocation drops and
recreates the `raw` schema, so the warehouse holds **exactly one run at a time**.
`run_id` is a **provenance stamp** (which collection produced this row, and when)
— not a history key and not a partition for multi-run queries.
`select count(distinct run_id) from fct_findings` returns 1 by construction.

The loader also writes `raw.load_manifest`: one row per landing file processed
(including a file that is an empty JSON array, with `row_count = 0`). A source
**absent from the landing directory** produces **no** manifest row. Completeness
(`tests/completeness_expected_sources.sql`) joins `seeds/expected_sources.csv` to
this table — missing collector → build failure; `row_count = 0` → completeness
**passes** (reported, found nothing). Reconciliation
(`tests/reconciliation_raw_to_staged.sql`) compares `row_count` to staged
`count(*)` per `(run_id, source)`. Known limit: a zero-finding source still
leaves no `raw.<source>` table (by design — D2), so `dbt build` errors on that
path until staging tolerates a missing raw table (follow-up issue). Do not read
`row_count = 0` as "the build stays green." `row_count` is loader-generated
(`BIGINT`), not producer data — the deliberate exception to the D11 VARCHAR pin
on finding columns.

Multi-run retention (append-only or run-partitioned raw) is a separate design
change, deferred outside v1.0.

## Finding identity

Uniqueness is defined **per source** at staging, where a natural key holds.
`check_id` namespace ownership is `(source, check_id)` — not global. The mart
(`fct_findings`) carries no uniqueness test: the six-field core is a union spine,
not a grain key.

| Source | Natural key | Enforced |
|---|---|---|
| `s3_audit` | `(check_id, resource_id)` | yes — `tests/unique_stg_s3_audit.sql` |
| `sg_audit` | `(check_id, resource_id, from_port, to_port, cidr_ip)` | **partial** — `tests/unique_stg_sg_audit.sql`; no `ip_protocol` in contract, so tcp/22 vs udp/22 collide |
| `evidence_logger` | `(check_id, resource_id, policy_file, violated_attribute)` | yes — `tests/unique_stg_evidence_logger.sql`; **known false alarm:** two Sid-less statements failing the same check in one file are distinct findings but share a NULL `resource_id`, so the test red-builds on valid evidence |
| `cloudtrail_audit` | **none available** | **no — declared gap** |

**Declared gaps / partial keys.** CloudTrail's producer emits no `eventID`. Any
composite built from `(check_id, resource_id, event_time, event_name)` can still
collide (two identical API calls in the same second). See
`contracts/cloudtrail_audit.md`; the `--json` retrofit must carry `eventID`.
`sg_audit` lacks `ip_protocol` (producer does not emit it today) — tcp/22 and
udp/22 on the same SG + CIDR share the staged key and **red-build** if both are
present (false alarm), matching `contracts/sg_audit.md`.
`evidence_logger` includes `resource_id` (Sid) so two Sid'd statements in one
file are distinct. **Known limit:** two Sid-less statements failing the same
check in one file are distinct findings but share the key (`resource_id` is
NULL after staging; `GROUP BY` treats NULLs as equal), so the uniqueness test
**red-builds on valid evidence**. Fixing it needs a producer-side statement
index at `--json` retrofit; a synthetic ordinal or hash is rejected — a test
that cannot fail is worse than no test.

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
- Producer sentinels stay raw in fixtures (`'N/A'`, `'None'`); staging normalizes
  them to `NULL` where the per-source contract says so
