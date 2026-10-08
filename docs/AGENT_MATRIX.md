# Parinita GrowthOS v1.8 Agent Naming Register

The parent remains **Parinita GrowthOS**. These names are GrowthOS identities, with stable underlying capability IDs. No rename grants additional authority.

## Sources and scope

Checked the current contents of `parinita_product_set.json` (September 27, 2026), the naming roster in `Parinita_Master_Context_Brief_v3_Technical.md` (June 2026), and later naming decisions retrieved from prior discussions. Later explicit user decisions take precedence over older proposed assignments. This is a check against the available register, not proof that an exhaustive enterprise register exists.

The older brief has superseded technical/business facts. Only its naming roster is used here. Current assignments include Marshal/Witness; Driver/Praxis; Echo/Atma; Sutra/Nexus; Inspector/Fulcrum; Painter/Motif; Sage/Pulse; Vigil and Cipher/Quotient Canon; Pathfinder/Orchestra; Runner/Relay; Weaver/Tapestry.

Forge and Lens are occupied existing names. Conductor is excluded on the user's instruction despite inconsistent earlier proposals. Chorus remains a separate product. Editor, Steward, Switchboard, Registrar and Auditor were previously occupied/rejected and are excluded. Scout and Vector appeared in unaccepted proposals outside GrowthOS; Scout is retained as a **GrowthOS-qualified** identity from the earlier GrowthOS proposal. Vector is avoided because it appeared as another product candidate. Reach, Compass and Sentinel/Senitene are also excluded as existing products per the user's current correction. Broadcaster (distribution), Cartographer (AEO) and Scrutineer (Gate) replace them. No existing ownership for these replacements was found in retrieved discussions; they are new scoped GrowthOS assignments, not claimed globally unique names. No external product is renamed.

## Core identities

| Stable API ID | GrowthOS identity | Role | May transmit |
|---|---|---|---|
| `signal` | **Scout** | Signal detection and story briefs | No |
| `pr` | **Envoy** | PR packages and media targeting | No |
| `media` | **Curator** | Master media package | No |
| `podcast` | **Orator** | Podcast plans and show notes | No |
| `social` | **Ripple** | Social copy and approved scheduling | No |
| `amplify` | **Broadcaster** | Distribution and localization plans | No |
| `engagement` | **Liaison** | Inbox triage and response drafts | No |
| `acquire` | **Magnet** | CTA and UTM routing | No |
| `feed` | **Courier** | Governed ingestion and publishing | Yes, subject to publisher authority and all release controls |
| `claim` | **Scribe** | Claim inventory and evidence coverage | No |
| `aeo` | **Cartographer** | Answer visibility and citation recommendations | No |
| `performance` | **Gauge** | Observed outcome aggregation | No |
| `gate` | **Scrutineer** | Deterministic policy checks | No |
| `rally` | **Convenor** | High-risk approval hold | No |
| `channels` | **Cadence** | Channel specialist orchestration | No |

## Qualified channel specialists

These are scoped instances of core identities, not 13 unrelated new brands.

| Stable API ID | Display identity |
|---|---|
| `reddit` | Parinita GrowthOS Ripple / Forums |
| `facebook` | Parinita GrowthOS Ripple / Facebook |
| `instagram` | Parinita GrowthOS Ripple / Instagram |
| `threads` | Parinita GrowthOS Ripple / Threads |
| `pinterest` | Parinita GrowthOS Ripple / Pinterest |
| `tiktok` | Parinita GrowthOS Ripple / TikTok |
| `tumblr` | Parinita GrowthOS Curator / Tumblr |
| `etsy` | Parinita GrowthOS Magnet / Etsy |
| `shopify` | Parinita GrowthOS Magnet / Shopify |
| `local` | Parinita GrowthOS Envoy / Local |
| `blog` | Parinita GrowthOS Curator / Blog |
| `newsletter` | Parinita GrowthOS Curator / Newsletter |
| `community` | Parinita GrowthOS Liaison / Community |

## Compatibility

