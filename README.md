# Parinita GrowthOS v1.9.2

## Connector hardening update

All 37 outbound adapters and four feed formats now have console setup, editable settings and configuration readiness checks. See [connector coverage and production acceptance](docs/CONNECTOR_COVERAGE.md). This release improves validation, credential handling, draft delivery reporting and runtime checks; live account certification and target-cluster acceptance remain required.

## Running the application

For the real application on Windows with Python 3.12 installed, run:

```powershell
.\start-local.ps1
# Or point to a specific Python 3.12 interpreter:
.\start-local.ps1 -Python 'C:\path\to\python.exe'
```

Then visit `http://127.0.0.1:8080/console`. The local launcher creates an isolated development database in `data/local/` and a random admin access key in `data/local/admin-key.txt`. Use that key with the console's access-key sign-in. These local files are excluded from Git. The launcher binds only to this computer and ignores a production `.env` file. Stop it with Ctrl+C. Production deployment continues to use the Docker instructions below.

The Windows compatibility update adds platform conditions to the Linux-only uvloop dependency and hash-pinned Windows colorama/tzdata dependencies. The supplied release evidence remains historical; new local verification is recorded separately in `evidence/local-windows-*.xml`.

Parinita GrowthOS is a self-hosted evidence-governed operating system for PR, social, media, podcasts/voice, feeds, messaging, AEO/GEO visibility, engagement and growth telemetry. Its core model is **one governed release object, one proof/approval path, many channels, one measurable feedback loop**.

v1.6 closes the largest product gaps identified in the v1.5 market review without pretending GrowthOS owns every underlying data source. It adds a normalized PR/media-intelligence layer, ranked Opportunity Queue, Claim Graph, stronger agent feedback loops, and native Chrysalis anchoring for audit heads and release attestations.

## What changed in v1.8

- Named identities for all 28 capabilities, with 15 core identities and 13 qualified channel specialists. `docs/AGENT_NAMING.md` records exclusions, sources and stable API IDs.
- Production Chrysalis verification requires digest echo and a signing verification key. Cached attestations recheck Gate, exact approval/dispositions binding, and the current receipt key.
- Journalist email fields are visible only to editor/admin principals.
- Shared provider requests stream responses under a hard cap; oversized ambiguous sends never automatically retry.
- Hash-locked runtime/development dependencies, CycloneDX inventory, CI definitions, regression tests and updated release documentation.

## What changed in v1.7

- **37 destinations.** Added Reddit, Facebook Pages, Instagram, Threads, Pinterest, TikTok (photo), Tumblr, Lemmy, Etsy,
  Shopify, Google Business Profile, Dev.to, Ghost, Buttondown, Mailchimp, Google Chat, Mattermost, Matrix and Zulip to
  the existing LinkedIn, X, Mastodon, Bluesky, Slack, Teams, Discord, Telegram, WhatsApp, WordPress, podcast hosts, PR
  wire, SMTP, webhooks, MCP and Vaak. Every one sits behind the same Gate, destination policy, idempotent delivery
  record, audit chain and Chrysalis policy. See `docs/PROVIDERS.md`, including what is deliberately not supported.
- **Channel agents.** One agent per destination family (Reddit, Facebook, Instagram, Threads, Pinterest, TikTok, Tumblr,
  Etsy, Shopify, Local, Blog, Newsletter, Community) plus a `channels` orchestrator. They write channel-native copy that
  is drift-checked against the governed master, report which configured destinations would accept the release and
  why the others would not, and hand the copy to the Feed Agent's adapters. They cannot approve, waive, schedule or
  send. See `docs/AGENT_MATRIX.md`.

## What changed in v1.6

| Gap | v1.6 closure |
|---|---|
| PR was packaging without intelligence | `media_contacts` + `media_coverage`, licensed-provider import contracts, transparent journalist/outlet targeting, earned-media observations linked to governed releases. |
| Signal saw feeds but did not decide what mattered next | Opportunity Queue fuses earned media, AEO visibility gaps, high-priority inbox events and observed performance into ranked next actions. |
| AEO/PR/performance were separate views | Claim Graph connects source -> approved claim -> exact release hash -> delivery -> earned coverage -> exact AEO citation matches -> outcome telemetry. |
| Audit head anchoring was a generic external utility | Chrysalis is the canonical external assurance anchor. GrowthOS stores the returned Chrysalis receipt and can fail closed before high-risk publication. |
| Agents did not sufficiently use downstream results | PR Agent ranks imported media targets; Social Agent includes observed performance learning; Signal creates opportunity work; Engagement reads normalized inbox data; AEO observes answer-engine responses; Performance learns from recorded outcomes. |

## Core authority rule

**Agents can work; agents cannot sign.** Only Feed Agent can transmit content. Approval remains attributable to a human principal. Every send re-checks the exact governed content hash, Gate, destination policy and, when configured, Chrysalis attestation policy.

## Chrysalis integration

GrowthOS maintains its append-only local hash chain for fast operational verification. Chrysalis is the external assurance anchor.

- `POST /v1/chrysalis/anchor/audit` verifies the current GrowthOS chain and anchors its head to Chrysalis.
- `POST /v1/content/{id}/chrysalis/attest` anchors the exact governed release version after Gate clearance.
- The worker can anchor audit heads periodically (`CHRYSALIS_ANCHOR_INTERVAL_SECONDS`).
- High-risk publishing can fail closed if the exact release version has no valid Chrysalis receipt.
- GrowthOS stores the Chrysalis receipt/reference and payload digest.
- GrowthOS does **not** rename its Claim Graph to Lineage; **Lineage remains the Chrysalis causal-forensics component**.

Production configuration:

