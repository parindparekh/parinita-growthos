"""Provider adapters, exercised against a local mock that speaks each provider's documented request shape.
These are contract tests. They do not prove a live account accepts the request; that is an acceptance step."""
import json
import re
from urllib.parse import unquote

import pytest
from oauthlib.oauth1.rfc5849 import signature as oauth_sig

import app.agents as agents_mod
from app.adapters.social import linkedin_escape
from app.adapters._common import compose, x_weight
from app.config import settings
from tests.conftest import AUDITOR, BOOT, EDITOR, PUBLISHER, feed, make, run_pipeline

BODY = "GrowthOS routes governed content (PR, social, podcast) to every feed destination."


@pytest.fixture()
def providers(monkeypatch, sink, lan):
    """Point every fixed-host provider adapter at the mock."""
    monkeypatch.setattr(settings, "provider_base_overrides",
                        json.dumps({p: sink.url for p in ("linkedin", "x", "bluesky", "transistor", "buzzsprout")}))
    return sink


def approved(client, **kw):
    kw.setdefault("classification", "social")
    kw.setdefault("title", "GrowthOS is live")
    kw.setdefault("body", BODY)
    kw.setdefault("cta_url", "https://parinita.example/growthos")
    c = make(client, **kw)
    assert run_pipeline(client, c["id"])["state"] == "approved"
    return c["id"]


def publish(client, cid, ep):
    return client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)


def dest(client, protocol, slug=None, url="", **config):
    return feed(client, name=protocol, slug=slug or protocol.replace("_", "-"), direction="outbound", protocol=protocol, url=url, config=config)


