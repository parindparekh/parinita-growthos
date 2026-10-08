# Provider destinations

Every provider endpoint is created with `POST /v1/feeds` (`direction: "outbound"`) and used with
`POST /v1/content/{id}/publish` or "Send" in the console. All of them sit behind the same destination policy,
gate, idempotency record and audit trail.

**Status of all adapters in this release: contract-tested against local mocks built from each provider's public
API documentation (October 2026). Not yet exercised against live accounts.**

## What text is posted (social)

1. Amplify copy for that channel, if it was generated from the current content version (it is drift-checked).
2. Otherwise: title, then summary (or body), then the CTA link.

Text is trimmed at a word boundary to the network's limit; the link is never cut. Set `"text_source": "master"`
to always use option 2.

## Social

| Protocol | Config | Notes |
|---|---|---|
| `linkedin` | `author_urn` (`urn:li:organization:<id>` or `urn:li:person:<id>`), `bearer_token_env`, optional `api_version` (YYYYMM), `visibility` | Posts API `POST /rest/posts`. Needs `w_organization_social` (or `w_member_social`). Tokens last 60 days; refresh is not automated. LinkedIn retires API versions: pin `api_version` and bump it yearly. Reserved "little text" characters are escaped. |
| `x` | either `consumer_key_env` + `consumer_secret_env` + `access_token_env` + `access_token_secret_env` (OAuth 1.0a, tokens do not expire), or `bearer_token_env` (OAuth 2.0 user token, expires in 2 h, refresh not automated) | `POST /2/tweets`. 280 weighted characters (links count 23). X rejects duplicate text. |
| `mastodon` | endpoint `url` = instance, `bearer_token_env`, optional `visibility`, `max_chars` | `POST /api/v1/statuses` with `Idempotency-Key`, so it is fully retry-safe. |
| `bluesky` | `identifier` (handle), `app_password_env`, optional endpoint `url` (PDS, default `https://bsky.social`) | Creates a session, then `com.atproto.repo.createRecord`. Links get rich-text facets. 300 characters. |

## Team and community messaging

| Protocol | Config | Notes |
|---|---|---|
| `slack` | `bearer_token_env` (bot token with `chat:write`), `channel` | `chat.postMessage`. Slack reports errors inside a 200; those are recorded as failures. |
| `teams` | `webhook_url_env` (Workflows webhook URL, stored as a secret), optional `link_label` | Adaptive Card. Office 365 connectors are retired; create the webhook with the Workflows template. |
| `discord` | `webhook_url_env` | Mentions are disabled, so release text cannot ping `@everyone`. |
| `telegram` | `bot_token_env`, `chat_id` | Bot must be in the chat or channel. The token is never echoed in errors. |

## WhatsApp

| Protocol | Config | Notes |
|---|---|---|
| `whatsapp` | `phone_number_id`, `bearer_token_env` (system-user token), `recipients_env` (comma-separated numbers or group ids, stored as a secret), `template`, `language` (default `en_US`), `body_parameters` (release fields in template order; default `["title","cta_url"]`), optional `api_version` (default `v25.0`), `recipient_type: "group"`, `max_param_chars` | WhatsApp Business Platform Cloud API. **Templates only.** |

What to know before using it:

- WhatsApp lets a business start a conversation only with a **pre-approved template**. Free-form text works only
  within 24 hours of the person's last message to you, so this adapter never sends it.
- Create the template in WhatsApp Manager first, for example `{{1}}` / `{{2}}` / `Read more: {{3}}`. Its fixed
  wording never passes the GrowthOS gate, so keep it neutral and let the variables carry the release.
- Recipients must have opted in to hear from you on WhatsApp. Holding that consent is your responsibility.
- At most 100 recipients per destination. If one fails, the delivery is marked failed and "Send again" continues
  with that recipient; nobody receives the release twice. Phone numbers are never written to errors or the delivery record.
- Meta charges per template message, and marketing templates are subject to per-user frequency limits.
- There is no public API for posting to a WhatsApp **Channel**; this reaches individual numbers and groups.
- Add `graph.facebook.com` to `DESTINATION_ALLOWLIST` if you use one.

## Social (v1.7)

