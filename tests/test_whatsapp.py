"""WhatsApp Cloud API adapter against a local mock of the documented Messages endpoint (contract test)."""
import json

import pytest

from app.config import settings
from tests.conftest import BOOT, EDITOR, PUBLISHER, feed, make, run_pipeline

PATH = "/v25.0/106540352242922/messages"
OK = (200, {}, {"messaging_product": "whatsapp", "contacts": [{"wa_id": "x"}], "messages": [{"id": "wamid.HBgL"}]})


@pytest.fixture()
def wa(monkeypatch, sink, lan):
    monkeypatch.setattr(settings, "provider_base_overrides", json.dumps({"whatsapp": sink.url}))
    return sink


def dest(client, **over):
    cfg = {"phone_number_id": "106540352242922", "bearer_token_env": "GROWTHOS_SECRET_WA_TOKEN", "recipients_env": "GROWTHOS_SECRET_WA_LIST",
           "template": "release_announcement", "language": "en_US", "body_parameters": ["title", "summary", "cta_url"], **over}
    return feed(client, name="WhatsApp press list", slug="whatsapp", direction="outbound", protocol="whatsapp", config=cfg)


def approved(client, **kw):
    kw.setdefault("classification", "pr")
    kw.setdefault("title", "Parinita launches GrowthOS")
    kw.setdefault("summary", "A control plane\nfor governed     releases.")
    kw.setdefault("body", "Parinita today announced GrowthOS.")
    kw.setdefault("cta_url", "https://parinita.example/g")
    c = make(client, **kw)
    assert run_pipeline(client, c["id"])["state"] == "approved"
    return c["id"]


def publish(client, cid, ep):
    return client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)


def test_template_message_goes_to_every_recipient(client, wa):
    wa.reply("POST", PATH, OK)
    r = publish(client, approved(client), dest(client))
    assert r.status_code == 200 and r.json()["provider_id"] == "sent:3" and "3 recipient(s)" in r.json()["detail"]
    calls = wa.calls("POST", PATH)
    assert [c["json"]["to"] for c in calls] == ["15551230001", "15551230002", "15551230003"]
    b = calls[0]["json"]
    assert calls[0]["headers"]["authorization"] == "Bearer wa-system-user-token"
    assert b["messaging_product"] == "whatsapp" and b["type"] == "template" and b["recipient_type"] == "individual"
    assert b["template"]["name"] == "release_announcement" and b["template"]["language"] == {"code": "en_US"}
    params = b["template"]["components"][0]["parameters"]
    assert b["template"]["components"][0]["type"] == "body" and [p["type"] for p in params] == ["text"] * 3
    # Template variables may not contain newlines or runs of spaces; the link is intact.
    assert [p["text"] for p in params] == ["Parinita launches GrowthOS", "A control plane for governed releases.",
                                           "https://parinita.example/g?utm_source=growthos&utm_medium=content&utm_campaign=always-on"]
    assert "text" not in b                                    # never free-form text: only approved templates start a conversation


def test_partial_failure_resumes_without_messaging_anyone_twice(client, wa):
    err = {"error": {"message": "(#131026) Message undeliverable to 15551230002", "type": "OAuthException", "code": 131026}}
    wa.reply("POST", PATH, OK, (400, {}, err), OK, OK)       # recipient 2 fails once
    cid, ep = approved(client), dest(client)
    r = publish(client, cid, ep)
    assert r.status_code == 502 and "recipient 2 of 3" in r.json()["detail"] and "cannot receive this message" in r.json()["detail"]
    assert "15551230002" not in r.text                        # phone numbers never land in errors or the delivery record
    d = client.get(f"/v1/content/{cid}/deliveries", headers=EDITOR).json()[0]
    assert d["status"] == "failed" and d["provider_id"] == "sent:1" and "15551230002" not in json.dumps(d)
    assert client.get(f"/v1/content/{cid}", headers=EDITOR).json()["state"] == "approved"
    r = publish(client, cid, ep)                              # send again: continues with recipient 2
    assert r.status_code == 200 and r.json()["provider_id"] == "sent:3"
    assert [c["json"]["to"] for c in wa.calls("POST", PATH)] == ["15551230001", "15551230002", "15551230002", "15551230003"]
    assert publish(client, cid, ep).json()["duplicate"] is True and len(wa.calls("POST", PATH)) == 4


def test_gate_recipient_cap_and_config_validation(client, wa, monkeypatch):
    ep = dest(client)
    blocked = make(client, classification="pr", body="Customers love it.", claims=[])["id"]
    assert publish(client, blocked, ep).status_code == 409 and wa.requests == []
    monkeypatch.setenv("GROWTHOS_SECRET_WA_LIST", ",".join(str(15550000000 + i) for i in range(101)))
    r = publish(client, approved(client), ep)
    assert r.status_code == 400 and "at most 100" in r.json()["detail"] and wa.requests == []
    assert "15551230001" not in json.dumps(client.get("/v1/feeds", headers=BOOT).json())      # recipients are not in endpoint config
    base = {"name": "n", "slug": "w2", "direction": "outbound", "protocol": "whatsapp"}
    good = {"phone_number_id": "1", "bearer_token_env": "GROWTHOS_SECRET_WA_TOKEN", "recipients_env": "GROWTHOS_SECRET_WA_LIST", "template": "t"}
    for bad, needle in [({"phone_number_id": "+1 555"}, "phone_number_id"), ({"template": "Has Spaces"}, "config.template"),
                        ({"body_parameters": ["body_html"]}, "body_parameters"), ({"recipients_env": "PHONES"}, "GROWTHOS_SECRET_"),
                        ({"api_version": "latest"}, "api_version"), ({"recipients_env": ""}, "recipients_env")]:
        r = client.post("/v1/feeds", json={**base, "config": {**good, **bad}}, headers=BOOT)
        assert r.status_code == 422 and needle in r.json()["detail"], r.text


def test_group_recipients_and_no_parameters(client, wa, monkeypatch):
    monkeypatch.setenv("GROWTHOS_SECRET_WA_LIST", "120363000000000000")
    wa.reply("POST", PATH, OK)
    ep = dest(client, recipient_type="group", body_parameters=[])
    assert publish(client, approved(client), ep).status_code == 200
    b = wa.calls("POST", PATH)[0]["json"]
    assert b["recipient_type"] == "group" and b["to"] == "120363000000000000" and "components" not in b["template"]
