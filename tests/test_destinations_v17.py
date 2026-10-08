"""v1.7 destinations: contract tests against a local mock that speaks each provider's documented request shape.
They prove GrowthOS sends what the documentation asks for and handles the documented answers; a live account is an
acceptance step."""
import base64
import json

import pytest

from app.config import settings
from tests.conftest import BOOT, EDITOR, PUBLISHER, feed, make, run_pipeline

FIXED = ("reddit", "reddit_auth", "meta", "threads", "pinterest", "tiktok", "tumblr", "etsy", "google_business", "devto", "buttondown", "mailchimp")
SECRETS = {"GROWTHOS_SECRET_RD_SECRET": "reddit-app-secret", "GROWTHOS_SECRET_RD_REFRESH": "reddit-refresh", "GROWTHOS_SECRET_RD_PASS": "reddit-pass",
           "GROWTHOS_SECRET_FB_PAGE": "fb-page-token", "GROWTHOS_SECRET_IG": "ig-token", "GROWTHOS_SECRET_TH": "threads-token",
           "GROWTHOS_SECRET_PIN": "pin-token", "GROWTHOS_SECRET_TT": "tiktok-token", "GROWTHOS_SECRET_TUMBLR": "tumblr-token",
           "GROWTHOS_SECRET_LEMMY": "lemmy-pass", "GROWTHOS_SECRET_ETSY": "etsy-token", "GROWTHOS_SECRET_SHOPIFY": "shpat-token",
           "GROWTHOS_SECRET_GBP": "gbp-token", "GROWTHOS_SECRET_DEVTO": "devto-key",
           "GROWTHOS_SECRET_GHOST": "66f1a2b3c4d5e6f708091a2b:" + "ab" * 32, "GROWTHOS_SECRET_BTN": "btn-key",
           "GROWTHOS_SECRET_MC": "mc-key-us21", "GROWTHOS_SECRET_MATRIX": "syt-token", "GROWTHOS_SECRET_ZULIP": "zulip-key"}


@pytest.fixture()
def providers(monkeypatch, sink, lan):
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GROWTHOS_SECRET_GCHAT_URL", sink.url + "/gchat")
    monkeypatch.setenv("GROWTHOS_SECRET_MM_URL", sink.url + "/mm")
    monkeypatch.setattr(settings, "provider_base_overrides", json.dumps({p: sink.url for p in FIXED}))
    return sink


def approved(client, **kw):
    kw.setdefault("classification", "social"); kw.setdefault("title", "GrowthOS is live")
    kw.setdefault("body", "GrowthOS routes governed content (PR, social, podcast) to every feed destination.")
    kw.setdefault("cta_url", "https://parinita.example/growthos")
    c = make(client, **kw)
    assert run_pipeline(client, c["id"])["state"] == "approved"
    return c["id"]


def with_image(client):
    return approved(client, metadata={"public": {"image_url": "https://cdn.parinita.example/launch.jpg"}})


def dest(client, protocol, url="", **config):
    return feed(client, name=protocol, slug=protocol.replace("_", "-"), direction="outbound", protocol=protocol, url=url, config=config)


def publish(client, cid, ep):
    return client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)


CTA = "https://parinita.example/growthos?utm_source=growthos&utm_medium=content&utm_campaign=always-on"  # Acquire adds UTM tags


def basic(req):
    return base64.b64decode(req["headers"]["authorization"].split()[1]).decode()


# ------------------------------------------------------------------------------ Reddit
def test_reddit_link_post_with_refresh_token(client, providers):
    providers.reply("POST", "/api/v1/access_token", (200, {}, {"access_token": "rd-access", "expires_in": 3600}))
    providers.reply("POST", "/api/submit", (200, {}, {"json": {"errors": [], "data": {"url": "https://www.reddit.com/r/parinita/comments/abc/x/", "name": "t3_abc"}}}))
    ep = dest(client, "reddit", subreddit="parinita", client_id="abcDEF123456", client_secret_env="GROWTHOS_SECRET_RD_SECRET", refresh_token_env="GROWTHOS_SECRET_RD_REFRESH", username="parinita_bot")
    r = publish(client, approved(client), ep)
    assert r.status_code == 200, r.text
    assert r.json()["provider_id"].startswith("https://www.reddit.com/r/parinita/")
    tok = providers.calls("POST", "/api/v1/access_token")[0]
    assert basic(tok) == "abcDEF123456:reddit-app-secret" and tok["json"]["grant_type"] == "refresh_token" and tok["json"]["refresh_token"] == "reddit-refresh"
    sub = providers.calls("POST", "/api/submit")[0]
    assert sub["headers"]["authorization"] == "Bearer rd-access" and "parinita.growthos" in sub["headers"]["user-agent"] and "/u/parinita_bot" in sub["headers"]["user-agent"]
    assert sub["json"]["sr"] == "parinita" and sub["json"]["kind"] == "link" and sub["json"]["url"] == CTA
    assert sub["json"]["title"] == "GrowthOS is live" and sub["json"]["api_type"] == "json" and sub["json"]["sendreplies"] == "false"


