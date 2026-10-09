# Connector coverage and production acceptance

This register reconciles the GrowthOS production packet's v1.8 white paper with the repository provider contract and executable adapter registry. The scope is **37 outbound adapter protocols plus four feed formats**. It does not expand a generic webhook or MCP transport into an unimplemented native provider.

Every row below is available in **Destinations** in the console, with editable account settings and operator-provisioned secret references. New console destinations start disabled. Administrators can check configuration without sending anything. A green configuration result proves required settings and referenced secret presence, not token validity, permission scopes or live API compatibility.

## Destination inventory

| Connector | Protocol | Group | Live acceptance requirement |
|---|---|---|---|
| RSS newsroom | `rss` | Feeds | Verify feed rendering and ingestion against the intended source. |
| Atom feed | `atom` | Feeds | Verify feed rendering and ingestion against the intended source. |
| JSON feed | `jsonfeed` | Feeds | Verify feed rendering and ingestion against the intended source. |
| Podcast RSS | `podcast_rss` | Podcast and voice | Hosted audio is required for each episode. |
| Webhook | `webhook` | Integration | Receiver must honour the delivery idempotency key. |
| REST JSON | `rest_json` | Integration | Uses the governed release JSON contract. |
| Email (SMTP) | `smtp` | Messaging | Configure the SMTP relay on the server. Recipient consent remains an operator responsibility. |
| LinkedIn | `linkedin` | Social | Requires an authorised member or organisation and posting scope. Renew tokens outside GrowthOS. |
| X | `x` | Social | Supply either an OAuth 2 user token or all four OAuth 1 fields. |
| Mastodon | `mastodon` | Social | Use your instance URL. |
| Bluesky | `bluesky` | Social | Optional custom PDS URL; otherwise bsky.social. |
| Reddit | `reddit` | Social | Supply a refresh token, or username and password for an authorised script app. |
| Facebook Pages | `facebook` | Social | Page posting only; requires pages_manage_posts. |
| Instagram | `instagram` | Social | Professional account and a public HTTPS image on the release are required. |
| Threads | `threads` | Social | Text container followed by publish; account permission required. |
| Pinterest | `pinterest` | Social | Requires pins:write and a public image on the release. |
| TikTok photos | `tiktok` | Social | Photo uploads only. Defaults to creator review; source image domain must be verified. |
| Tumblr | `tumblr` | Social | Uses Neue Post Format. |
| Lemmy | `lemmy` | Social | Use your instance URL. |
| Slack | `slack` | Messaging | Invite the bot to the channel; chat:write scope required. |
| Microsoft Teams | `teams` | Messaging | Store the complete Workflows webhook URL in the named server secret. |
| Discord | `discord` | Messaging | Store the complete webhook URL in the named server secret. Mentions are disabled. |
| Telegram | `telegram` | Messaging | The bot must have access to the chat. |
| WhatsApp Business | `whatsapp` | Messaging | Approved templates and opted-in recipients only; not WhatsApp Channels. |
| Google Chat | `google_chat` | Messaging | Store the complete space webhook URL as a server secret. |
| Mattermost | `mattermost` | Messaging | Incoming webhook URL belongs in a server secret. |
| Matrix | `matrix` | Messaging | Homeserver URL and !room:server room ID required. |
| Zulip | `zulip` | Messaging | Use the realm URL and a bot account. |
| WordPress | `wordpress` | Publishing | Application password; defaults to a draft during setup. |
| Dev.to | `devto` | Publishing | Creates a draft by default during setup. |
| Ghost | `ghost` | Publishing | Use the site URL and a server secret containing the Admin API id:secret. |
| Buttondown | `buttondown` | Publishing | Creates a draft by default during setup. |
| Mailchimp | `mailchimp` | Publishing | Creates a campaign draft by default; sending needs a consented audience. |
| Etsy | `etsy` | Commerce | Updates an announcement or an existing listing; does not create inventory. |
| Shopify blog | `shopify` | Commerce | Store URL and write_content scope. Existing adapter uses the legacy REST contract; verify account access. |
| Google Business Profile | `google_business` | Commerce | Requires business.manage and access to the location. |
| Transistor | `transistor` | Podcast and voice | Hosted audio required; creates an episode draft by default during setup. |
| Buzzsprout | `buzzsprout` | Podcast and voice | Hosted audio required; creates an episode draft by default during setup. |
| PR wire | `pr_wire` | Publishing | Configure either your contracted wire API or its email desk in advanced settings. |
| MCP server | `mcp` | Integration | Use an authorised Streamable HTTP server and map release fields to tool arguments. |
| Parinita Vaak | `vaak` | Podcast and voice | Enrolled voice, consent and shared media storage are required. This renders audio without publishing it. |