API/MCP capability IDs, pipeline order, protocol names and permissions remain unchanged. `GET /v1/agents` includes `name`, `identity`, `namespace` and `legacy_name`. New audit events and agent histories include the scoped identity. Existing audit history is never rewritten. Channel prompts use the same registered identity. Core identities are checked against the known reserved set at import; every capability must have a naming entry.

This does not create new autonomous agent processes. The existing capability runners remain model-assisted when configured and deterministic otherwise. Agents cannot approve, waive or sign; Courier publishes through the existing governed delivery path under the calling principal's authority. Cadence orchestrates channel preparation only.

## Capability details

# Historical capability descriptions (stable IDs)

| Agent | Mode | Does real system work | Can publish |
|---|---|---|---|
| Signal | acts | Monitors feeds; Opportunity Queue fuses media/AEO/inbox/performance observations | No |
| PR | transforms + targets | Builds grounded PR package and ranks imported/licensed media contacts | No |
| Media | transforms | Builds master asset package | No |
| Podcast | transforms | Builds episode plan/show notes | No |
| Social | acts | Creates channel copy, schedules approved content, consumes performance learning | No |
| Amplify | plans | Distribution/localization/channel plan | No |
| Engagement | acts | Reads normalized inbox, triages, drafts response | No |
| Acquire | acts on governed content | CTA/UTM changes force a new governed version | No |
| Feed | acts | Ingests, normalizes, renders, routes and transmits after Gate/policy/Chrysalis checks | **Yes** |
| Claim | governs | Candidate extraction, source/sentence coverage | No |
| AEO | observes | Answer-engine observations, citation visibility, evidence export | No |
| Performance | learns | Aggregates observed outcomes and returns transparent heuristics | No |
| Gate | governs | Deterministic release decision | No |
| Rally | governs | High-risk checkpoint/hold | No |

### Channel agents (v1.7)

One agent per destination family. Each writes channel-native copy (model-generated when `TEXT_MODEL_*` is configured,
deterministic otherwise, always drift-checked against the governed master with `gate.ungrounded_in`), reports
destination readiness (which configured endpoints would accept this release now, and why the others would not), and
records both under its own name in the release's agent history. Adapters pick that copy up through
`public_projection.channel_copy`, only when it was generated from the exact current content version.

| Agent | Protocols | Family rule |
|---|---|---|
| Reddit | `reddit`, `lemmy` | Community-first, plain, affiliation disclosed, standalone title |
| Facebook | `facebook` | Conversational, one link |
| Instagram | `instagram` | First line carries, "link in bio", hashtags only from source words; **needs an image** |
| Threads | `threads` | One idea, under 500 chars |
| Pinterest | `pinterest` | Searchable description; **needs an image** |
| TikTok | `tiktok` | Hook-first caption for a photo carousel; **needs images** |
| Tumblr | `tumblr` | Heading + paragraphs |
| Etsy | `etsy` | Shop voice; no price/stock claims unless sourced |
| Shopify | `shopify` | Store blog article |
| Local | `google_business` | Actionable local post + CTA |
| Blog | `devto`, `ghost`, `wordpress` | Long-form, body intact |
| Newsletter | `buttondown`, `mailchimp`, `smtp` | Subject = title, preview, body, one CTA |
| Community | `slack`, `teams`, `discord`, `telegram`, `whatsapp`, `google_chat`, `mattermost`, `matrix`, `zulip` | Plain internal/community notice |
| **Channels** (orchestrator) | all of the above | Runs every family with at least one enabled destination (`options.all` runs all) and rolls readiness up |

Run with `POST /v1/content/{id}/agents/run` (`{"agent": "reddit"}`, `{"agent": "channels"}`, options `protocols`,
`max_chars`, `all`). None of them can approve, waive, schedule or send: a ready destination is still published only by
the Feed Agent through `POST /v1/content/{id}/publish`, behind Gate, destination policy, idempotency and Chrysalis.

The product does not equate an agent name with autonomy. Human approval remains separate from agent execution.
