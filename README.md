![License](https://img.shields.io/badge/License-MIT-green?style=flat)
![NIST 800-53](https://img.shields.io/badge/NIST-800--53%20Rev%205-004990?style=flat)
![FedRAMP](https://img.shields.io/badge/FedRAMP-High%20Baseline-0071bc?style=flat)
![CJIS](https://img.shields.io/badge/CJIS-Security%20Policy%20v6.0-cc0000?style=flat)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![dbt](https://img.shields.io/badge/dbt-duckdb-FF694B?style=flat)
![DuckDB](https://img.shields.io/badge/DuckDB-warehouse-fff100?style=flat)

# GRC Engineering Evidence Warehouse

The missing layer *after* the audit scripts run. Four producer repos ([`s3-audit`](https://github.com/0xBahalaNa/s3-audit), [`sg-audit`](https://github.com/0xBahalaNa/sg-audit), [`cloudtrail-audit`](https://github.com/0xBahalaNa/cloudtrail-audit), [`evidence-logger`](https://github.com/0xBahalaNa/evidence-logger)) each check a slice of an AWS account and report findings — and the findings evaporate at the terminal. This warehouse treats audit evidence as a data product: producer outputs land as raw records in DuckDB, dbt stages and unifies them into a queryable findings model, dbt tests enforce that the evidence population is complete and reconciled, and dbt docs publish the lineage from API call to finding.

The claim this repo exists to back up: **collecting evidence is not enough — you have to be able to prove the evidence set is complete, and show the lineage.**

> **Status:** v1.0 in development (July 2026). Contract-first build — the warehouse publishes a findings schema per source and builds against checked-in JSON fixtures; live producer wiring (`--json` output PRs) follows.

## Why This Exists

An evidence population with a silently missing source is the classic audit failure: the S3 collector erroring out doesn't make the account compliant, it makes the evidence *incomplete* — and absence of findings reads as absence of problems. Point-in-time scripts can't defend against that; a warehouse with completeness tests can. The same logic an IT auditor applies to a user-access-review population pull (is this the *whole* population? can you prove it?) is applied here to continuous-monitoring evidence: completeness and accuracy enforced in the pipeline itself, failing loudly instead of degrading silently.

The design is contract-first: none of the producers emits structured output today, so the warehouse owns the contract. Each source gets a documented findings schema, checked-in fixtures conform to it, and the entire dbt project builds and tests against those fixtures — the pattern warehouse teams use to develop against sources they don't control. Producers are then retrofitted to emit conforming JSON, one small PR each.

## Architecture Overview

```mermaid
graph LR
    subgraph P [Producers — fixtures now, live JSON later]
        A1[s3_audit.json]
        A2[sg_audit.json]
        A3[cloudtrail_audit.json]
        A4[evidence_logger.json]
    end
    A1 & A2 & A3 & A4 --> B["ingest loader (EL)<br/>stamps run_id + loaded_at"]
    B --> C[("DuckDB<br/>raw schema")]
    C --> D["dbt staging<br/>stg_* — one model per source"]
    D --> E["marts<br/>fct_findings + dim_controls"]
    E --> F["dbt docs<br/>source → mart lineage"]
    E --> G["Evidence.dev report<br/>(stretch)"]
    D -.->|"dbt tests: completeness ·<br/>reconciliation · schema"| E
```

The split is deliberately ELT: the Python loader does extract-and-load only — raw JSON files land in DuckDB `raw.*` tables with every row stamped with `run_id` and `loaded_at`, and nothing else. All transformation lives in dbt, where it is versioned, tested, and documented. Staging models normalize each source to one row per finding with consistent types and status values; the `fct_findings` mart unifies all sources into a single queryable evidence table, joined to `dim_controls` — a seed mapping every check to its NIST 800-53 / FedRAMP High / CJIS v6.0 controls.

## Compliance Controls Addressed

These are the warehouse's own controls. The producers' controls (SC-28, SC-7, AU-2/AC-6(9), AC-3/AC-6) travel with their findings through the `dim_controls` mapping.

| NIST 800-53 Rev 5 | FedRAMP High | CJIS v6.0 | How This Repo Validates |
|---|:---:|:---:|---|
| AU-6 | Yes | Weekly-review + 1-year-retention delta | The analysis layer over collector output — findings queryable by control family, status, and run |
| CA-7 | Yes | — | Repeated runs with completeness enforcement: a continuous-monitoring capability, not a one-off script |
| AU-9 / AU-12(3) | Yes | — | Evidence integrity — `run_id` stamping ties every row to its collection run; raw↔staged reconciliation makes any row-count change between landed and staged evidence a build failure |

Commercial crosswalk: the completeness and reconciliation tests are SOX ITGC vocabulary — completeness & accuracy (C&A) over evidence populations — applied to continuous monitoring instead of a quarterly population pull.

## The Tests Are the Control

The dbt tests aren't code hygiene — they are the control implementation:

- **Completeness** — every `run_id` is compared against an expected-sources manifest (a dbt seed). A collector that silently fails to report **fails the build**, converting a silent evidence gap into a loud pipeline failure.
- **Reconciliation** — raw row counts are reconciled to staged row counts per run; a divergence fails the build — a chain-of-custody break caught in the pipeline instead of during an auditor's re-performance.
- **Schema tests** — `not_null`, `accepted_values`, uniqueness. A finding without a `resource_id`, or with status `PASSED` instead of `PASS`, is evidence that can't be traced or aggregated. These pin the contract at the data layer, not just in a docs file.

## How an Auditor Uses This Output

When an assessor asks "show me the complete population of security checks run in this period," `fct_findings` answers it directly: filter by `run_id`, group by control family or status, and the completeness test result *proves* no collector is silently missing from the population — the question auditors otherwise resolve through sampling and re-performance. That proof is scoped honestly: a green build shows every expected source contributed findings to the run — it does not cover what each collector can see (known producer blind spots are documented per source in `contracts/`), and how a legitimately zero-finding source is represented is an open design decision ([#14](https://github.com/0xBahalaNa/grc-engineering-evidence-warehouse/issues/14)). The reconciliation tests compare raw to staged row counts per run, so a transformation that changes the row count between raw and staged fails the build instead of reaching an auditor, and `dbt docs` renders the full lineage from declared source to mart, so the path from API call to finding is inspectable rather than asserted.

This slots into the broader evidence loop as the transform-retain-review layers: producers detect, the warehouse lands raw records stamped with `run_id` and `loaded_at`, transforms them under test, and serves the review surface (AU-6) that turns collector output into audit-record analysis.

## FedRAMP 20x Alignment

- **Compliance-as-code:** the completeness and reconciliation controls are encoded as dbt tests that gate the build — control failure is pipeline failure
- **Machine-readable evidence:** a published contract per source (`contracts/`, versioned markdown) with conforming JSON fixtures; findings land in a queryable mart instead of terminal output. Machine-enforceable JSON Schema in CI is v1.1 — dbt schema tests pin the contract at the data layer today
- **Continuous monitoring:** run-versioned evidence with completeness enforcement across repeated runs (CA-7)
- **API-driven evidence:** DuckDB + dbt expose the findings model to any downstream consumer — reporting, OSCAL transformation, or dashboarding

## Sample Evidence Output

A `fct_findings` excerpt (v1.0 target shape, built from checked-in fixtures):

| source | check_id | resource_id | status | control_ids | run_id | collected_at |
|---|---|---|---|---|---|---|
| s3_audit | s3-bucket-encryption-enabled | backups-unencrypted | FAIL | SC-28 | 20260715T130000Z | 2026-07-15T12:00:00Z |
| sg_audit | open-to-internet-risky-port | sg-0abc123def456789a | FAIL | SC-7 | 20260715T130000Z | 2026-07-15T12:00:00Z |
| cloudtrail_audit | root-account-usage | ACCOUNT | FAIL | AU-2, AC-6(9) | 20260715T130000Z | 2026-07-14T21:00:00Z |
| evidence_logger | wildcard-action | DangerousAdmin | FAIL | AC-6 | 20260715T130000Z | 2026-07-14T21:00:00Z |

`status` above is the **normalized** mart value (`CRITICAL`→`FAIL` for root usage).
`control_ids` is the `dim_controls` join output — not carried in raw fixtures — and the
join is **one-to-many**: a single check can evidence several controls (root usage above).
`collected_at` is the producer's collection time (per the checked-in fixtures); `run_id`
stamps the load, so it always postdates the evidence it carries.

And the control doing its job — on the **next** run, `sg_audit` fails to report, and the completeness test fails the build rather than letting the population go quietly short:

```
FAIL 1 completeness_expected_sources
  Source 'sg_audit' is in the expected-sources manifest but absent
  from run_id 20260716T090000Z — evidence population incomplete.
```

## Requirements

- Python 3.11+
- [dbt-core](https://docs.getdbt.com/) with the [dbt-duckdb](https://github.com/duckdb/dbt-duckdb) adapter (bundles DuckDB)

## Usage

```bash
python ingest/load_raw.py --raw-dir raw/   # EL: land JSON into DuckDB raw schema (run_id + loaded_at)
dbt build                                  # models + tests — the control layer gates here
dbt docs generate && dbt docs serve        # browse source → staging → mart lineage
```

## Repository Structure

```
grc-engineering-evidence-warehouse/
├── contracts/            # findings schema per source — the published contract
├── fixtures/             # checked-in JSON conforming to contracts (permanent test data)
├── ingest/               # thin Python EL loader
├── models/
│   ├── staging/          # stg_s3_audit, stg_sg_audit, stg_cloudtrail_audit, stg_evidence_logger
│   └── marts/            # fct_findings, dim_controls
├── seeds/                # dim_controls mapping, expected-sources manifest
├── tests/                # completeness + reconciliation tests
└── README.md
```

## Future Enhancements

- `--json` output PRs on the four producers, conforming to the published contracts (`cloudtrail-audit` first — its finding dicts already exist in memory)
- Live end-to-end run: producers → landing directory → warehouse, no fixtures
- Evidence.dev thin reporting page over `fct_findings` (findings by control family, by status, by run)
- `iam-access-review` as a fifth source (August 2026) — a UAR-shaped source (identities and entitlements), exercising the contract design beyond resource findings

## What This Project Demonstrates

Audit evidence treated as a data product, with the data-engineering discipline that implies: contract-first development against sources the warehouse doesn't control, an explicit ELT split, staging/mart layering, and data tests used not as hygiene but as the control implementation — SOX-style completeness & accuracy reasoning applied to continuous-monitoring evidence. It's the difference between "I wrote scripts that check things" and "I can hand an assessor a defensible evidence population with provable lineage."

## References

- [dbt documentation](https://docs.getdbt.com/)
- [DuckDB documentation](https://duckdb.org/docs/)
- [NIST SP 800-53 Rev 5](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final)
- [FBI CJIS Security Policy](https://le.fbi.gov/informational-tools/cjis)
- Producer repos: [s3-audit](https://github.com/0xBahalaNa/s3-audit) · [sg-audit](https://github.com/0xBahalaNa/sg-audit) · [cloudtrail-audit](https://github.com/0xBahalaNa/cloudtrail-audit) · [evidence-logger](https://github.com/0xBahalaNa/evidence-logger)

## License

MIT
