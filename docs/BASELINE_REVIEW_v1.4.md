# Status after v1.4

| Added | Evidence | Still unproven |
|---|---|---|
| WhatsApp destination (approved templates, Cloud API) | 4 contract tests against a mock of the Messages endpoint, including resume after a partial failure | A live WhatsApp Business account, template approval, real delivery |
| Witness profile for sign-in | 3 tests against a mock IdP issuing Keycloak-shaped tokens (client roles in the access token, `azp` and subject checks) | A Witness realm |

## The other v1.2 packet (uploaded 2 October, 108 tests)

A second build exists that also calls itself v1.2. It branches from v1.1 and is not the v1.2 in this line.
I ran it: its 108 tests pass on SQLite and, which its own manifest says was not done, on PostgreSQL 16.

| | Other v1.2 | This line (v1.4) |
|---|---|---|
| Gate on plain unsourced prose ("Customers love it." in a PR release) | Passes with no warning; claim extraction is advisory | Blocked until sourced or let stand by a reviewer |
| Sign-in | Bearer JWT validation only (no browser sign-in, no session) | Browser sign-in with PKCE + bearer tokens, Witness profile |
| Operator surface | `/operator` page | `/console` with sentence proof, browser-tested |
| Destinations | webhook, SMTP, LinkedIn, WordPress | 18, including MCP, Vaak, WhatsApp |
| MCP | none | server and destination, SDK-verified |
| Only in the other build | Alembic migrations, per-process rate limiter, `anchor_audit.py`, PR / Social / Engagement agents, Word deliverables reissued for v1.2 | not yet merged |

The two should become one line. The five items in the last row are worth bringing across.

Rating for v1.4 stays at **8 / 10** for the same reason as before: the unproven column.

---

# Status after v1.3

| Added | Evidence | Still unproven |
|---|---|---|
| MCP server (`/mcp`) and MCP destination adapter, protocol 2026-07-28 with legacy fallback | 17 tests; the official MCP Python SDK 2.2.0 client drove a full draft-to-send flow against the server, and the adapter called an SDK-built server in JSON and SSE modes | Other SDKs and clients; OAuth-protected third-party servers; a Tapestry fabric |
| Parinita Vaak integration | 6 tests against a mock of the vaakd owner API; served audio hashes to the manifest's content digest | A real vaakd build (routes and auth are configurable for that reason) |
| Slack, Teams, Discord, Telegram, WordPress | 13 contract tests against mocks | Live workspaces and sites |

The agent surface was designed around one rule: an agent can do the work but cannot sign for it. There is no MCP
tool for approval, revocation or letting a sentence stand.

Rating stays at **8 / 10**. The surface is wider; the reasons it is not a 9 are unchanged (nothing here has run
against live providers, a commercial IdP, a vaakd build or a Docker host).

---

# Status after v1.2

v1.1 was held at 7 / 10 by four open items. This is where each stands now, and what I would rate it.

| Open item in v1.1 | v1.2 | Evidence | What is still open |
|---|---|---|---|
| No provider adapters for social, podcast hosts or PR wires | LinkedIn, X, Mastodon, Bluesky, Transistor, Buzzsprout and a PR-wire handoff, all behind the gate, destination policy, idempotency and audit | 29 contract tests against mocks of each documented API; X's OAuth 1.0a signature verified with an independent library; SMTP over a real socket | **Not run against live accounts.** No token refresh for LinkedIn (60-day) or X OAuth 2.0 (2-hour) tokens. No media upload. The major wires have no self-serve API, so `pr_wire` is a handoff (desk email or your contracted endpoint), not a native integration |
| No operator UI | Growth Command at `/console` | 5 browser tests in headless Chromium, including an XSS probe and a full blocked-to-sent run; screenshots reviewed at desktop and phone width | Destinations are created through the API, not the console. Chromium only. No bulk actions |
| API keys rather than SSO | OpenID Connect for the console, IdP bearer tokens for the API, group-to-role mapping; approvals require an SSO identity once SSO is on | 26 tests against a mock IdP with real RSA signing and PKCE, including `alg: none`, HMAC key confusion, wrong audience / issuer, replay, CSRF, open redirect | Not verified against a commercial IdP. Stateless sessions (no revocation before expiry). No SCIM or per-campaign permissions |
| Gate cannot see unsourced prose with no number, quote or superlative | Sentence accounting: every assertive sentence must be covered by a supported claim or dispositioned by a reviewer | 17 tests; "Customers love it." now blocks a PR release and is marked in the console | Matching is lexical. A reviewer can still wrongly waive a factual sentence; that is attributed and audited, not prevented. English-oriented heuristics |