## Product integrations outside destination publishing

| Integration | Implemented path | Production requirement |
|---|---|---|
| Denizen / Qwen | Server-side text generation, brand voice, campaigns and editorial review | Model endpoint, chosen model and valid runtime credential. The existing local Qwen connection does not certify deployment credentials or writing quality. |
| Witness / OIDC | Company sign-in, role mapping, session and attributable approval | Deployed issuer, client, redirect URI, session secret and tested role assignments. See SSO.md and WITNESS.md. |
| Chrysalis | Audit and release anchoring; signed digest-bound receipt verification | Assurance endpoint, bearer secret and receipt verification public key. Test wrong digest, wrong key and approval revocation against the deployed service. |
| Vaak | Enrolled-voice synthesis and governed audio artifact transport | Actual service contract, enrolled voice/consent, endpoint credentials and writable shared media volume. |
| PR/media intelligence | Normalized contacts and coverage import APIs | Licensed source data and a provider-specific import integration. This is not a native Cision or Muck Rack connector. |
| AEO | Configurable REST probes and normalized citation observations | Operator-approved probe endpoint, field mappings and licensed credentials. Not a universal answer-engine API. |
| Engagement and performance | Authenticated normalized inbox and outcome APIs | Provider-specific event import. Universal native inbox readers and automatic token renewal are not supplied. |

## What changed in this hardening update

- All declared destinations are exposed through one server-owned setup catalogue; no four-option console restriction remains.
- Read-only readiness distinguishes missing server secrets from actual account verification; secret values never appear in its output.
- Editing cannot clear a provider's required configuration through an empty-object validation bypass. Malformed nested settings produce validation errors, not application crashes.
- Credential-shaped fields must use server variable references. Provider errors omit response bodies and redact referenced credentials. HTTP client URL logging is disabled because bot/webhook URLs may carry secrets.
- Caller requests cannot forge agent history, voice receipts or AI-review metadata.
- Provider draft and creator-review deliveries no longer mark releases as published. Draft delivery is still recorded and deduplicated; finishing publication in the provider requires a separate controlled workflow.
- Partial SMTP recipient refusal is a failed delivery requiring reconciliation, not a successful send. Do not retry a partially accepted recipient list indiscriminately.
- HTML attributes and copy are escaped in the publishing/Shopify adapters.
- The Compose worker shares the audio volume and has a heartbeat check. CI boots the real PostgreSQL/API/worker stack and checks the authentication boundary.

## Required live acceptance before launch

For each enabled account, record owner, scopes, expiry/renewal procedure, permitted destination and classification, one approved test release, provider receipt and failure/retry reconciliation. Account owners must approve test publication; this code update does not send messages or posts.

Run the release checks and Helm validation. Install the immutable image on the intended cluster with real hostname/TLS, database, backup/restore, egress restrictions and runtime secrets. Validate Witness roles, Chrysalis receipts and audio storage there. All those checks must have actual deployment evidence before labelling the installation production-ready.

Known limits remain explicit: operator-managed token renewal, provider-dependent media/inbox support, no configured target Kubernetes context/hostname in this workspace, and no live certification of all external accounts. Provider mocks verify request/response contracts; they do not prove current service access.
