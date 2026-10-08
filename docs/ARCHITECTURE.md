# Parinita GrowthOS v1.6 Architecture

## Closed-loop flow

`Listen -> Normalize -> Opportunity -> Governed Content -> Claims/Sentence Proof -> Human Approval -> Chrysalis Attestation -> Distribute -> Observe -> Claim Graph -> Learn -> Next Opportunity`

GrowthOS avoids N x M point-to-point integrations. Inbound feeds, media coverage, engagement, AEO and performance normalize into stable data planes. Releases leave only through Feed Agent after Gate/policy checks. Chrysalis anchors the assurance boundary.

## Product lanes

| Lane | v1.6 behavior |
|---|---|
| Signal | Monitors inbound corpus and creates ranked Opportunity Queue items from media, AEO, inbox and performance observations. |
| PR intelligence | Normalized licensed-provider contacts/coverage, transparent target ranking, coverage-to-release observations. |
| PR production | Grounded release/pitch/newsroom packages plus ranked imported media targets. |
| Social | Grounded channel derivatives, future scheduling of approved versions, observed performance learning. |
| Media/podcast/voice | Production manifests, podcast feeds/hosts and governed Vaak audio artifacts. |
| Engagement | Normalized inbox triage and response drafts; never auto-replies. |
| AEO/GEO | Prompt library, live/configured probes, visibility/citations, governed public claim manifests and JSON-LD. |
| Claim Graph | Source -> claim -> exact release hash -> delivery -> earned-media/AEO/performance observations. |
| Governance | Claim, Rally, Gate, human approval, append-only local audit. |
| Assurance | Chrysalis external anchoring of audit heads and release attestations; configurable high-risk fail-closed policy. |
| Distribution | Feed Fabric + provider adapters + MCP. |

## Trust boundary

GrowthOS local audit is operational evidence. Chrysalis is the external trust anchor. GrowthOS stores the Chrysalis receipt and payload digest. A high-risk publish can be refused before any external delivery if Chrysalis cannot attest the exact version.

## Naming boundary

GrowthOS **Claim Graph** is communications provenance. **Chrysalis Lineage** remains the causal forensic analyzer. No duplicate Lineage component is introduced in GrowthOS.

## Remaining deployment dependencies

Licensed media-data credentials/contracts, native provider inbox/media-upload/token-refresh support where needed, live answer-engine credentials, production Witness realm, live Chrysalis assurance ingress and target Docker/PostgreSQL acceptance.