## Rating

| Dimension | v1.0 | v1.1 | v1.2 |
|---|---|---|---|
| Gate effectiveness | 2 | 7 | 8 |
| Security and identity | 2.5 | 7.5 | 8.5 |
| Audit integrity | 3 | 8 | 8 |
| Distribution (feeds + providers) | 4.5 | 7.5 | 7.5 until live-verified, 8.5 after |
| Operability (console, runbook) | 4 | 6 | 8 |
| Test and validation evidence | 2 | 8 | 8.5 |
| Deployability | 5 | 7 | 7 |
| **Overall** | **3.5** | **7** | **8 / 10** |

What keeps v1.2 from 9: nothing here has touched a live provider, a commercial IdP or a Docker host; provider
token refresh is manual; no rate limiting or Alembic; sentence matching is lexical; the three Word deliverables
still describe v1.0.

---

# Review of Parinita GrowthOS v1.0 Production Packet

Reviewed 2 October 2026. Every finding below was reproduced by running the shipped v1.0 code, not inferred from
reading it. The fix column points at the v1.1 test that now fails if the defect returns.

## Rating

| Dimension | v1.0 | v1.1 | Basis |
|---|---|---|---|
| Architecture and scope honesty | 7 | 7.5 | Envelope + adapter model is right; boundary language is honest |
| Gate effectiveness (the core claim) | 2 | 7 | v1.0 gate was bypassable five ways; v1.1 is still lexical and claim-declared |
| Security | 2.5 | 7.5 | Secret exfiltration, SSRF, default credentials, shared-key "approvals" |
| Audit integrity | 3 | 8 | Chain forked under load; no verifier; not immutable |
| Feed Fabric correctness | 4.5 | 7.5 | Leaked high-risk items; invalid Atom/Podcast output; broken dedupe |
| Test and validation evidence | 2 | 8 | 5 unit tests, no API/DB tests, never run on PostgreSQL -> 100 tests on SQLite and PostgreSQL 16 |
| Deployability | 5 | 7 | Compose still not executed in the build environment (no Docker available) |
| Documentation fidelity | 5 | 8 | Runbook described operations the API could not perform |
| **Overall as a "production packet"** | **3.5 / 10** | **7 / 10** | |

As a prototype scaffold v1.0 was a 6.5: small, coherent, readable, and careful not to overclaim on third-party
integrations. The problem was the label. The release documents assert controls ("deterministic publish blocking",
"immutable audit events", "cannot bypass Gate", "model output is still downstream of Claim and Gate controls") that
the code did not enforce.

What holds v1.1 at 7: no provider adapters for social / podcast hosts / PR wires, no operator UI, agents are
templates rather than producers of media, API keys rather than SSO, no Alembic, no rate limiting, the gate cannot
see unsourced prose that carries no number, quote or superlative, and Docker Compose has not been run end to end.

## Critical findings

