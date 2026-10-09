"""Messaging and CMS adapters against local mocks of each provider's documented request shape (contract tests)."""
import json

import pytest

from app.config import settings
from tests.conftest import BOOT, PUBLISHER, feed, make, run_pipeline

BODY = "GrowthOS routes governed content <fast> & safely to every feed destination. @everyone"


@pytest.fixture()
def providers(monkeypatch, sink, lan):
    monkeypatch.setattr(settings, "provider_base_overrides", json.dumps({"slack": sink.url, "telegram": sink.url}))
    monkeypatch.setenv("GROWTHOS_SECRET_TEAMS_URL", sink.url + "/workflows/abc/triggers/manual/paths/invoke?sig=s3cret")
    monkeypatch.setenv("GROWTHOS_SECRET_DISCORD_URL", sink.url + "/api/webhooks/1/tok")
    return sink


def approved(client, **kw):
    kw.setdefault("classification", "social")
    kw.setdefault("title", "GrowthOS is live")
    kw.setdefault("body", BODY)
    kw.setdefault("cta_url", "https://parinita.example/growthos")
    c = make(client, **kw)
    assert run_pipeline(client, c["id"])["state"] == "approved"
    return c["id"]


def dest(client, protocol, url="", **config):
    return feed(client, name=protocol, slug=protocol, direction="outbound", protocol=protocol, url=url, config=config)


def publish(client, cid, ep):
    return client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)