```env
CHRYSALIS_ENABLED=true
CHRYSALIS_ANCHOR_URL=https://<your-chrysalis-assurance-ingress>
CHRYSALIS_BEARER_TOKEN_ENV=GROWTHOS_SECRET_CHRYSALIS_TOKEN
GROWTHOS_SECRET_CHRYSALIS_TOKEN=<secret>
CHRYSALIS_FAIL_CLOSED_HIGH_RISK=true
CHRYSALIS_FAIL_CLOSED_ALL=false
CHRYSALIS_ANCHOR_INTERVAL_SECONDS=3600
CHRYSALIS_REQUIRE_RECEIPT_DIGEST=true
CHRYSALIS_RECEIPT_VERIFY_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
```

Receipts are verified (reference, digest echo, signature) before GrowthOS records them as anchored; see
`docs/CHRYSALIS.md` "Receipt verification".

The exact Chrysalis ingress route is deployment-configured; v1.6 does not invent or hard-code a route for another Parinita product.

## PR/media intelligence

GrowthOS intentionally separates **communications intelligence** from **proprietary contact data ownership**.

- `POST /v1/media/contacts` normalizes licensed/internal journalist, analyst or creator records.
- `POST /v1/media/coverage` normalizes earned coverage and can link it to a governed release.
- `GET /v1/content/{id}/media-targets` ranks imported contacts by transparent topic/beat overlap, imported influence signal and recent activity.
- PR Agent includes those targets in its content-scoped result.
- Coverage linked to a release can create downstream claim observations when lexical evidence passes the configured threshold.

No contact is invented. Provider/source identity stays attached to each record.

## Opportunity Queue

`POST /v1/opportunities/refresh` combines:

- earned-media coverage,
- high-priority media/community inbound,
- recorded AEO visibility gaps,
- performance-learning actions.

`GET /v1/opportunities` returns a ranked queue. Opportunity scores are transparent heuristics, not predictions or approvals. An accepted opportunity still has to become governed content, pass the sentence/claim proof path, receive human authorization where required and publish through Feed Agent.

## Claim Graph

`GET /v1/content/{id}/claim-graph` returns a machine-readable graph of:

```text
source -> approved claim -> governed release/version
                           -> delivery
                           -> earned-media observation
source --------------------> exact AEO citation observation
governed release ----------> recorded performance
```

The graph records provenance and observations. It does not independently prove source truth or claim causal influence over a citation or conversion.

## AEO/GEO

GrowthOS tracks answer-engine prompts, observed responses, brand mentions and citations; exposes governed claim manifests and JSON-LD; and supports a configurable licensed REST probe. v1.6 adds the Claim Graph so exact citation URLs can be tied back to the source/claim/release graph without claiming semantic attribution when only an exact citation match exists.

## Performance and social learning

`POST /v1/performance/events` remains the normalized outcome ingress for provider analytics, conversion systems and webhooks. Performance Agent computes explicit observed rates and non-causal recommendations. Social Agent now includes those performance learnings when preparing channel derivatives/scheduling work.

## Quick start

```bash
./deploy.sh
# Windows PowerShell: .\single-click.ps1
```

Open `http://localhost:8080/console` locally or your HTTPS front door in production. Growth Command's Intelligence view now includes performance, AEO, engagement, Opportunity Queue, earned media, scheduled distribution and Chrysalis anchor status.

## Validation

See `REVIEW.md` and `evidence/pytest.xml` for this release's measured results. Previous-version counts are historical, not v1.8 validation. Dependencies are fully resolved with hashes in `requirements.lock` and `requirements-dev.lock`; the Dockerfile installs the runtime lock with `--require-hashes`.

```bash
python -m pip install --require-hashes -r requirements-dev.lock
python -m playwright install chromium
python -m pytest -q -rs
# PostgreSQL acceptance:
TEST_DATABASE_URL=postgresql+psycopg://... python -m pytest -q -rs
```

The checked-in CI workflow defines SQLite and PostgreSQL 16 checks plus container build. Its presence is not evidence that a hosted CI run or container build has passed. Optional SDK interop requires a separate MCP SDK interpreter (`MCP_SDK_PYTHON`).

## Honest boundaries

- GrowthOS now has a PR intelligence **data plane and targeting engine**, not a proprietary Cision/Muck Rack-scale journalist database. Live licensed-provider adapters/credentials remain deployment work.
- Native social-network inbox readers and every provider's media-upload/token-refresh lifecycle are not universalized.
- AEO monitoring is only as live as the configured provider/probe credentials; answer engines do not share one universal API/citation format.
- Claim Graph records observed relationships; it does not prove causal influence.
- Source presence, human approval, Gate clearance and Chrysalis attestation prove process/provenance controls, not that an external source itself is true.
- Docker/PostgreSQL/Witness/live-provider/Chrysalis endpoint acceptance must still be run in the actual target environment before GA.
# GrowthOS 1.9 deployment update

The current source includes Denizen-backed drafting, brand voice, four-format campaign generation, editorial review, and a Kubernetes Helm chart. See [Kubernetes deployment](docs/KUBERNETES.md) for installation and [1.9 verification](evidence/GROWTHOS_1.9_VERIFICATION.md) for tested behavior and remaining limitations.


## Company workspaces (1.9.2)

Company setup, company membership checks for OIDC sign-in, an encrypted connector credential vault, and source selection in drafting are now available. Each company uses a dedicated deployment and database; shared-database multi-tenancy and automatic cloud provisioning are not implemented. See [company workspace setup](docs/COMPANY_WORKSPACES.txt). Live account connections, identity configuration, cluster deployment and AI Studio generation require the actual services and company authorization.