| ID | Finding in v1.0 | Evidence (reproduced) | v1.1 fix | Regression test |
|---|---|---|---|---|
| C1 | **Gate passes content with no declared claims.** Claims are optional and self-declared; with none attached, a `pr` item saying "Revenue grew 40% last year. We operate 101 POPs in 42 states. Our CEO said 'we are #1'" passed with zero warnings. The numeric scanner required a word boundary after `%`, so it never matched a normal percentage, and it ignored plain counts. | `passed: True, warnings: [], numeric_tokens: 0` | Coverage scan of title/summary/body: numbers, quotations and superlatives must appear in a supported claim. Blocks for high-risk + `pr` + `social`. | `test_pr_with_undeclared_numbers_is_blocked`, `test_assertions_are_detected` |
| C2 | **One unrelated claim disables the numeric check.** The scan only ran when `claims` was empty. An investor item with "$50M revenue, 80% margin" plus one `opinion` claim was approved. | `state: approved, blockers: []` | Coverage is computed per token against supported claims only; `opinion`/`internal` never count. | `test_unrelated_opinion_claim_does_not_disable_scan` |
| C3 | **Approval is not bound to content or to a person.** After a CFO approval, the Acquire agent repointed the CTA to `https://evil.example/phish`; the approval still held and the gate passed. `approver` was a free-text field sent with one shared API key, so anyone holding the key could approve as anyone. | `approval still valid: True, gate passed: True` | Approval stores the governed `content_hash`; any governed change invalidates it and returns the item to `draft`. Approver identity = API key principal with an explicit `approver` role; four-eyes in production. | `test_cta_rewrite_after_approval_invalidates_it`, `test_edit_after_approval_invalidates_it`, `test_approver_identity_comes_from_the_key_not_the_body`, `test_four_eyes_for_high_risk_content` |
| C4 | **Every approved item is published in every public feed.** `/feeds/{slug}` is unauthenticated and selected all `approved`/`published` items regardless of endpoint, campaign or classification. An approved investor note appeared in the public blog RSS. | `'CONFIDENTIAL investor note' in public /feeds/blog: True` | Feeds select by endpoint routing; high-risk classes and ingested third-party items are excluded unless the endpoint opts in; the gate is re-run at render time; inbound/disabled endpoints return 404. | `test_high_risk_content_never_leaks_into_default_feeds`, `test_ingested_items_are_not_resyndicated_by_default` |
| C5 | **Any API-key holder can exfiltrate process secrets and reach internal services.** Endpoint `config.bearer_token_env` read any environment variable and sent it as a Bearer token to any URL, including loopback and cloud-metadata addresses, following redirects. | Remote received `Authorization: Bearer super-secret-smtp-pw` | Only `GROWTHOS_SECRET_*` names are readable; egress guard blocks non-public addresses, enforces an allowlist, re-validates redirects; credential headers rejected in config. | `test_endpoint_config_cannot_name_arbitrary_env_vars_or_auth_headers`, `test_egress_guard_blocks_internal_and_odd_destinations`, `test_redirect_hops_are_revalidated` |
| C6 | **The audit "hash chain" is not a chain under concurrency, and is not immutable.** Writers read the previous hash without a lock. On PostgreSQL with 24 concurrent clients, 287 of the last 500 events shared a `prev_hash` with another event. Timestamps were outside the hash, events were committed separately from the change they described, refusals and failures were not recorded, and there was no verifier (the acceptance checklist asks for "no missing links" with no way to check). | `forks: 287`, `verify: 404` | Advisory lock + unique `prev_hash`; timestamp inside the hash; event flushed in the same transaction; append-only triggers; `GET /v1/audit/verify`; refusals/failures audited. Same load on v1.1: 1,080 events, 0 forks, `ok: true`. | `test_chain_cannot_fork`, `test_database_rejects_audit_mutation`, `test_verify_detects_tampering_when_triggers_are_removed`, `test_publish_is_gated_and_the_refusal_is_audited` |

## High findings

