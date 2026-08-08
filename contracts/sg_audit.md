# sg_audit contract

Producer: `sg-audit` (SC-7 evidence). Extends the common core in `_core.md`.

## Status vocabulary (raw in fixtures → staging)

| Raw (fixture) | Normalized (staging) |
|---------------|----------------------|
| FAIL          | FAIL                 |
| WARN          | WARN                 |

No `PASS` rows — compliant security groups emit no finding (detection-only). By design.
Producer print lines use `[FAIL]` / `[WARN]`; fixtures store unbracketed `FAIL` / `WARN`.

## Check catalog

| check_id | Meaning |
|----------|---------|
| `open-to-internet-risky-port` | Ingress from `0.0.0.0/0` where `from_port` is in the risky set (`FAIL`) |
| `open-to-internet-nonrisky-port` | Ingress from `0.0.0.0/0` where `from_port` is **not** in the risky set (`WARN`) — includes numeric non-risky ports **and** the string sentinel `All` |

Risky ports in the producer: `{22, 3389, 3306, 5432, 1433, 27017}` (integers only).

**Severity inversion (producer design):** the producer classifies on `from_port`
set-membership **alone** — the rule's lower bound. Two consequences, both
producer-faithful and neither a warehouse choice:

- **The `All` sentinel.** When AWS omits `FromPort`/`ToPort`, the producer sets
  both to the string `'All'`. `'All' in RISKY_PORTS` is False, so an ALL-traffic
  rule (every port, including 22/3389) classifies `open-to-internet-nonrisky-port`
  /`WARN` — inverted vs a single-port SSH `FAIL`. The fixture's `wide-open-sg`
  row models this.
- **Numeric ranges.** A range whose lower bound is not itself risky but which
  *spans* a risky port (e.g. `20`–`25` covering SSH 22, or `3000`–`4000` covering
  3306/3389) also classifies `WARN`. `to_port` is never consulted.

Neither is fixed here — the contract records the producer as it is. A consumer
must not read `WARN` as "no risky port exposed."

**Population gap:** the producer reads only IPv4 `IpRanges`. An SG open via
`Ipv6Ranges` `::/0` (even on port 22) emits **no** finding.

## resource_id semantics

Security group id (`sg-…`). Strong identifier. Human label lives in the `sg_name` extension.

## Finding identity (partial key)

Natural key enforced at staging:
`(check_id, resource_id, from_port, to_port, cidr_ip)` —
`tests/unique_stg_sg_audit.sql`. **Partial:** the producer does not emit
`ip_protocol`, so tcp/22 and udp/22 on the same SG + CIDR are indistinguishable
and would red-build if both were present. Declared here and in
`contracts/_core.md`; adding `ip_protocol` is a contract + `--json` retrofit
change, not an invented ordinal. See `_core.md` ## Finding identity.

## Extension fields (mandatory)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `from_port` | JSON string → `VARCHAR` | yes | The producer's raw `FromPort` value (`rule.get('FromPort', 'All')`, `sg_audit.py:76`): a port on TCP/UDP rules; the ICMP type (`-1` = all types) on ICMP rules; the string sentinel `All` when AWS omits the key. Serialized as a JSON string per the pin below. |
| `to_port` | JSON string → `VARCHAR` | yes | The producer's raw `ToPort` value: range upper bound; the ICMP code (`-1` = all codes) on ICMP rules; `All` when AWS omits the key. The producer computes it (`rule.get('ToPort', 'All')`, `sg_audit.py:77`) but **never reads it** — classification and both print lines use `from_port` alone, so `to_port` reaches no output today. Required here because the `--json` retrofit can always compute it from that expression. |
| `cidr_ip` | string | yes | Always `0.0.0.0/0` at finding time in v1.0 (producer-guarded). |
| `sg_name` | string | yes | Human-readable SG name. |

**Port serialization is pinned to strings.** The producer's `rule.get('FromPort', 'All')`
returns a native `int` when AWS supplies `FromPort` and the `str` `'All'` otherwise. Emitters
(fixtures today, `--json` later) MUST serialize ports as JSON **strings** — `"22"`,
never `22` — so one port never lands as two distinct values and splits aggregation.

Producer controls (SC-7) travel via `dim_controls` on `check_id` — not restated as this repo's controls.
