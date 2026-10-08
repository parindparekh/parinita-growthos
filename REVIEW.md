# Parinita GrowthOS v1.8.0 — Independent review and improvement report

Release date: October 8, 2026. Reviewed the attached v1.7.0 source and review, reproduced tests, then implemented a focused v1.8 upgrade. This report supersedes the supplied review's mixed v1.6.1/v1.7 statements. It does not claim external deployment acceptance.

## Rating

**As shipped: 8.3/10 as a deployment candidate. Improved: 9.0/10 as a locally verified deployment candidate.** A “20/10” label would be marketing; target-host readiness and live integration cannot be scored as proven from this packet.

| Dimension | v1.7 | v1.8 | Reason |
|---|---:|---:|---|
| Architecture | 9.0 | 9.0 | One governed release, one proof path, many channels; clean authority separation. |
| Release assurance | 8.0 | 9.2 | Production verification now mandatory; reuse bound to current Gate, approval/dispositions and trust key. |
| Privacy and request robustness | 8.2 | 9.0 | Journalist emails role-restricted; common provider replies streamed under a hard cap. |
| Agent clarity | 7.8 | 9.0 | 28 capabilities have scoped identities, stable IDs and reserved-name checks. |
| Product depth | 8.0 | 8.0 | Strong communications workflow; licensed PR data, token renewal and native inbox breadth remain deployment/product work. |
| Supply chain and packaging | 7.2 | 8.8 | Transitive hash locks, CycloneDX inventory, CI definitions and current release docs. |
| Local verification | 8.8 | 9.5 | Baseline 285/285 and upgraded 302/302; browser and official SDK interop exercised. |
| Live deployment evidence | 6.5 | 6.5 | PostgreSQL/Docker/Witness/Chrysalis/providers not exercised on the target host. |

These ratings are engineering judgment, not a certification or computed average.

## What is strong

The governed release contract is the real differentiator: sources/claims, channel variants, approval, Gate, destination classifications, delivery idempotency and assurance remain on the same content version. Channel copy is drift-checked. Non-idempotent sends avoid automatic retries after ambiguous transport outcomes. A local append-only hash chain supplies operational evidence. Human authority stays distinct from agent preparation and publishing credentials.

## New findings and shipped fixes

| Severity | Finding in v1.7 | v1.8 fix | Verification |
|---|---|---|---|
| High, configuration-dependent | Enabled production Chrysalis accepted unsigned and digest-less receipts by default. Key/digest checks were optional, despite strong wording in the supplied review. | Production startup requires digest echo and a usable signing key whenever Chrysalis is enabled; verification also rejects a runtime downgrade. | 3 production-policy regressions plus existing signature/digest tests. |
| High for direct attestation correctness | `anchor_release` returned a matching prior content-hash attestation before Gate evaluation. Existing approval/disposition and key changes were not part of reuse. The normal publish route separately checked Gate, so this was not a demonstrated bypass of every publish check. | Gate first; bind reuse to release ID/hash/classification, full approval object and dispositions; reverify the original receipt against the current key. Legacy unbound receipts reanchor. | Revoked approval, changed approval, unchanged reuse and key-rotation tests. |
| Medium | Contact-list emails were returned to every authenticated principal. | Email field blank unless principal has editor/admin authority; other fields and response shape preserved. | Five role-specific privacy cases. |
| Medium | Shared provider helper buffered arbitrary response bodies although other egress paths had a cap. | Use streamed capped requests; oversized replies report uncertain outcome and never auto-retry. | Oversized non-idempotent provider response produces one request only. |
| Low | Receipt references coerced booleans, numbers and objects into strings. | Require nonblank string references and strict base64 parsing. | Four malformed-reference cases plus signature regressions. |
| Packaging | Stale v1.6 Word deliverables; no hash lock, runtime inventory or CI definition. | Current Markdown white paper, operating guide, claims audit, review and naming register; hash locks, CycloneDX inventory and CI definitions. | Hash-locked installation checked; archive manifest regenerated and verified. |

The regression module adds **17 test cases**. Existing tests are adapted only where display names intentionally changed; capability IDs and permissions are preserved.