| Protocol | Config | Notes |
|---|---|---|
| `reddit` | `subreddit`, `client_id`, `client_secret_env`, `refresh_token_env` (scope `submit`) **or** `username` + `password_env` (script app), optional `kind` (`link`/`self`), `flair_id`, `resubmit`, `sendreplies` | OAuth token from `www.reddit.com/api/v1/access_token`, then `POST /api/submit` (`api_type=json`). Link post when the release has a CTA/source URL, otherwise self post. Reddit refuses a URL already posted to the subreddit (`ALREADY_SUB`) unless `resubmit`. Descriptive User-Agent is sent automatically. Not retried after it may have been processed. |
| `facebook` | `page_id`, `page_token_env` (Page token with `pages_manage_posts`), optional `unpublished`, `graph_version` | `POST /{page_id}/feed` with `message` + `link` (rendered as a preview card). |
| `instagram` | `ig_user_id`, `access_token_env`, optional `image_url` fallback | Two steps: `/media` (image container) then `/media_publish`. **Needs a public https image** (`metadata.public.image_url` on the release). A failed publish keeps the container id as the resume point. |
| `threads` | `user_id`, `access_token_env` | `/threads` TEXT container (+ `link_attachment`) then `/threads_publish`. 500 chars. Container kept on a failed publish step. |
| `pinterest` | `board_id`, `bearer_token_env` (`pins:write`), optional `alt_text`, `image_url` | `POST /v5/pins` with `media_source.image_url`. **Needs an image.** |
| `tiktok` | `access_token_env`, optional `privacy_level`, `direct_post`, `disable_comment` | Content Posting API photo post pulled from `metadata.public.image_urls` (or `image_url`). Default `MEDIA_UPLOAD` + `SELF_ONLY`: the post lands in the creator's inbox for review; set `direct_post` and a privacy level to post directly. The image domain must be verified with TikTok. No text-only posts exist. |
| `tumblr` | `blog`, `bearer_token_env` (OAuth 2.0), optional `tags`, `state` | Neue Post Format: heading, text, link blocks. |
| `lemmy` | endpoint `url` = instance, `community_id`, `username`, `password_env` | Login then `POST /api/v3/post`. Works on any Lemmy instance. |

## Commerce and local business (v1.7)

| Protocol | Config | Notes |
|---|---|---|
| `etsy` | `shop_id`, `keystring`, `bearer_token_env` (`shops_w` / `listings_w`), `mode` (`announcement` default, or `listing` + `listing_id`) | Etsy has no "post". `announcement` updates the shop announcement; `listing` updates the title/description of an existing listing. Creating listings (price, inventory, shipping) stays manual by design. Tokens last 1 h; refresh is not automated. |
| `shopify` | endpoint `url` = store, `blog_id`, `access_token_env` (`write_content`), optional `api_version`, `draft`, `tags`, `author` | Blog article via the Admin REST API; body as escaped HTML paragraphs; `metadata.public.image_url` becomes the featured image. |
| `google_business` | `account_id`, `location_id`, `bearer_token_env` (`business.manage`), optional `action_type` | "What's new" local post with a call-to-action; image attached when present. |

## Blogs and newsletters (v1.7)

| Protocol | Config | Notes |
|---|---|---|
| `devto` | `api_key_env`, optional `tags` (max 4), `organization_id`, `draft` | `POST /api/articles`, markdown body, canonical URL = release source. |
| `ghost` | endpoint `url` = site, `admin_key_env` (`id:secret`), optional `tags`, `draft`, `accept_version` | Admin API: a 5-minute HS256 JWT is minted per send from the admin key. |
| `buttondown` | `api_key_env`, optional `draft` | `POST /v1/emails`; `about_to_send` queues the email, `draft` does not. |
| `mailchimp` | `api_key_env`, `list_id`, `from_name`, `reply_to`, optional `draft` | Three steps: create campaign, set content, send. The campaign id is the resume point, so a failed later step never creates a second campaign. |

## More messaging (v1.7)

| Protocol | Config | Notes |
|---|---|---|
| `google_chat` | `webhook_url_env` (space webhook, stored as a secret) | `{"text": ...}` |
| `mattermost` | `webhook_url_env`, optional `channel`, `username` | Incoming webhook. |
| `matrix` | endpoint `url` = homeserver, `room_id` (`!room:server`), `access_token_env` | `PUT .../send/m.room.message/{txnId}` with the delivery id as transaction id: Matrix de-duplicates retries itself. |
| `zulip` | endpoint `url` = realm, `bot_email`, `api_key_env`, `stream`, optional `topic` | `POST /api/v1/messages` with bot credentials. |