def test_reddit_self_post_duplicate_and_token_failures(client, providers):
    providers.reply("POST", "/api/v1/access_token", (200, {}, {"access_token": "rd-access"}))
    providers.reply("POST", "/api/submit", (200, {}, {"json": {"errors": [["ALREADY_SUB", "that link has already been submitted", "url"]]}}))
    ep = dest(client, "reddit", subreddit="parinita", client_id="abcDEF123456", client_secret_env="GROWTHOS_SECRET_RD_SECRET", username="u", password_env="GROWTHOS_SECRET_RD_PASS", kind="self")
    cid = approved(client)
    r = publish(client, cid, ep)
    assert r.status_code == 502 and "already posted" in r.json()["detail"]
    sub = providers.calls("POST", "/api/submit")[0]["json"]
    assert sub["kind"] == "self" and "text" in sub and sub["text"].endswith(CTA)
    assert providers.calls("POST", "/api/v1/access_token")[0]["json"]["grant_type"] == "password"
    providers.reply("POST", "/api/v1/access_token", (401, {}, {"error": "invalid_grant"}))
    r = publish(client, cid, ep)
    assert r.status_code == 502 and "token request failed" in r.json()["detail"]
    assert len(providers.calls("POST", "/api/submit")) == 1  # never reached submit without a token
    assert client.post("/v1/feeds", json={"name": "bad", "slug": "bad-rd", "direction": "outbound", "protocol": "reddit", "config": {"subreddit": "r/parinita"}}, headers=BOOT).status_code == 422


