# Parinita Vaak integration

`protocol: "vaak"` renders an approved release as audio through Vaak and keeps the proof next to it.

- GrowthOS decides **what may be said**: evidence, sentence accounting, approval. Copy that is not clear never
  reaches Vaak.
- Vaak decides **whether its voice may say it** and proves that it did: consent, envelope, its own policy
  checks, session manifest, anchoring. A refusal from Vaak is reported verbatim and nothing is attached.

## Flow

1. `POST <vaakd>/twins/{twin_id}/sessions` with verb, channel, register, language.
2. `POST /sessions/{id}/disclose` on call channels.
3. `POST /sessions/{id}/speak` for the headline, the summary and each paragraph. Links and separators are not spoken.
4. `POST /sessions/{id}/close` returns the manifest; `POST /anchor` anchors it.
5. The audio is written to `MEDIA_DIR` and the content item gets `audio_url`, `audio_type`, `audio_bytes`,
   `audio_duration` and `vaak: {twin_id, session_id, manifest_hash, content_digest, anchored_root, rendered_hash}`.

The delivery reference is `manifest:<hash>`. The SHA-256 of the served audio equals the manifest's
`content_digest` (tested), so a listener's file can be checked against Vaak's own record.

Rendering does not mark the release as sent. The audio then feeds Podcast RSS and the Transistor / Buzzsprout
adapters through `audio_url`.

## Set up

```json
{"name": "Newsroom voice", "slug": "vaak", "direction": "outbound", "protocol": "vaak",
 "url": "http://vaakd.pop.internal:8477",
 "config": {"twin_id": "newsroom-voice", "verb": "speak_public", "channel": "local", "register": "professional",
            "bearer_token_env": "GROWTHOS_SECRET_VAAK_TOKEN", "classifications": ["pr", "general"]}}
```

`.env`: `MEDIA_DIR=/media` (the compose file mounts a volume), `TRUSTED_INTERNAL_HOSTS=pop.internal`.
Optional config: `prosody`, `presence_checked`, `anchor: false`, `max_chars`, `routes`.

## Serving rules for `/media`

Audio is served only while the exact version it was rendered from is still approved or published and still
passes the gate. Edit or block the release and its audio returns 404. High-risk classes are never served from
`/media`. In the console, a rendered release shows a player and the manifest hash.

## What to verify on your side

Built against the vaakd owner API routes of the reference daemon and tested against a mock of those routes.
It has **not** been run against a vaakd build. If your build moved a route, set `config.routes`; if it requires
a credential, set `bearer_token_env`. The voice named in `twin_id` must already be enrolled with an envelope that
grants the verb; GrowthOS does not enrol voices or set envelopes.
