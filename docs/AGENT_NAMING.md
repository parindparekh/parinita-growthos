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