# ------------------------------------------------------------------------------ Meta
def test_facebook_page_post(client, providers):
    providers.reply("POST", "/v21.0/123456/feed", (200, {}, {"id": "123456_789"}))
    ep = dest(client, "facebook", page_id="123456", page_token_env="GROWTHOS_SECRET_FB_PAGE")
    r = publish(client, approved(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "123456_789"
    f = providers.calls("POST", "/v21.0/123456/feed")[0]["json"]
    assert f["access_token"] == "fb-page-token" and f["link"] == CTA and f["published"] == "true"
    assert f["message"].startswith("GrowthOS is live") and "parinita.example" not in f["message"]  # link rides in its own field


def test_instagram_two_step_publish_resumes_container(client, providers):
    providers.reply("POST", "/v21.0/17841/media", (200, {}, {"id": "container-1"}))
    providers.reply("POST", "/v21.0/17841/media_publish", (400, {}, {"error": {"message": "Media not ready", "code": 9007}}), (200, {}, {"id": "ig-post-1"}))
    ep = dest(client, "instagram", ig_user_id="17841", access_token_env="GROWTHOS_SECRET_IG")
    cid = with_image(client)
    r = publish(client, cid, ep)
    assert r.status_code == 502 and "container kept" in r.json()["detail"]
    r = publish(client, cid, ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "ig-post-1"
    assert len(providers.calls("POST", "/v21.0/17841/media")) == 1  # resumed with the same container, no duplicate
    assert [c["json"]["creation_id"] for c in providers.calls("POST", "/v21.0/17841/media_publish")] == ["container-1", "container-1"]
    media = providers.calls("POST", "/v21.0/17841/media")[0]["json"]
    assert media["image_url"] == "https://cdn.parinita.example/launch.jpg" and media["access_token"] == "ig-token"
    # Text-only releases are refused before any call.
    r = publish(client, approved(client, title="No picture"), ep)
    assert r.status_code == 502 and "image" in r.json()["detail"] and len(providers.calls("POST", "/v21.0/17841/media")) == 1


def test_threads_text_post_with_link(client, providers):
    providers.reply("POST", "/v21.0/9001/threads", (200, {}, {"id": "th-c1"}))
    providers.reply("POST", "/v21.0/9001/threads_publish", (200, {}, {"id": "th-post"}))
    ep = dest(client, "threads", user_id="9001", access_token_env="GROWTHOS_SECRET_TH")
    r = publish(client, approved(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "th-post"
    c = providers.calls("POST", "/v21.0/9001/threads")[0]["json"]
    assert c["media_type"] == "TEXT" and c["link_attachment"] == CTA and len(c["text"]) <= 500


# ------------------------------------------------------------------------------ Pinterest / TikTok / Tumblr / Lemmy
def test_pinterest_pin(client, providers):
    providers.reply("POST", "/v5/pins", (201, {}, {"id": "pin-1"}))
    ep = dest(client, "pinterest", board_id="b1", bearer_token_env="GROWTHOS_SECRET_PIN")
    r = publish(client, with_image(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "pin-1"
    b = providers.calls("POST", "/v5/pins")[0]["json"]
    assert b["media_source"] == {"source_type": "image_url", "url": "https://cdn.parinita.example/launch.jpg"} and b["link"] == CTA


def test_tiktok_photo_post_defaults_to_creator_review(client, providers):
    providers.reply("POST", "/v2/post/publish/content/init/", (200, {}, {"data": {"publish_id": "p1"}, "error": {"code": "ok"}}))
    ep = dest(client, "tiktok", access_token_env="GROWTHOS_SECRET_TT")
    r = publish(client, with_image(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "p1" and "review" in r.json()["detail"]
    b = providers.calls("POST", "/v2/post/publish/content/init/")[0]["json"]
    assert b["post_mode"] == "MEDIA_UPLOAD" and b["post_info"]["privacy_level"] == "SELF_ONLY" and b["source_info"]["photo_images"] == ["https://cdn.parinita.example/launch.jpg"]


def test_tumblr_npf_post(client, providers):
    providers.reply("POST", "/v2/blog/parinita.tumblr.com/posts", (201, {}, {"response": {"id": "7777"}}))
    ep = dest(client, "tumblr", blog="parinita.tumblr.com", bearer_token_env="GROWTHOS_SECRET_TUMBLR", tags=["growthos"])
    r = publish(client, approved(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "7777"
    b = providers.calls("POST", "/v2/blog/parinita.tumblr.com/posts")[0]["json"]
    assert b["content"][0] == {"type": "text", "subtype": "heading1", "text": "GrowthOS is live"} and b["content"][-1]["type"] == "link"


def test_lemmy_login_then_post(client, providers):
    providers.reply("POST", "/api/v3/user/login", (200, {}, {"jwt": "lemmy-jwt"}))
    providers.reply("POST", "/api/v3/post", (200, {}, {"post_view": {"post": {"id": 42, "ap_id": "https://lemmy.example/post/42"}}}))
    ep = dest(client, "lemmy", url=providers.url, community_id="7", username="parinita", password_env="GROWTHOS_SECRET_LEMMY")
    r = publish(client, approved(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "https://lemmy.example/post/42"
    p = providers.calls("POST", "/api/v3/post")[0]
    assert p["headers"]["authorization"] == "Bearer lemmy-jwt" and p["json"]["community_id"] == 7 and p["json"]["url"] == CTA


# ------------------------------------------------------------------------------ commerce / local
def test_etsy_announcement_and_listing_modes(client, providers):
    providers.reply("PUT", "/v3/application/shops/555", (200, {}, {"shop_id": 555}))
    providers.reply("PATCH", "/v3/application/shops/555/listings/999", (200, {}, {"listing_id": 999}))
    cid = approved(client)
    a = dest(client, "etsy", shop_id="555", keystring="ks123", bearer_token_env="GROWTHOS_SECRET_ETSY")
    r = publish(client, cid, a)
    assert r.status_code == 200 and r.json()["provider_id"] == "shop:555:announcement"
    req = providers.calls("PUT", "/v3/application/shops/555")[0]
    assert req["headers"]["x-api-key"] == "ks123" and req["headers"]["authorization"] == "Bearer etsy-token" and req["json"]["announcement"].startswith("GrowthOS is live")
    b = feed(client, name="etsy-listing", slug="etsy-listing", direction="outbound", protocol="etsy",
             config={"shop_id": "555", "keystring": "ks123", "bearer_token_env": "GROWTHOS_SECRET_ETSY", "mode": "listing", "listing_id": "999"})
    r = publish(client, cid, b)
    assert r.status_code == 200 and r.json()["provider_id"] == "listing:999"
    assert providers.calls("PATCH", "/v3/application/shops/555/listings/999")[0]["json"]["title"] == "GrowthOS is live"


def test_shopify_blog_article(client, providers):
    providers.reply("POST", "/admin/api/2026-07/blogs/88/articles.json", (201, {}, {"article": {"id": 1, "admin_graphql_api_id": "gid://shopify/Article/1"}}))
    ep = dest(client, "shopify", url=providers.url, blog_id="88", access_token_env="GROWTHOS_SECRET_SHOPIFY", tags=["launch"])
    r = publish(client, approved(client, body="First paragraph.\n\nSecond <b>paragraph</b>."), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "gid://shopify/Article/1"
    req = providers.calls("POST", "/admin/api/2026-07/blogs/88/articles.json")[0]
    assert req["headers"]["x-shopify-access-token"] == "shpat-token"
    a = req["json"]["article"]
    assert a["body_html"].startswith("<p>First paragraph.</p><p>Second &lt;b&gt;paragraph&lt;/b&gt;.</p>") and a["published"] is True and a["tags"] == "launch"


def test_google_business_local_post(client, providers):
    providers.reply("POST", "/v4/accounts/1/locations/2/localPosts", (200, {}, {"name": "accounts/1/locations/2/localPosts/3"}))
    ep = dest(client, "google_business", account_id="1", location_id="2", bearer_token_env="GROWTHOS_SECRET_GBP")
    r = publish(client, with_image(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"].endswith("/localPosts/3")
    b = providers.calls("POST", "/v4/accounts/1/locations/2/localPosts")[0]["json"]
    assert b["callToAction"] == {"actionType": "LEARN_MORE", "url": CTA} and b["media"][0]["sourceUrl"].endswith("launch.jpg")


# ------------------------------------------------------------------------------ blogs / newsletters
def test_devto_article(client, providers):
    providers.reply("POST", "/api/articles", (201, {}, {"id": 5, "url": "https://dev.to/parinita/growthos"}))
    ep = dest(client, "devto", api_key_env="GROWTHOS_SECRET_DEVTO", tags=["ai", "devops"])
    r = publish(client, approved(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "https://dev.to/parinita/growthos"
    req = providers.calls("POST", "/api/articles")[0]
    assert req["headers"]["api-key"] == "devto-key" and req["json"]["article"]["body_markdown"].endswith(f"[Read more]({CTA})")


def test_ghost_admin_jwt_post(client, providers):
    import jwt as pyjwt
    providers.reply("POST", "/ghost/api/admin/posts/", (201, {}, {"posts": [{"id": "p1", "url": "https://blog.example/growthos/"}]}))
    ep = dest(client, "ghost", url=providers.url, admin_key_env="GROWTHOS_SECRET_GHOST")
    r = publish(client, approved(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "https://blog.example/growthos/"
    req = providers.calls("POST", "/ghost/api/admin/posts/")[0]
    tok = req["headers"]["authorization"].split()[1]
    assert pyjwt.get_unverified_header(tok)["kid"] == "66f1a2b3c4d5e6f708091a2b"
    assert pyjwt.decode(tok, bytes.fromhex("ab" * 32), algorithms=["HS256"], audience="/admin/")["aud"] == "/admin/"
    assert req["json"]["posts"][0]["status"] == "published" and "<p>" in req["json"]["posts"][0]["html"]


def test_buttondown_email(client, providers):
    providers.reply("POST", "/v1/emails", (201, {}, {"id": "em-1"}))
    ep = dest(client, "buttondown", api_key_env="GROWTHOS_SECRET_BTN")
    r = publish(client, approved(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "em-1"
    req = providers.calls("POST", "/v1/emails")[0]
    assert req["headers"]["authorization"] == "Token btn-key" and req["json"]["status"] == "about_to_send" and req["json"]["subject"] == "GrowthOS is live"


def test_mailchimp_three_step_campaign_resumes(client, providers):
    providers.reply("POST", "/3.0/campaigns", (200, {}, {"id": "camp1"}))
    providers.reply("PUT", "/3.0/campaigns/camp1/content", (200, {}, {}))
    providers.reply("POST", "/3.0/campaigns/camp1/actions/send", (500, {}, {"detail": "try later"}), (204, {}, {}))
    ep = dest(client, "mailchimp", api_key_env="GROWTHOS_SECRET_MC", list_id="L1", from_name="Parinita", reply_to="hello@parinita.example")
    cid = approved(client)
    r = publish(client, cid, ep)
    assert r.status_code == 502 and "campaign kept" in r.json()["detail"]
    r = publish(client, cid, ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "camp1" and r.json()["detail"] == "campaign sent"
    assert len(providers.calls("POST", "/3.0/campaigns")) == 1  # the retry resumed campaign camp1; no second campaign
    assert basic(providers.calls("POST", "/3.0/campaigns")[0]) == "anystring:mc-key-us21"
    assert providers.calls("POST", "/3.0/campaigns")[0]["json"]["recipients"] == {"list_id": "L1"}


# ------------------------------------------------------------------------------ messaging
def test_google_chat_and_mattermost_webhooks(client, providers):
    providers.reply("POST", "/gchat", (200, {}, {"name": "spaces/A/messages/B"}))
    providers.reply("POST", "/mm", (200, {}, "ok"))
    cid = approved(client)
    r = publish(client, cid, dest(client, "google_chat", webhook_url_env="GROWTHOS_SECRET_GCHAT_URL"))
    assert r.status_code == 200 and r.json()["provider_id"] == "spaces/A/messages/B"
    r = publish(client, cid, dest(client, "mattermost", webhook_url_env="GROWTHOS_SECRET_MM_URL", channel="town-square"))
    assert r.status_code == 200 and providers.calls("POST", "/mm")[0]["json"]["channel"] == "town-square"
    # The webhook URL is a secret: it must not be accepted in plain endpoint config.
    assert client.post("/v1/feeds", json={"name": "x", "slug": "gc-plain", "direction": "outbound", "protocol": "google_chat",
                                          "config": {"webhook_url_env": "NOT_A_SECRET"}}, headers=BOOT).status_code == 422


def test_matrix_uses_delivery_id_as_transaction_id(client, providers):
    ep = dest(client, "matrix", url=providers.url, room_id="!abc:example.org", access_token_env="GROWTHOS_SECRET_MATRIX")
    providers.dynamic = lambda req: (200, {}, {"event_id": "$evt"}) if req["path"].startswith("/_matrix/") else None
    r = publish(client, approved(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "$evt"
    req = providers.requests[-1]
    assert req["method"] == "PUT" and req["path"].startswith("/_matrix/client/v3/rooms/%21abc%3Aexample.org/send/m.room.message/") and req["path"].endswith(r.json()["delivery_id"])
    assert req["json"] == {"msgtype": "m.text", "body": req["json"]["body"]} and req["headers"]["authorization"] == "Bearer syt-token"


def test_zulip_stream_message(client, providers):
    providers.reply("POST", "/api/v1/messages", (200, {}, {"result": "success", "id": 31}))
    ep = dest(client, "zulip", url=providers.url, bot_email="bot@parinita.example", api_key_env="GROWTHOS_SECRET_ZULIP", stream="announce")
    r = publish(client, approved(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "31"
    req = providers.calls("POST", "/api/v1/messages")[0]
    assert basic(req) == "bot@parinita.example:zulip-key" and req["json"]["to"] == "announce" and req["json"]["topic"] == "GrowthOS is live"


# ------------------------------------------------------------------------------ every new protocol sits behind the same governance
@pytest.mark.parametrize("protocol,cfg", [
    ("reddit", {"subreddit": "parinita", "client_id": "abcDEF123456", "client_secret_env": "GROWTHOS_SECRET_RD_SECRET", "refresh_token_env": "GROWTHOS_SECRET_RD_REFRESH"}),
    ("facebook", {"page_id": "123", "page_token_env": "GROWTHOS_SECRET_FB_PAGE"}),
    ("etsy", {"shop_id": "1", "keystring": "k", "bearer_token_env": "GROWTHOS_SECRET_ETSY"}),
    ("devto", {"api_key_env": "GROWTHOS_SECRET_DEVTO"}),
])
def test_new_destinations_refuse_blocked_and_high_risk_content(client, providers, protocol, cfg):
    ep = dest(client, protocol, **cfg)
    blocked = make(client, classification="pr", title="Big claim", body="We are the #1 platform with 500% growth.", claims=[])
    assert run_pipeline(client, blocked["id"])["state"] == "blocked"
    assert publish(client, blocked["id"], ep).status_code == 409
    investor = make(client, classification="investor", title="Outlook", body="Demand remains healthy.")
    assert publish(client, investor["id"], ep).status_code == 409  # destination does not accept investor content by default
    assert providers.requests == []  # nothing left the process