## Not supported, and why

| Network | Reason |
|---|---|
| YouTube community posts, Snapchat, Substack, Nextdoor, Medium | No public write API (Medium's was retired). Use the Feed Fabric RSS/Atom output where the platform imports feeds. |
| YouTube / TikTok video, Instagram Reels | Need a rendered video asset; GrowthOS governs copy and metadata, not video production. Vaak audio is the only media it renders. |
| WhatsApp Channels, Telegram Stories, LinkedIn newsletters | No posting API. |

Images: networks that cannot post text alone (`instagram`, `pinterest`, `tiktok`) read `metadata.public.image_url` or
`metadata.public.image_urls` from the release. Metadata is not governed, so attaching an image does not create a new
content version; the image host must be public https (and, for TikTok, verified).

## Newsroom / CMS

| Protocol | Config | Notes |
|---|---|---|
| `wordpress` | endpoint `url` = site, `username`, `app_password_env`, optional `status` (`publish`/`draft`/`pending`/`private`), `categories`, `tags`, `author` | REST API with an application password. Body is sent as escaped HTML paragraphs. A `draft` does not mark the release as sent. |

## Anything with an MCP server, and Parinita Vaak

See `MCP.md` (`protocol: "mcp"`) and `VAAK.md` (`protocol: "vaak"`).

Not built natively: Facebook / Instagram / Threads, YouTube, TikTok, Ghost, HubSpot, Mailchimp. Reach them through
the `mcp` or `webhook` destination, or add an adapter (`PROVIDER_ADAPTER_GUIDE.md`).

## Podcast hosts

The content item must carry `metadata.audio_url` (audio you already host). GrowthOS does not upload audio.

| Protocol | Config | Notes |
|---|---|---|
| `transistor` | `api_key_env`, `show_id`, optional `publish: false` | Creates a draft episode, then publishes it. If the second step fails, the next Send resumes at publishing instead of creating a duplicate. |
| `buzzsprout` | `api_token_env`, numeric `podcast_id`, optional `private`, `artist`, `publish: false` | `POST /api/{podcast_id}/episodes.json`. |

## PR wire

The big wires have no self-serve submission API. `pr_wire` builds one wire-ready release (label, headline,
dateline, body, media contact, `###`) from the governed content and hands it over:

| Mode | Config | What happens |
|---|---|---|
| `"mode": "email"` | `to` (the wire's desk address), optional `subject_prefix`, `dateline_city`, `contact`, `release_label` | Sent over the configured SMTP relay. |
| `"mode": "api"` | endpoint `url`, `auth: {scheme: bearer\|header\|basic, secret_env, header?, username?}`, `field_map: {<wire field>: <package field>}`, optional `static`, `id_field` | JSON `POST` to the endpoint in your wire contract. |

Package fields available to `field_map`: `headline`, `subheadline`, `dateline`, `body`, `contact`, `cta_url`,
`release_text`, `release_at`, `locale`, `content_id`, `content_hash`, `sources`.

The adapter adds structure only. Company boilerplate ("About ...") belongs in the release body, where the gate
checks it like any other sentence.

## Retry policy

A post that might already exist is never sent twice automatically.

| Situation | Mastodon, webhook (idempotency key) | LinkedIn, X, Bluesky, Buzzsprout, Transistor create, wire API |
|---|---|---|
| Could not connect | retried | retried |
| HTTP 429 | retried | retried |
| Timeout after sending, HTTP 5xx | retried | **not retried**; delivery marked failed for a person to check |

Email (SMTP, wire desk) is attempted once. A failed delivery can be sent again from the console; a delivery that
succeeded is never repeated for the same content version.

## Example

```bash
curl -X POST $BASE/v1/feeds -H "X-API-Key: $ADMIN" -H 'Content-Type: application/json' -d '{
  "name": "Company page", "slug": "linkedin-company", "direction": "outbound", "protocol": "linkedin",
  "config": {"author_urn": "urn:li:organization:2414183", "bearer_token_env": "GROWTHOS_SECRET_LINKEDIN_TOKEN",
             "api_version": "202609", "classifications": ["pr", "social"]}}'
```

Add the provider's API host to `DESTINATION_ALLOWLIST` if you use one: `api.linkedin.com`, `api.x.com`,
`bsky.social`, `api.transistor.fm`, `www.buzzsprout.com`, your Mastodon instance, your wire's host.