def test_slack(client, providers):
    providers.reply("POST", "/api/chat.postMessage", (200, {}, {"ok": True, "channel": "C024BE91L", "ts": "1727880000.000100"}))
    ep = dest(client, "slack", bearer_token_env="GROWTHOS_SECRET_SLACK", channel="C024BE91L")
    r = publish(client, approved(client), ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "C024BE91L:1727880000.000100"
    req = providers.calls("POST", "/api/chat.postMessage")[0]
    assert req["headers"]["authorization"] == "Bearer xoxb-slack-bot-token" and req["json"]["channel"] == "C024BE91L"
    assert "&lt;fast&gt; &amp; safely" in req["json"]["text"]            # Slack control characters escaped
    # Slack reports failure inside a 200: it must not be recorded as sent.
    providers.reply("POST", "/api/chat.postMessage", (200, {}, {"ok": False, "error": "not_in_channel"}))
    r = publish(client, approved(client, title="Second"), ep)
    assert r.status_code == 502 and "not_in_channel" in r.json()["detail"] and "invite the bot" in r.json()["detail"]


def test_teams_adaptive_card(client, providers):
    providers.reply("POST", "/workflows/abc/triggers/manual/paths/invoke", (202, {}, {}))
    ep = dest(client, "teams", webhook_url_env="GROWTHOS_SECRET_TEAMS_URL")
    assert publish(client, approved(client), ep).status_code == 200
    req = providers.calls("POST", "/workflows/abc/triggers/manual/paths/invoke")[0]
    assert "sig=s3cret" in req["path"]
    att = req["json"]["attachments"][0]
    assert req["json"]["type"] == "message" and att["contentType"] == "application/vnd.microsoft.card.adaptive"
    card = att["content"]
    assert card["type"] == "AdaptiveCard" and card["body"][0]["text"] == "GrowthOS is live" and card["body"][1]["wrap"] is True
    assert card["actions"][0]["url"].startswith("https://parinita.example/growthos")
    assert "s3cret" not in json.dumps(client.get("/v1/feeds", headers=BOOT).json())   # the URL secret never sits in endpoint config


def test_discord_cannot_ping_everyone(client, providers):
    providers.reply("POST", "/api/webhooks/1/tok", (200, {}, {"id": "112233"}))
    ep = dest(client, "discord", webhook_url_env="GROWTHOS_SECRET_DISCORD_URL")
    r = publish(client, approved(client), ep)
    assert r.json()["provider_id"] == "112233"
    req = providers.calls("POST", "/api/webhooks/1/tok")[0]
    assert req["path"].endswith("?wait=true") and req["json"]["allowed_mentions"] == {"parse": []} and len(req["json"]["content"]) <= 2000


def test_telegram_and_token_never_leaks(client, providers):
    path = "/bot123456:telegram-bot-token/sendMessage"
    providers.reply("POST", path, (200, {}, {"ok": True, "result": {"message_id": 77}}))
    ep = dest(client, "telegram", bot_token_env="GROWTHOS_SECRET_TG", chat_id="@parinita_news")
    r = publish(client, approved(client), ep)
    assert r.json()["provider_id"] == "@parinita_news:77" and providers.calls("POST", path)[0]["json"]["chat_id"] == "@parinita_news"
    providers.reply("POST", path, (403, {}, {"ok": False, "description": "bot 123456:telegram-bot-token was kicked"}))
    r = publish(client, approved(client, title="Second"), ep)
    assert r.status_code == 502 and "telegram-bot-token" not in r.text
    assert r.json()["detail"] == "delivery failed: HTTP 403"


def test_wordpress_post_is_escaped_html(client, sink, lan):
    sink.reply("POST", "/wp-json/wp/v2/posts", (201, {}, {"id": 501, "link": "https://news.parinita.example/?p=501"}))
    ep = dest(client, "wordpress", url=sink.url, username="newsroom", app_password_env="GROWTHOS_SECRET_WP", classifications=["pr"], categories=[7])
    cid = approved(client, classification="pr", title="Parinita launches GrowthOS",
                   body="Parinita today announced GrowthOS.\n<script>alert(1)</script> is just text here.")
    r = publish(client, cid, ep)
    assert r.status_code == 200 and r.json()["provider_id"] == "https://news.parinita.example/?p=501" and r.json()["published"] is True
    req = sink.calls("POST", "/wp-json/wp/v2/posts")[0]
    assert req["headers"]["authorization"].startswith("Basic ")
    b = req["json"]
    assert b["status"] == "publish" and b["categories"] == [7] and b["title"] == "Parinita launches GrowthOS"
    assert b["content"].startswith("<p>Parinita today announced GrowthOS.</p>\n<p>&lt;script&gt;alert(1)&lt;/script&gt; is just text here.</p>")
    assert '<a href="https://parinita.example/growthos?utm_source=growthos&amp;' in b["content"]


def test_wordpress_draft_does_not_mark_the_release_sent(client, sink, lan):
    sink.reply("POST", "/wp-json/wp/v2/posts", (201, {}, {"id": 9, "link": "https://news.parinita.example/?p=9"}))
    ep = dest(client, "wordpress", url=sink.url, username="newsroom", app_password_env="GROWTHOS_SECRET_WP", status="draft", classifications=["pr"])
    cid = approved(client, classification="pr")
    assert publish(client, cid, ep).json()["published"] is False
    assert client.get(f"/v1/content/{cid}", headers=PUBLISHER).json()["state"] == "approved"


@pytest.mark.parametrize("protocol,url,config,needle", [
    ("slack", "", {"bearer_token_env": "GROWTHOS_SECRET_SLACK"}, "config.channel"),
    ("teams", "", {"webhook_url_env": "TEAMS_URL"}, "GROWTHOS_SECRET_"),
    ("discord", "", {}, "webhook_url_env"),
    ("telegram", "", {"bot_token_env": "GROWTHOS_SECRET_TG"}, "chat_id"),
    ("wordpress", "", {"username": "u", "app_password_env": "GROWTHOS_SECRET_WP"}, "requires a URL"),
    ("wordpress", "https://news.example", {"username": "u", "app_password_env": "GROWTHOS_SECRET_WP", "status": "live"}, "config.status"),
])
def test_bad_config_is_rejected_at_creation(client, protocol, url, config, needle):
    r = client.post("/v1/feeds", json={"name": "n", "slug": "s", "direction": "outbound", "protocol": protocol, "url": url, "config": config}, headers=BOOT)
    assert r.status_code == 422 and needle in r.json()["detail"], r.text


def test_new_adapters_are_gated_too(client, providers):
    ep = dest(client, "slack", bearer_token_env="GROWTHOS_SECRET_SLACK", channel="C1")
    blocked = make(client, classification="social", body="Customers love it.", claims=[])["id"]
    assert publish(client, blocked, ep).status_code == 409 and providers.requests == []