| ID | Finding in v1.0 | Evidence | v1.1 fix | Regression test |
|---|---|---|---|---|
| H1 | **Model output is never gated.** The gate reads `body`; model-written pitches and social posts live in `metadata.agent_history`, which was pushed to destinations as-is. A list-shaped model response crashed Amplify with a 500. | `pushed payload leaks agent_history: True`; `amplify -> 500` | Shape validation + deterministic drift check (no new numbers, quotes, superlatives, URLs); push sends a public projection; derivatives are opt-in and version-pinned. | `test_model_output_with_invented_facts_is_rejected`, `test_malformed_model_output_falls_back_instead_of_500`, `test_publish_sends_signed_minimal_payload_once` |
| H2 | **Ships and boots with known credentials.** `deploy.sh` copied `API_KEY=change-me-now`, published the API on all interfaces and started. PostgreSQL password hardcoded as `growthos`. `COPY . .` with no `.dockerignore` baked `.env` into the image. Key comparison was not constant-time. | `Settings(environment=production, api_key=default) accepted: True` | Launchers generate secrets; production refuses weak keys; loopback bind; no hardcoded DB password; lean image; `hmac.compare_digest`. | `test_production_refuses_unsafe_config` |
| H3 | **Publishing is not idempotent, not retried, not recorded.** Two publish calls delivered twice; 8 concurrent calls delivered 8 times. No delivery record, so "published" could not be traced to a destination. | `deliveries from 2 repeat calls: 2` | `deliveries` table with a unique (content version, destination) slot claimed before send; retries with a stable `Idempotency-Key`; HMAC signature. Same race on v1.1: 1 delivery. | `test_publish_sends_signed_minimal_payload_once`, `test_transient_failures_are_retried_with_one_idempotency_key`, `test_failed_delivery_is_visible_and_retryable` |
| H4 | **Weak evidence checks.** "The project will reach $1B revenue" counted as a labeled forecast because the noun "project" matched. A source of `{"uri": "x"}` satisfied the source requirement. | both `True` | Projection vocabulary with word boundaries; source URIs validated by scheme at the API and again in the gate. | `test_forecast_needs_real_projection_language`, `test_junk_source_uri_is_not_evidence` |
| H5 | **One malformed feed item halts all ingestion; untrusted feeds parsed unsafely.** On PostgreSQL, a feed item with a title over 500 characters raised a database error; the worker's error handler then touched the poisoned session, the exception escaped `run_once`, and the worker process died (restart loop on the same item). The same error was returned to the API caller with the full SQL statement. XML entities were expanded by the standard-library parser, a 30 MB item was accepted with no size limit, and redirects were followed. | `PendingRollbackError` escaping `worker.py:18`; `30 MB feed item accepted: 200`; SQL text in the 502 body | Fields truncated to column limits; `defusedxml`; size and entry caps; per-endpoint sessions with rollback; failures recorded on the endpoint and in the audit log; error bodies reduced to one line. | `test_overlong_feed_fields_are_truncated_not_fatal`, `test_entity_expansion_feed_is_rejected_and_recorded`, `test_oversized_feed_is_rejected`, `test_worker_survives_a_failing_endpoint` |
| H6 | **The runbook describes operations the API cannot perform.** "Disable a destination by setting enabled=false", "correct the content object", "review the blocked content queue", "review audit chain continuity": no endpoint existed for any of them. A blocked item was a dead end because claims could only be attached at creation, and ingested items could never receive claims. | no `PATCH`/`PUT` routes | `PATCH /v1/content/{id}`, `PATCH /v1/feeds/{id}`, `?state=` filter, `/v1/audit/verify`, `/revoke`, `/deliveries`. | `test_claims_can_be_attached_to_unblock`, `test_inbound_and_disabled_endpoints_are_not_public`, `test_list_filters_and_bounds` |
| H7 | **Never run on its production database.** The release manifest says Docker was unavailable; the 5 tests used no database. The first PostgreSQL run of the new suite found a crash: any content containing a NUL byte returns 500. API and worker also raced on `create_all` at first boot. | `psycopg.DataError: ... cannot contain NUL` | NUL stripped at the schema boundary; API owns schema creation under an advisory lock; worker waits. Suite runs on PostgreSQL via `TEST_DATABASE_URL`. | `test_rss_and_atom_are_well_formed_and_complete` |

## Medium findings

