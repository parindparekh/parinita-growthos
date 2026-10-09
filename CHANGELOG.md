## 1.9.1 — Connector setup and production hardening

All 37 outbound adapters and four feed formats are configurable from the console. Added configuration readiness checks, editable provider settings and a complete coverage register. Fixed empty-config validation bypass, malformed config handling, caller-forged server metadata, credential-bearing errors, draft-as-published reporting, HTML escaping and partial SMTP success reporting. Compose worker now mounts shared audio storage and exposes heartbeat health; CI boots the runtime stack. Target-cluster and live-account acceptance remain outstanding.

# Changelog

## v1.8.0 — 2026-10-08

- Collision-aware GrowthOS names with occupied products reserved; API IDs and permissions unchanged.
- Production receipt signatures/digest echo mandatory when Chrysalis is enabled.
- Release proof reuse rechecks Gate, exact authority binding and current receipt key.
- Journalist email visibility restricted to editor/admin.
- Shared provider responses streamed and bounded; uncertain sends never automatically retry.
- Hash-locked dependencies, runtime inventory, CI definitions and current documents.
- 17 new regression cases; final 302 passed with browser/MCP interop enabled.


## v1.7.0 - 2026-10-08 (destinations + channel agents)

### Destinations (19 new adapters, 37 total; all behind Gate / destination policy / idempotency / audit / Chrysalis)
- Social: `reddit` (link/self posts, refresh-token or script-app auth), `facebook` (Page feed), `instagram` (image
  container + publish, resumable), `threads` (text container + publish, resumable), `pinterest`, `tiktok` (photo posts,
  creator-review default), `tumblr` (NPF), `lemmy`.
- Commerce / local: `etsy` (shop announcement or listing copy), `shopify` (blog article), `google_business` (local post).
- Blogs / newsletters: `devto`, `ghost` (Admin JWT), `buttondown`, `mailchimp` (3-step campaign, resumable).
- Messaging: `google_chat`, `mattermost`, `matrix` (transaction id = delivery id), `zulip`.
- Image-only networks read `metadata.public.image_url` / `image_urls`; text-only releases are refused before any call.
- Documented as unsupported: YouTube community posts, Snapchat, Substack, Nextdoor, Medium, video surfaces.

### Channel agents (14 new agents; none can publish)
- `reddit`, `facebook`, `instagram`, `threads`, `pinterest`, `tiktok`, `tumblr`, `etsy`, `shopify`, `local`, `blog`,
  `newsletter`, `community`, plus the `channels` orchestrator. Each writes channel-native copy (model or deterministic,
  drift-checked per protocol with `gate.ungrounded_in`), reports destination readiness with reasons, and records the
  result under its own name. Adapters use that copy via `public_projection.channel_copy` for the exact content version.

### Validation
- 285 tests collected; **282 passed, 3 skipped, 0 failed** in one run (143 s). New: `tests/test_destinations_v17.py`
  (23 contract tests incl. resume/duplicate/governance cases), `tests/test_channel_agents.py` (7).


## v1.6.1 - 2026-10-08 (hardening release)

### Security
- AEO probes can only attach secrets named `GROWTHOS_SECRET_AEO_*` (`AEO_PROBE_SECRET_PREFIX`); closes an editor-level
  secret-exfiltration path through `POST /v1/aeo/probes/run`.
- Rate limiter now charges every request to its source address as well as its credential, and bounds its bucket table
  (LRU). New settings `RATE_LIMIT_PER_IP_PER_MINUTE`, `RATE_LIMIT_MAX_BUCKETS`; `FORWARDED_ALLOW_IPS` wired through compose.
- Chrysalis receipts are verified before they count: digest echo (optionally mandatory) and Ed25519 / ECDSA P-256
  signature verification (`CHRYSALIS_REQUIRE_RECEIPT_DIGEST`, `CHRYSALIS_RECEIPT_VERIFY_KEY`,
  `CHRYSALIS_RECEIPT_SIGNATURE_FIELD`). Production requires an https anchor URL.
- `safe_post` caps response size; the attest route no longer echoes transport exceptions; HSTS in production.

### Governance
- Approvals bind the reviewer dispositions in force (`dispositions_hash`) in addition to the content hash. A waiver
  recorded by a principal without the approver role after an approval makes that approval stale and must be re-approved;
  approver waivers re-bind it. Release attestation payloads carry `dispositions_hash`.

### Correctness
- Chrysalis release anchoring during publish no longer commits mid-transaction (row lock held until the delivery slot
  is claimed).
- Landing page styles moved to an external stylesheet; the page was rendering unstyled under its own CSP.

### Validation
- 255 tests collected; **252 passed, 3 skipped, 0 failed** in a single uninterrupted run (SQLite, 116 s).
- New `tests/test_v161_hardening.py` pins every finding above (15 tests).


## v1.6.0 - 2026-10-02

### Product gap closures
- Added provider-neutral PR/media intelligence: normalized contacts, coverage, transparent target ranking and coverage-linked claim observations.
- Added Signal Opportunity Queue combining earned media, high-priority inbox, AEO visibility gaps and performance learnings.
- Added GrowthOS Claim Graph: source -> approved claim -> governed release/version -> delivery / earned coverage / exact AEO citation / performance observations.
- Added native Chrysalis anchoring for audit heads and governed release attestations. High-risk publishing can fail closed before any external side effect.
- Added periodic worker-driven Chrysalis audit-head anchoring.
- PR Agent now returns ranked imported media targets; Social Agent includes observed performance learning.
- Growth Command Intelligence view now includes Opportunity Queue, earned media and Chrysalis status.
- Added Alembic revision `0002_v16_intelligence_chrysalis`.

### Naming / architecture
- GrowthOS uses **Claim Graph** for communications provenance.
- **Lineage** remains the Parinita Chrysalis causal-forensics component; no duplicate GrowthOS Lineage service is introduced.

### Validation
- 240 tests collected.
- Split validation: 232 passed, 8 skipped, 0 failed.
- v1.6-specific tests: media-target ranking, multi-stream opportunity fusion, Claim Graph, Chrysalis receipts, fail-closed high-risk publication.

## v1.5.0
Merged the hardened v1.4 line with the stronger v1.2 branch; added executable AEO, system-level agents, performance learning, rate limiting, Alembic baseline and current deliverables.