## Naming and collision audit

Checked current `parinita_product_set.json`, the naming section of `Parinita_Master_Context_Brief_v3_Technical.md`, retrieved later decisions and the user's latest corrections. The earlier register did not contain every existing product. **Reach, Compass, Sentinel and Senitene are reserved and excluded**, alongside Forge, Lens, Marshal, Conductor and the wider known occupied set.

Core GrowthOS identities: **Scout, Envoy, Curator, Orator, Ripple, Broadcaster, Liaison, Magnet, Courier, Scribe, Cartographer, Gauge, Scrutineer, Convenor, Cadence.** Broadcaster replaces Reach; Cartographer replaces Compass; Scrutineer replaces Sentinel. No existing ownership for the replacements was found in retrieved context; this is not a claim of global uniqueness.

Channel specialists use qualified names such as `Parinita GrowthOS Ripple / Instagram` and `Parinita GrowthOS Magnet / Etsy`. Fifteen core identities and thirteen scoped specialists cover 28 capabilities. Names appear in the manifest, prompts, new audit events and agent-history metadata. Existing audit events are preserved. See `docs/AGENT_NAMING.md` for the complete ID mapping, source scope and reserved names.

## Verification actually performed

- Original checksum manifest: **123/123 files verified**.
- Original v1.7 suite: **285 passed, 0 skipped, 0 failed** (Python 3.12, SQLite, browser and separate MCP SDK enabled).
- Final v1.8 suite: **302 passed, 0 skipped, 0 failed**, one complete run; raw JUnit evidence and summary included.
- Five console/browser checks and three independent MCP SDK interop cases run as part of the full suite. Provider acceptance uses local test servers, not real social accounts.
- Runtime/development dependencies are transitive and hash-locked; installation against the development lock succeeded. The inventory derives from the runtime lock; no vulnerability-scan conclusion is implied.
- No Docker binary/target PostgreSQL service was available for target-host validation. The checked-in CI workflow defines these checks but has not run in hosted CI.

The first attempt at running tests inherited this workstation's proxy environment and failed local HTTP fixtures. Removing proxy variables for local test execution resolved the environment problem; no proxy-sensitive product behavior was silently changed. Only the successful controlled runs are release evidence.

## What it takes to meet the user's “20/10” objective

1. **Prove the deployed trust boundary.** Run actual PostgreSQL/Docker/worker acceptance, Witness identity roles, and deployed Chrysalis receipt-profile compatibility. Include wrong-key, wrong-digest, revoked approval and receipt-key rotation refusal evidence.
2. **Certify the channels actually used.** Record live account scopes, approved media hosting, response shapes, resume checkpoints and ambiguous-send reconciliation. Thirty-seven coded protocols are not thirty-seven live production certifications.
3. **Make daily operation self-maintaining.** Add provider-specific OAuth/token renewal with revocation and account isolation; current token renewal is operator-managed. Native inbox ingestion is not complete across all providers.
4. **Strengthen intelligence with real licensed data.** Keep provider rights and attribution. Ranking uses transparent lexical overlap and recorded activity, not a proprietary journalist corpus or truth oracle.
5. **Close infrastructure residuals.** Application DNS prevalidation still has a rebinding race; use egress enforcement. In-process rate limiting is not distributed. Graph and media ranking still scan potentially large collections; add indexed normalized citation/beat tables before growth warrants them.
6. **Demonstrate outcomes honestly.** Measure approved-release completion, publish refusal reasons, duplicate rate, uncertain-send reconciliation, time to approved story and observed conversion telemetry. Current performance recommendations are heuristics, not causal attribution or a proven autonomous revenue engine.

## Upgrade and deliverables

No new database schema is required. Stable API/MCP IDs and authority remain intact. Enabled production Chrysalis configurations without key/digest verification now fail closed at startup; supply valid configuration before rolling out. Legacy attestations require new evidence rather than inheriting the old trust default.

This packet is a hardened deployment candidate with tested code and current documentation. It is **not a live deployed system, a provider certification, a PQC receipt verifier, a complete multi-tenant SaaS platform, or proof of external-source truth**.
