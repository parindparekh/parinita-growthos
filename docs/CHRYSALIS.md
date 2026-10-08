# GrowthOS -> Chrysalis assurance contract

## Principle
GrowthOS owns communications workflow state and a local append-only hash chain. Chrysalis is the external assurance anchor. GrowthOS does not create a competing ledger.

## Audit head payload
`parinita.growthos.chrysalis.audit-head.v1` carries the verified GrowthOS `head_hash`, event count and observation time.

## Release attestation payload
`parinita.growthos.chrysalis.release.v1` carries the exact governed `content_id`, `content_hash`, classification, approval object, Gate checks and the current GrowthOS audit head.

The Chrysalis ingress must return JSON containing an `anchor_id`, `receipt_id`, `reference` or `id`. If it also returns `payload_hash` or `digest`, GrowthOS requires it to equal the submitted canonical payload digest.

## Fail-closed policy
`CHRYSALIS_FAIL_CLOSED_HIGH_RISK=true` makes Chrysalis attestation mandatory before Feed Agent can cause an external side effect for investor, regulated, legal, health or financial content. `CHRYSALIS_FAIL_CLOSED_ALL=true` extends the rule to every class.

## Lineage naming
GrowthOS uses **Claim Graph** for communications provenance. **Lineage** remains the Chrysalis causal-forensics component and may consume/inspect GrowthOS evidence downstream.

## Receipt verification (v1.6.1)

A receipt is only proof of what GrowthOS checks before storing it. Three checks run on every receipt, in order:

1. **Reference.** The receipt must carry an `anchor_id` / `receipt_id` / `reference` / `id`.
2. **Digest echo.** If the receipt carries `payload_hash` or `digest`, it must equal the SHA-256 of the canonical payload
   GrowthOS submitted. `CHRYSALIS_REQUIRE_RECEIPT_DIGEST=true` makes the echo mandatory (required when Chrysalis is enabled in production).
3. **Signature.** With `CHRYSALIS_RECEIPT_VERIFY_KEY` set (PEM, Ed25519 or ECDSA P-256), the receipt must carry a
   base64 signature in `CHRYSALIS_RECEIPT_SIGNATURE_FIELD` (default `signature`) over the canonical JSON
   (`sort_keys`, separators `,`/`:`, UTF-8) of every receipt field except the signature itself. An unsigned, tampered
   or wrongly-keyed receipt is recorded as `failed`, and fail-closed publication stays closed.

The stored receipt gains a `_growthos_verification` block (`digest_verified`, `signature_verified`, profile
`parinita.chrysalis.receipt-signature.v1`). Release payloads now also carry `dispositions_hash`, the digest of the
reviewer waivers in force, so the attested object includes the reviewer decisions that let it pass Gate.

In production `CHRYSALIS_ANCHOR_URL` must be `https://`. An unusable verification key is a startup error, not a runtime
surprise. During a publish the release anchor is committed together with the delivery claim (same transaction), so the
publisher's row lock is no longer released mid-request.

## v1.8 assurance reuse

Production with Chrysalis enabled requires HTTPS, digest echo, and an Ed25519 or ECDSA P-256 verification key. Unsigned receipts cannot be enabled as a production fallback. This is a classical receipt verification profile, not an ML-DSA/PQC verifier.

Gate is evaluated before looking up any cached release attestation. Reuse binds the release ID/hash/classification, full approval object, and reviewer dispositions. Approval changes or legacy receipts without this binding require a fresh attestation. A cached receipt is reverified under the current key and policy, so key rotation cannot reuse an unsigned or wrongly keyed receipt.

The `_growthos_release_binding` and `_growthos_verification` fields are local annotations added after verification; they are excluded when rechecking the original issuer signature. The deployed Chrysalis ingress must still demonstrate this receipt profile in a target-host acceptance run.