# ------------------------------------------------------------------------------ LinkedIn
def test_linkedin_post(client, providers):
    providers.reply("POST", "/rest/posts", (201, {"x-restli-id": "urn:li:share:7001"}, {}))
    ep = dest(client, "linkedin", author_urn="urn:li:organization:2414183", bearer_token_env="GROWTHOS_SECRET_LI_TOKEN", api_version="202609")
    r = publish(client, approved(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "urn:li:share:7001"
    req = providers.calls("POST", "/rest/posts")[0]
    assert req["headers"]["authorization"] == "Bearer li-access-token"
    assert req["headers"]["linkedin-version"] == "202609" and req["headers"]["x-restli-protocol-version"] == "2.0.0"
    b = req["json"]
    assert b["author"] == "urn:li:organization:2414183" and b["lifecycleState"] == "PUBLISHED" and b["visibility"] == "PUBLIC"
    assert b["distribution"] == {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []}
    # Reserved "little text" characters are escaped (an unescaped "(" truncates the post), the link is not.
    assert "\\(PR, social, podcast\\)" in b["commentary"] and "https://parinita.example/growthos?utm_source=growthos" in b["commentary"]


def test_linkedin_escape_rules():
    assert linkedin_escape("A_B (x) [y] {z} <w> @me *b* ~s~ a|b #tag #1 # alone https://x.io/a_b(c)") == \
        "A\\_B \\(x\\) \\[y\\] \\{z\\} \\<w\\> \\@me \\*b\\* \\~s\\~ a\\|b #tag #1 \\# alone https://x.io/a_b(c)"


def test_linkedin_failures_are_explained_and_not_blindly_retried(client, providers):
    ep = dest(client, "linkedin", author_urn="urn:li:organization:1", bearer_token_env="GROWTHOS_SECRET_LI_TOKEN")
    cid = approved(client)
    providers.reply("POST", "/rest/posts", (500, {}, {"message": "boom"}))
    assert publish(client, cid, ep).status_code == 502
    assert len(providers.calls("POST", "/rest/posts")) == 1  # a 5xx may have created the post: never auto-retried
    providers.reply("POST", "/rest/posts", (401, {}, {"message": "expired"}))
    r = publish(client, cid, ep)
    assert r.status_code == 502 and "60 days" in r.json()["detail"]
    providers.reply("POST", "/rest/posts", (426, {}, {"code": "NONEXISTENT_VERSION"}))
    assert "api_version" in publish(client, cid, ep).json()["detail"]
    assert re.fullmatch(r"20\d{4}", providers.calls("POST", "/rest/posts")[0]["headers"]["linkedin-version"])  # default when not pinned


# ------------------------------------------------------------------------------ X
OAUTH1 = dict(consumer_key_env="GROWTHOS_SECRET_X_CK", consumer_secret_env="GROWTHOS_SECRET_X_CS",
              access_token_env="GROWTHOS_SECRET_X_AT", access_token_secret_env="GROWTHOS_SECRET_X_ATS")


def test_x_post_is_signed_with_oauth1_and_fits_280(client, providers):
    providers.reply("POST", "/2/tweets", (429, {"retry-after": "0"}, {}), (201, {}, {"data": {"id": "1900", "text": "ok"}}))
    ep = dest(client, "x", **OAUTH1)
    long_body = "GrowthOS routes governed content to every feed destination and checks the evidence first. " * 6
    r = publish(client, approved(client, body=long_body), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "1900" and r.json()["attempts"] == 2  # 429 is safe to retry
    req = providers.calls("POST", "/2/tweets")[-1]
    text = req["json"]["text"]
    assert x_weight(text) <= 280 and text.endswith("https://parinita.example/growthos?utm_source=growthos&utm_medium=content&utm_campaign=always-on")
    assert "\u2026" in text
    # Verify the signature with an independent OAuth library.
    auth = req["headers"]["authorization"]
    assert auth.startswith("OAuth ")
    params = {k: unquote(v) for k, v in re.findall(r'(\w+)="([^"]*)"', auth)}
    assert params["oauth_consumer_key"] == "x-consumer-key" and params["oauth_token"] == "x-access-token"
    base = oauth_sig.signature_base_string("POST", providers.url + "/2/tweets", oauth_sig.normalize_parameters(
        [(k, v) for k, v in params.items() if k != "oauth_signature"]))
    assert oauth_sig.sign_hmac_sha1(base, "x-consumer-secret", "x-access-token-secret") == params["oauth_signature"]


def test_x_weighting_and_oauth2_alternative(client, providers):
    assert x_weight("a" * 10 + " https://example.com/" + "p" * 80) == 11 + 23      # every URL counts as 23
    assert x_weight("\u65e5\u672c\u8a9e") == 6                                     # CJK counts double
    providers.reply("POST", "/2/tweets", (201, {}, {"data": {"id": "7"}}))
    ep = dest(client, "x", slug="x-oauth2", bearer_token_env="GROWTHOS_SECRET_MASTO")
    assert publish(client, approved(client), ep).status_code == 200
    assert providers.calls("POST", "/2/tweets")[0]["headers"]["authorization"] == "Bearer masto-token"


# ------------------------------------------------------------------------------ Mastodon
def test_mastodon_status_is_idempotent_and_retried(client, sink, lan):
    sink.reply("POST", "/api/v1/statuses", (503, {}, {}), (200, {}, {"id": "110", "url": "https://social.example/@p/110"}))
    ep = dest(client, "mastodon", url=sink.url, bearer_token_env="GROWTHOS_SECRET_MASTO", visibility="unlisted")
    r = publish(client, approved(client), ep)
    assert r.json()["provider_id"] == "https://social.example/@p/110" and r.json()["attempts"] == 2
    a, b = sink.calls("POST", "/api/v1/statuses")
    assert a["headers"]["idempotency-key"] == b["headers"]["idempotency-key"] == r.json()["delivery_id"]
    assert b["headers"]["authorization"] == "Bearer masto-token"
    assert b["json"]["visibility"] == "unlisted" and b["json"]["language"] == "en" and b["json"]["status"].startswith("GrowthOS is live")


# ------------------------------------------------------------------------------ Bluesky
def test_bluesky_post_with_link_facets(client, providers):
    providers.reply("POST", "/xrpc/com.atproto.server.createSession", (200, {}, {"did": "did:plc:abc", "accessJwt": "jwt-1"}))
    providers.reply("POST", "/xrpc/com.atproto.repo.createRecord", (200, {}, {"uri": "at://did:plc:abc/app.bsky.feed.post/3k", "cid": "b"}))
    ep = dest(client, "bluesky", identifier="parinita.example", app_password_env="GROWTHOS_SECRET_BSKY")
    r = publish(client, approved(client, title="Caf\u00e9 launch \u2014 GrowthOS is live"), ep)
    assert r.json()["provider_id"].startswith("at://did:plc:abc/")
    login = providers.calls("POST", "/xrpc/com.atproto.server.createSession")[0]["json"]
    assert login == {"identifier": "parinita.example", "password": "bsky-app-password"}
    req = providers.calls("POST", "/xrpc/com.atproto.repo.createRecord")[0]
    assert req["headers"]["authorization"] == "Bearer jwt-1" and req["json"]["repo"] == "did:plc:abc"
    rec = req["json"]["record"]
    assert rec["$type"] == "app.bsky.feed.post" and rec["createdAt"].endswith("Z") and len(rec["text"]) <= 300
    f = rec["facets"][0]  # facet offsets are UTF-8 *byte* positions, which differ from character positions here
    raw = rec["text"].encode("utf-8")
    assert raw[f["index"]["byteStart"]:f["index"]["byteEnd"]].decode() == f["features"][0]["uri"]
    assert f["features"][0]["uri"].startswith("https://parinita.example/growthos")


# ------------------------------------------------------------------------------ social copy source
def test_social_text_prefers_current_amplify_copy_and_drops_stale_copy(client, providers, monkeypatch):
    providers.reply("POST", "/2/tweets", (201, {}, {"data": {"id": "1"}}))
    monkeypatch.setattr(agents_mod, "generate_json", lambda s, u, f: (
        ({"posts": [{"channel": "x", "copy": "Governed content, routed to every feed destination."}]}, "model") if "Amplify" in s else (f, "deterministic")))
    cid = make(client, classification="social", title="GrowthOS is live", body=BODY)["id"]
    client.post(f"/v1/content/{cid}/agents/run", json={"agent": "amplify", "options": {"channels": ["x"]}}, headers=EDITOR)
    client.post(f"/v1/content/{cid}/agents/run", json={"agent": "gate"}, headers=EDITOR)
    ep = dest(client, "x", **OAUTH1)
    publish(client, cid, ep)
    assert providers.calls("POST", "/2/tweets")[0]["json"]["text"] == "Governed content, routed to every feed destination."
    # Edit the master: the old copy belongs to the previous version and must not go out.
    new_body = "GrowthOS routes governed content to feeds."
    client.patch(f"/v1/content/{cid}", json={"body": new_body, "claims": [{"text": f"GrowthOS is live. {new_body}", "sources": [{"uri": "https://example.com/e"}]}]}, headers=EDITOR)
    client.post(f"/v1/content/{cid}/agents/run", json={"agent": "gate"}, headers=EDITOR)
    publish(client, cid, ep)
    assert providers.calls("POST", "/2/tweets")[1]["json"]["text"] == "GrowthOS is live\n\n" + new_body


def test_compose_never_cuts_the_link():
    p = {"title": "T", "summary": "word " * 200, "cta_url": "https://example.com/a?b=c", "body": ""}
    out = compose(p, "linkedin", 120)
    assert len(out) <= 120 and out.endswith("\u2026\n\nhttps://example.com/a?b=c") and "word\u2026" in out


# ------------------------------------------------------------------------------ podcast hosts
AUDIO = {"audio_url": "https://cdn.example.com/ep1.mp3", "audio_type": "audio/mpeg"}


def test_transistor_creates_then_publishes_and_resumes_after_partial_failure(client, providers):
    providers.reply("POST", "/v1/episodes", (201, {}, {"data": {"id": "555", "type": "episode"}}))
    providers.reply("PATCH", "/v1/episodes/555/publish", (500, {}, {}), (500, {}, {}), (500, {}, {}), (200, {}, {"data": {"id": "555"}}))
    ep = dest(client, "transistor", api_key_env="GROWTHOS_SECRET_TRANSISTOR", show_id="99", classifications=["general"])
    cid = approved(client, classification="general", title="Episode 1", metadata=AUDIO)
    first = publish(client, cid, ep)
    assert first.status_code == 502 and "created as a draft but not published" in first.json()["detail"]
    d = client.get(f"/v1/content/{cid}/deliveries", headers=EDITOR).json()[0]
    assert d["status"] == "failed" and d["provider_id"] == "episode:555"
    second = publish(client, cid, ep)
    assert second.status_code == 200 and second.json()["provider_id"] == "episode:555"
    assert len(providers.calls("POST", "/v1/episodes")) == 1          # no duplicate episode on retry
    create = providers.calls("POST", "/v1/episodes")[0]
    assert create["headers"]["x-api-key"] == "transistor-key"
    assert create["json"]["episode[show_id]"] == "99" and create["json"]["episode[audio_url]"] == AUDIO["audio_url"]
    assert providers.calls("PATCH", "/v1/episodes/555/publish")[-1]["json"] == {"episode[status]": "published"}


def test_buzzsprout_episode(client, providers):
    providers.reply("POST", "/api/140447/episodes.json", (201, {}, {"id": 788881, "title": "Episode 1"}))
    ep = dest(client, "buzzsprout", api_token_env="GROWTHOS_SECRET_BUZZ", podcast_id="140447", classifications=["general"])
    cid = approved(client, classification="general", title="Episode 1", metadata=AUDIO)
    r = publish(client, cid, ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "episode:788881"
    req = providers.calls("POST", "/api/140447/episodes.json")[0]
    assert req["headers"]["authorization"] == "Token token=buzz-token" and req["headers"]["user-agent"].startswith("Parinita-GrowthOS")
    assert req["json"]["audio_url"] == AUDIO["audio_url"] and req["json"]["private"] is False and req["json"]["published_at"]
    assert req["json"]["guid"] == f"growthos-{cid}"


def test_podcast_hosts_refuse_items_without_audio(client, providers):
    ep = dest(client, "buzzsprout", api_token_env="GROWTHOS_SECRET_BUZZ", podcast_id="1", classifications=["general"])
    r = publish(client, approved(client, classification="general"), ep)
    assert r.status_code == 502 and "audio_url" in r.json()["detail"] and providers.requests == []


# ------------------------------------------------------------------------------ PR wire
def test_pr_wire_contract_api_mode(client, sink, lan):
    sink.reply("POST", "/partner/v3/releases", (202, {}, {"releaseId": "W-2026-0001", "status": "IN_REVIEW"}))
    ep = dest(client, "pr_wire", url=sink.url + "/partner/v3/releases", mode="api", classifications=["pr"],
              auth={"scheme": "header", "header": "X-Partner-Key", "secret_env": "GROWTHOS_SECRET_WIRE"},
              field_map={"headline": "headline", "bodyText": "release_text", "language": "locale", "clientRef": "content_id", "links": "sources"},
              static={"accountId": "ACME-77", "distribution": "US1"}, id_field="releaseId", dateline_city="New York",
              contact={"name": "Press Office", "email": "press@parinita.example"})
    cid = approved(client, classification="pr", title="Parinita launches GrowthOS", body="Parinita today announced GrowthOS.")
    r = publish(client, cid, ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "W-2026-0001" and "editorial review" in r.json()["detail"]
    req = sink.calls("POST", "/partner/v3/releases")[0]
    assert req["headers"]["x-partner-key"] == "wire-partner-key" and req["headers"]["idempotency-key"] == r.json()["delivery_id"]
    b = req["json"]
    assert b["accountId"] == "ACME-77" and b["distribution"] == "US1" and b["headline"] == "Parinita launches GrowthOS" and b["clientRef"] == cid
    assert b["links"] == ["https://example.com/evidence"]
    text = b["bodyText"].splitlines()
    assert text[0] == "FOR IMMEDIATE RELEASE" and text[-1] == "###" and "Press Office" in text
    assert re.search(r"^NEW YORK, [A-Z][a-z]+ \d{1,2}, 20\d\d -- Parinita today announced GrowthOS\.$", b["bodyText"], re.M)


def test_pr_wire_email_mode_and_plain_smtp(client, lan, smtp_sink):
    wire = dest(client, "pr_wire", mode="email", to="desk@wire.example", classifications=["pr"], dateline_city="New York")
    plain = dest(client, "smtp", to=["editor@outlet.example", "news@outlet.example"], subject_prefix="[Parinita] ", classifications=["pr"])
    cid = approved(client, classification="pr", title="Parinita launches GrowthOS", body="Parinita today announced GrowthOS.")
    assert publish(client, cid, wire).status_code == 200 and publish(client, cid, plain).status_code == 200
    w, p = smtp_sink.messages
    assert w["to"] == ["desk@wire.example"] and "Subject: Press release: Parinita launches GrowthOS" in w["data"]
    assert "FOR IMMEDIATE RELEASE" in w["data"] and "NEW YORK," in w["data"] and w["data"].rstrip().endswith("###")
    assert p["to"] == ["editor@outlet.example", "news@outlet.example"] and "Subject: [Parinita] Parinita launches GrowthOS" in p["data"]
    assert "X-GrowthOS-Content-Hash:" in p["data"] and "From: newsroom@parinita.example" in p["data"]


# ------------------------------------------------------------------------------ cross-cutting
@pytest.mark.parametrize("protocol,url,config,needle", [
    ("linkedin", "", {"bearer_token_env": "GROWTHOS_SECRET_LI_TOKEN"}, "author_urn"),
    ("linkedin", "", {"author_urn": "urn:li:organization:1", "bearer_token_env": "LINKEDIN_TOKEN"}, "GROWTHOS_SECRET_"),
    ("x", "", {"consumer_key_env": "GROWTHOS_SECRET_X_CK"}, "bearer_token_env"),
    ("x", "", {**OAUTH1, "access_token_secret_env": "DATABASE_URL"}, "GROWTHOS_SECRET_"),
    ("mastodon", "", {"bearer_token_env": "GROWTHOS_SECRET_MASTO"}, "requires a URL"),
    ("bluesky", "", {"identifier": "p.example"}, "app_password_env"),
    ("transistor", "", {"api_key_env": "GROWTHOS_SECRET_TRANSISTOR"}, "show_id"),
    ("buzzsprout", "", {"api_token_env": "GROWTHOS_SECRET_BUZZ", "podcast_id": "abc"}, "numeric"),
    ("pr_wire", "https://wire.example/api", {"mode": "api", "field_map": {"h": "nonsense"}, "auth": {"secret_env": "GROWTHOS_SECRET_WIRE"}}, "unknown package field"),
    ("pr_wire", "https://wire.example/api", {"mode": "api", "field_map": {"h": "headline"}, "auth": {"secret_env": "API_KEY"}}, "GROWTHOS_SECRET_"),
    ("pr_wire", "", {"mode": "email"}, "config.to"),
])
def test_bad_provider_config_is_rejected_at_creation(client, protocol, url, config, needle):
    r = client.post("/v1/feeds", json={"name": "n", "slug": "s", "direction": "outbound", "protocol": protocol, "url": url, "config": config}, headers=BOOT)
    assert r.status_code == 422 and needle in r.json()["detail"], r.text


def test_provider_endpoints_are_outbound_only_and_never_public_feeds(client):
    bad = client.post("/v1/feeds", json={"name": "n", "slug": "s", "direction": "inbound", "protocol": "mastodon", "url": "https://m.example",
                                         "config": {"bearer_token_env": "GROWTHOS_SECRET_MASTO"}}, headers=BOOT)
    assert bad.status_code == 422 and "must be outbound" in bad.json()["detail"]
    dest(client, "mastodon", url="https://m.example", bearer_token_env="GROWTHOS_SECRET_MASTO")
    assert client.get("/feeds/mastodon").status_code == 404


def test_providers_sit_behind_the_gate_the_policy_and_the_audit_log(client, providers):
    providers.reply("POST", "/rest/posts", (201, {"x-restli-id": "urn:li:share:1"}, {}))
    ep = dest(client, "linkedin", author_urn="urn:li:organization:1", bearer_token_env="GROWTHOS_SECRET_LI_TOKEN")
    blocked = make(client, classification="social", body="Customers love it.", claims=[])["id"]
    r = publish(client, blocked, ep)
    assert r.status_code == 409 and "Hallucination Gate" in r.json()["detail"] and providers.requests == []
    ok = approved(client)
    assert publish(client, ok, ep).json()["duplicate"] is False and publish(client, ok, ep).json()["duplicate"] is True
    assert len(providers.calls("POST", "/rest/posts")) == 1
    last = client.get(f"/v1/audit?content_id={ok}", headers=AUDITOR).json()[0]
    assert last["action"] == "publish.push" and last["decision"] == "success" and last["details"]["protocol"] == "linkedin"


def test_missing_secret_is_reported_without_calling_the_provider(client, providers, monkeypatch):
    monkeypatch.delenv("GROWTHOS_SECRET_LI_TOKEN")
    ep = dest(client, "linkedin", author_urn="urn:li:organization:1", bearer_token_env="GROWTHOS_SECRET_LI_TOKEN")
    r = publish(client, approved(client), ep)
    assert r.status_code == 400 and "GROWTHOS_SECRET_LI_TOKEN is not set" in r.json()["detail"] and providers.requests == []


def test_fixed_host_providers_respect_the_egress_allowlist(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_private_destinations", True)   # skip DNS; test the allowlist only
    monkeypatch.setattr(settings, "destination_allowlist", "hooks.partner.example")
    ep = dest(client, "linkedin", author_urn="urn:li:organization:1", bearer_token_env="GROWTHOS_SECRET_LI_TOKEN")
    r = publish(client, approved(client), ep)
    assert r.status_code == 400 and "api.linkedin.com" in r.json()["detail"] and "DESTINATION_ALLOWLIST" in r.json()["detail"]
