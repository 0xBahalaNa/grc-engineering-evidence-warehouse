# s3_audit contract

Producer: `s3-audit` (SC-28 evidence). Extends the common core in `_core.md`.

## Status vocabulary (raw in fixtures → staging)

| Raw (fixture) | Normalized (staging) |
|---------------|----------------------|
| PASS          | PASS                 |
| WARN          | WARN                 |
| FAIL          | FAIL                 |

Encryption checks emit only `PASS` \| `FAIL`. Public-access-block checks can emit all three.

## Check catalog

| check_id | Meaning |
|----------|---------|
| `s3-bucket-encryption-enabled` | Bucket default encryption on/off |
| `s3-bucket-public-access-block-all-enabled` | All four PAB settings enabled |

## resource_id semantics

Bucket name (string). Strong identifier — one finding subject per bucket per check.

## Extension fields (mandatory)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `enc_type` | string, nullable | no | SSE algorithm, passed through from `SSEAlgorithm` — `AES256`, `aws:kms`, `aws:kms:dsse`. **Non-exhaustive** (AWS adds algorithms; DSSE-KMS arrived in 2023) — do not pin a closed `accepted_values` test on it. Present on encryption `PASS`; null otherwise. The SC-28 detail a bare core would drop. |

**Producer limitation:** both checks wrap the AWS call in a broad `ClientError`
handler that maps **any** client error (including `AccessDenied`) to `FAIL`,
printing the same "Not configured" line regardless of cause — false-FAIL risk
on a live retrofit.

Note this is the *only* path to an encryption `FAIL` — there is no
successful-response FAIL branch. **The intended trigger is stale on live AWS:**
since January 5, 2023, S3 applies SSE-S3 to every bucket as base-level
encryption, and `GetBucketEncryption` returns that default configuration for an
unconfigured bucket instead of raising. On a live retrofit the check's `FAIL`
path is reached in practice by other client errors (`AccessDenied` the
plausible one) — an error signal, not an encryption finding. Recorded, not
fixed: modernizing the check (e.g. asserting the algorithm rather than the
configuration's presence) is producer-repo work. The fixture's
`backups-unencrypted` row exercises the producer's `except` branch, which the
contract covers even though live AWS no longer produces its intended trigger.

Producer controls (SC-28) travel via `dim_controls` on `check_id` — not restated as this repo's controls.
