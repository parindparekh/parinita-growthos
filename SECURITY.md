# Parinita GrowthOS v1.7.0 Security and Trust Model

## Authority separation
- Generation/planning/observation agents cannot approve a release.
- Human approvals bind to the governed `content_hash`.
- Only Feed Agent can cause outbound publication.
- Every send re-runs Gate and destination policy.
- Scheduled sends bind to the exact approved hash and become stale after governed edits.

## Chrysalis assurance
GrowthOS keeps an append-only local hash chain for operational verification. Chrysalis is the external assurance anchor.

When enabled:
- audit heads are submitted as `parinita.growthos.chrysalis.audit-head.v1`;
- governed release versions are submitted as `parinita.growthos.chrysalis.release.v1`;
- GrowthOS stores the Chrysalis receipt/reference and canonical payload digest;
- if Chrysalis echoes a digest it must match the submitted payload;
- high-risk or all publication can be configured fail-closed before any provider side effect.

This is an assurance boundary, not a claim that the source material itself is true.

## PR/media data
Media contacts and coverage are imported with provider attribution. GrowthOS must be deployed in accordance with the source provider's license, retention, contact-use and privacy terms. The application never invents journalist records.

## Claim Graph
The Claim Graph records provenance and observed relationships. Exact source-URL matches can create AEO citation edges; lexical coverage matching is labeled with a match score. Neither constitutes causal proof.

## Existing controls retained
- Witness-ready OIDC/PKCE and bearer validation.
- Named API principals and role checks.
- Four-eyes high-risk approval policy.
- SSRF/egress protection and secret-name boundary.
- Idempotent provider deliveries.
- Append-only audit DB triggers and verifier.
- Size-limited/defused feed parsing.
- Rate limiting and security headers.
- Provider adapter destination policy and classification opt-in.

## v1.7 destinations and channel agents

- Every new adapter resolves credentials only from `GROWTHOS_SECRET_*`; webhook URLs that are themselves credentials
  (Google Chat, Mattermost) must be referenced as secrets, never written in endpoint config.
- Adapters never retry a request that may already have been processed (Reddit, Meta, Pinterest, TikTok, Tumblr, Lemmy,
  Shopify, Dev.to, Ghost, Buttondown, Zulip). Matrix and Etsy are idempotent by protocol; Mailchimp, Instagram and
  Threads resume from a stored container/campaign id.
- TikTok defaults to `MEDIA_UPLOAD` + `SELF_ONLY` (creator reviews in-app before anything is public).
- Channel agents inherit the model-output drift guard; their copy is only used for the exact content version it was
  generated from, and they hold no publish, approve or waive authority.

## v1.6.1 hardening (review findings closed)

| Finding (v1.6.0) | Severity | v1.6.1 control |
|---|---|---|
| An **editor** could run `POST /v1/aeo/probes/run` against any public URL with `bearer_token_env` naming *any* `GROWTHOS_SECRET_*` variable, exfiltrating provider, messaging or Chrysalis tokens to a host of their choosing. | High | Probes may only reference secrets under `AEO_PROBE_SECRET_PREFIX` (`GROWTHOS_SECRET_AEO_*`). Enforced in `aeo.run_rest_probe`; regression test. |
| Rate limiter keyed on the presented credential: random API keys minted fresh buckets, so credential guessing was unlimited and the bucket table grew without bound. | High | Every request is also charged to its source address (`RATE_LIMIT_PER_IP_PER_MINUTE`); bucket table is a bounded LRU (`RATE_LIMIT_MAX_BUCKETS`). `FORWARDED_ALLOW_IPS` documented so the real client address is seen behind a proxy. |
| Chrysalis receipts were trusted on HTTP 200 + any `id`; the digest echo was optional and no signature was checked, so a compromised or mis-pointed ingress could mint "anchored" status. | High | Mandatory digest echo (`CHRYSALIS_REQUIRE_RECEIPT_DIGEST`) and Ed25519/ECDSA receipt signature verification (`CHRYSALIS_RECEIPT_VERIFY_KEY`); https required in production. |
| Approval bound the content hash but not reviewer dispositions: with `GATE_WAIVER_ROLE=editor`, an editor could waive open sentences *after* an approver's approve-while-blocked and the release became releasable without the approver seeing the waivers. | High (governance) | Approvals record `dispositions_hash`; a waiver by a non-approver makes the approval stale (blocker: "sentence dispositions changed after it was approved"); approver waivers re-bind it. Legacy approvals keep old semantics. |
| Chrysalis `_anchor` committed mid-publish, releasing the publisher's row lock before the delivery slot was claimed. | Medium | Publish path anchors with `commit=False`; anchor and delivery claim commit together. |
| `safe_post` buffered unbounded responses from Chrysalis / answer engines. | Medium | Streamed with a hard cap (`MAX_FEED_BYTES`, 1 MB for Chrysalis). |
| `POST /v1/content/{id}/chrysalis/attest` echoed raw exception text (could include transport detail). | Low | Only GrowthOS's own refusal messages are returned; transport errors are 502 with the exception type. |
| Landing page `/` shipped an inline `<style>` under a CSP of `style-src 'self'`: rendered unstyled. | Low | Styles moved to `/console/landing.css` (fixed allowlist). |
| No HSTS header. | Low | `Strict-Transport-Security` in production. |

## Production requirements
Use TLS, network egress policy, secret manager injection, distributed/edge rate limiting at scale, production PostgreSQL backups, live Witness role validation, live Chrysalis receipt verification and per-provider acceptance before GA.

## v1.8 changes

Enabled production Chrysalis requires digest echo and a signing verification key. Cached release attestations recheck Gate, exact approval/disposition binding and current trust key; names and content hashes alone are insufficient. Non-editor/non-admin contact-list callers see a blank email field. Shared provider replies are capped with no automatic retry after an oversized ambiguous response. See `REVIEW.md` for tests and precise limits.

Known residuals: DNS prevalidation is not connection-time IP pinning; rate limits are in-process; no multi-tenant isolation guarantee is made. Provider tokens still require operator-managed renewal. Dependency hashes ensure artifact identity, not lack of known vulnerabilities.