| ID | Finding in v1.0 | v1.1 |
|---|---|---|
| M1 | Feed items with no `guid`/`link` got a random id and were re-ingested on every poll. | Content-fingerprint identity. `test_ingest_dedupes_including_items_without_ids` |
| M2 | Podcast RSS had no iTunes channel tags, included non-audio items, and returned 500 on a non-numeric `audio_bytes`. Atom lacked the required `author`. RSS lacked `atom:link rel=self`. JSON Feed linked to a `/content/{id}` route that does not exist. Control characters produced unparseable XML. | Built with an XML serializer, directory tags from config, episodes only, safe coercion. `test_podcast_feed_carries_only_episodes_with_directory_tags`, `test_rss_and_atom_are_well_formed_and_complete`, `test_jsonfeed_has_no_dead_links` |
| M3 | Re-running the gate on a published item regressed it to `approved`. `content_hash` covered state, timestamps and agent output, so it changed on every agent run and identified nothing. | Explicit state rules; hash over governed fields only. `test_gate_rerun_keeps_published_state`, `test_content_hash_is_stable_across_agent_runs` |
| M4 | Rally treated only investor/regulated/financial as high-risk; Gate also treated legal/health. | One `HIGH_RISK` set. `test_every_high_risk_class_needs_approval` |
| M5 | Duplicate content id returned 500; negative `limit` reached the database; `agent_history` grew without bound; `campaign_id` was never validated; `Campaign.default_cta_url` was never used. | 409 / 422 / bounded history / validated / used by Acquire. `test_duplicate_ids_are_409_not_500`, `test_agent_history_is_bounded_and_versioned` |
| M6 | README pointed to `app/adapters/`, which did not exist; "adapter contract supplied" was a markdown page. | Contract in code with two reference adapters. |
| M7 | Atom ingest took the first `<link>` (often `rel=self`), RSS ingest ignored `content:encoded`. | Prefers `rel=alternate`; reads `content:encoded`. `test_atom_ingest_prefers_alternate_link` |
| M8 | `pytest` in the runtime image; tests and Word documents copied into the image; no container healthcheck; `demo.sh` required a `python` binary. | Split requirements, `.dockerignore`, `HEALTHCHECK`, `python3` fallback. |

## Statements in the v1.0 documents that the v1.0 code contradicts

See `deliverables/ERRATA.md`.

## Validation performed for v1.1

| Check | Result |
|---|---|
| Test suite, SQLite | 100 passed |
| Test suite, PostgreSQL 16.15 | 100 passed |
| Live uvicorn on PostgreSQL, 120 create+pipeline requests across 24 threads | 120 x 200, 1,080 audit events, 0 forks, chain verifies |
| Live publish race, 8 concurrent calls | 1 delivery, 7 x 409 |
| v1.0 database upgraded in place by v1.1 | Columns added, legacy audit rows verify, legacy approvals correctly treated as unbound |
| `examples/demo.sh` against a production-mode server on PostgreSQL | Completed; docs disabled; bootstrap key refused for approval |
| `deploy.sh` with stubbed Docker | Secrets generated, `.env` mode 600, refuses default key |
| `docker compose up` | **Not run. Docker is not available in this environment.** Compose file parsed only. |
| `single-click.ps1` | **Not run. PowerShell is not available in this environment.** |
| External feed/podcast validators | **Not run.** Output is parsed as well-formed XML in tests; validator conformance is an acceptance item. |

## Recommended next steps, in order

1. Run `docs/THREE_DAY_ACCEPTANCE.md` on a Docker host, including `single-click.ps1` on Windows.
2. Replace API keys with SSO (Witness is named in the white paper) and add per-campaign authorization.
3. Anchor the audit `head_hash` externally on a schedule.
4. Build the first two provider adapters the launch actually needs, with the test set in the adapter guide.
5. Move from declared claims to extracted claims: sentence-level claim extraction with a required human confirm, then source-quality scoring.
6. Adopt Alembic; add rate limiting at ingress; add an operator UI for the blocked queue and approvals.
