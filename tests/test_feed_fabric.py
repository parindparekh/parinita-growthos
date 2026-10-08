"""Ingest, render and push."""
import hashlib
import hmac
import json
import xml.etree.ElementTree as ET

from app.config import settings
from app.db import SessionLocal
from app.models import FeedEndpoint
from app.worker import run_once
from tests.conftest import APPROVER, AUDITOR, BOOT, EDITOR, PUBLISHER, SRC, feed, make, run_pipeline

ATOM = "{http://www.w3.org/2005/Atom}"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"

RSS_IN = b"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>t</title>
<item><guid>g-1</guid><title>With guid</title><link>https://news.example.com/1</link><description>short</description><content:encoded>full body text</content:encoded></item>
<item><title>No guid or link</title><description>d</description><pubDate>Fri, 02 Oct 2026 10:00:00 +0000</pubDate></item>
</channel></rss>"""
ATOM_IN = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
<entry><id>urn:a:1</id><title>Atom one</title><link rel="self" href="https://x.example.com/self"/><link rel="alternate" href="https://x.example.com/post"/><summary>s</summary><updated>2026-10-02T00:00:00Z</updated></entry></feed>"""
BOMB = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;">]>
<rss version="2.0"><channel><title>&c;</title></channel></rss>"""


def approved_item(client, **kw):
    c = make(client, **kw)
    assert run_pipeline(client, c["id"])["state"] == "approved"
    return c["id"]


# ------------------------------------------------------------------------------ ingest
def test_ingest_dedupes_including_items_without_ids(client, sink, lan):
    sink.serve("/in.xml", RSS_IN)
    ep = feed(client, name="in", slug="in", direction="inbound", protocol="rss", url=sink.url + "/in.xml")
    first = client.post(f"/v1/feeds/{ep['id']}/sync", headers=BOOT).json()
    second = client.post(f"/v1/feeds/{ep['id']}/sync", headers=BOOT).json()
    assert first["count"] == 2 and second["count"] == 0  # v1.0 re-created the id-less item on every poll
    items = client.get("/v1/content", headers=EDITOR).json()
    assert {i["body"] for i in items} == {"full body text", "d"} and all(i["state"] == "draft" for i in items)


def test_overlong_feed_fields_are_truncated_not_fatal(client, sink, lan):
    # v1.0 on PostgreSQL: a 600-character title raised a database error that killed the worker process.
    sink.serve("/long.xml", b'<rss version="2.0"><channel><title>t</title><item><guid>a</guid><title>' + b"T" * 600
               + b"</title><description>" + b"d" * 3000 + b"</description></item></channel></rss>")
    ep = feed(client, name="long", slug="long", direction="inbound", protocol="rss", url=sink.url + "/long.xml")
    assert client.post(f"/v1/feeds/{ep['id']}/sync", headers=BOOT).json()["count"] == 1
    item = client.get("/v1/content", headers=EDITOR).json()[0]
    assert len(item["title"]) == 500 and len(item["summary"]) == 1000 and len(item["body"]) == 3000
    assert run_once() == {"synced": 0, "failed": 0}


def test_atom_ingest_prefers_alternate_link(client, sink, lan):
    sink.serve("/a.xml", ATOM_IN)
    ep = feed(client, name="a", slug="a", direction="inbound", protocol="atom", url=sink.url + "/a.xml")
    client.post(f"/v1/feeds/{ep['id']}/sync", headers=BOOT)
    assert client.get("/v1/content", headers=EDITOR).json()[0]["source"] == "https://x.example.com/post"


def test_jsonfeed_ingest(client, sink, lan):
    sink.serve("/f.json", json.dumps({"version": "https://jsonfeed.org/version/1.1", "title": "t",
                                      "items": [{"id": "1", "title": "J", "content_text": "body", "url": "https://j.example.com/1"}]}))
    ep = feed(client, name="j", slug="j", direction="inbound", protocol="jsonfeed", url=sink.url + "/f.json")
    assert client.post(f"/v1/feeds/{ep['id']}/sync", headers=BOOT).json()["count"] == 1


def test_entity_expansion_feed_is_rejected_and_recorded(client, sink, lan):
    sink.serve("/bomb.xml", BOMB)
    ep = feed(client, name="b", slug="b", direction="inbound", protocol="rss", url=sink.url + "/bomb.xml")
    assert client.post(f"/v1/feeds/{ep['id']}/sync", headers=BOOT).status_code == 400
    view = [e for e in client.get("/v1/feeds", headers=BOOT).json() if e["id"] == ep["id"]][0]
    assert view["last_status"] == "error" and "Entities" in view["last_error"]
    assert client.get("/v1/audit", headers=AUDITOR).json()[0]["decision"] == "failure"


def test_oversized_feed_is_rejected(client, sink, lan, monkeypatch):
    monkeypatch.setattr(settings, "max_feed_bytes", 1000)
    sink.serve("/big.xml", b"<rss>" + b"x" * 5000 + b"</rss>")
    ep = feed(client, name="big", slug="big", direction="inbound", protocol="rss", url=sink.url + "/big.xml")
    r = client.post(f"/v1/feeds/{ep['id']}/sync", headers=BOOT)
    assert r.status_code == 400 and "MAX_FEED_BYTES" in r.json()["detail"]


def test_ingest_to_loopback_is_blocked_by_default(client, sink):
    ep = feed(client, name="i", slug="i", direction="inbound", protocol="rss", url=sink.url + "/in.xml")
    r = client.post(f"/v1/feeds/{ep['id']}/sync", headers=BOOT)
    assert r.status_code == 400 and "non-public address" in r.json()["detail"] and sink.gets == []


def test_redirect_hops_are_revalidated(client, sink, lan, monkeypatch):
    monkeypatch.setattr(settings, "destination_allowlist", "127.0.0.1")
    sink.serve("/hop", b"", status=302, headers={"Location": "http://localhost:1/admin"})
    ep = feed(client, name="r", slug="r", direction="inbound", protocol="rss", url=sink.url + "/hop")
    r = client.post(f"/v1/feeds/{ep['id']}/sync", headers=BOOT)
    assert r.status_code == 400 and "DESTINATION_ALLOWLIST" in r.json()["detail"]


def test_worker_survives_a_failing_endpoint(client, sink, lan):
    sink.serve("/bomb.xml", BOMB)
    sink.serve("/in.xml", RSS_IN)
    feed(client, name="bad", slug="bad", direction="inbound", protocol="rss", url=sink.url + "/bomb.xml")
    feed(client, name="good", slug="good", direction="inbound", protocol="rss", url=sink.url + "/in.xml")
    assert run_once() == {"synced": 1, "failed": 1}
    assert run_once() == {"synced": 0, "failed": 0}  # both back off until their next poll window
    with SessionLocal() as db:
        assert {e.slug: e.last_status for e in db.query(FeedEndpoint).all()} == {"bad": "error", "good": "ok"}


# ------------------------------------------------------------------------------ render
def test_high_risk_content_never_leaks_into_default_feeds(client):
    # v1.0: every approved item, including investor material, appeared in every unauthenticated feed.
    inv = make(client, title="CONFIDENTIAL investor note", classification="investor")["id"]
    client.post(f"/v1/content/{inv}/approve", json={}, headers=APPROVER)
    approved_item(client, title="Public launch post")
    feed(client, name="Blog", slug="blog", direction="outbound", protocol="rss")
    feed(client, name="IR", slug="ir", direction="outbound", protocol="rss", config={"classifications": ["investor"]})
    blog, ir = client.get("/feeds/blog").text, client.get("/feeds/ir").text
    assert "Public launch post" in blog and "CONFIDENTIAL" not in blog
    assert "CONFIDENTIAL" in ir and "Public launch post" not in ir


def test_ingested_items_are_not_resyndicated_by_default(client, sink, lan):
    sink.serve("/in.xml", RSS_IN)
    ep = feed(client, name="in", slug="in", direction="inbound", protocol="rss", url=sink.url + "/in.xml")
    for cid in client.post(f"/v1/feeds/{ep['id']}/sync", headers=BOOT).json()["created"]:
        run_pipeline(client, cid)
    feed(client, name="Out", slug="out", direction="outbound", protocol="jsonfeed")
    feed(client, name="Mirror", slug="mirror", direction="outbound", protocol="jsonfeed", config={"include_ingested": True})
    assert client.get("/feeds/out").json()["items"] == []
    assert len(client.get("/feeds/mirror").json()["items"]) == 2


def test_inbound_and_disabled_endpoints_are_not_public(client):
    ep = feed(client, name="in", slug="in-only", direction="inbound", protocol="rss", url="https://news.example.com/rss")
    assert client.get("/feeds/in-only").status_code == 404
    out = feed(client, name="o", slug="o", direction="outbound", protocol="rss")
    assert client.get("/feeds/o").status_code == 200
    assert client.patch(f"/v1/feeds/{out['id']}", json={"enabled": False}, headers=BOOT).json()["enabled"] is False
    assert client.get("/feeds/o").status_code == 404
    assert "public_url" not in ep


def test_edited_item_is_withdrawn_from_feeds_until_regated(client):
    cid = approved_item(client, title="Stable title")
    feed(client, name="o", slug="o", direction="outbound", protocol="atom")
    assert "Stable title" in client.get("/feeds/o").text
    client.patch(f"/v1/content/{cid}", json={"body": "Now up 900% (unsourced)", "classification": "pr"}, headers=EDITOR)
    assert "Stable title" not in client.get("/feeds/o").text


def test_rss_and_atom_are_well_formed_and_complete(client):
    approved_item(client, title="Ampersand & <tags> \x0b control", body="Body with \x00 illegal chars & entities")
    feed(client, name="R & D", slug="rss", direction="outbound", protocol="rss")
    feed(client, name="A", slug="atom", direction="outbound", protocol="atom", config={"author": "Parinita Newsroom"})
    rss = ET.fromstring(client.get("/feeds/rss").text)  # raises if not well-formed
    ch = rss.find("channel")
    assert ch.findtext("title") == "R & D" and ch.find(ATOM + "link").attrib["rel"] == "self" and ch.findtext("lastBuildDate")
    assert ch.find("item").findtext("title") == "Ampersand & <tags>  control"
    atom = ET.fromstring(client.get("/feeds/atom").text)
    assert atom.tag == ATOM + "feed" and atom.find(ATOM + "author").findtext(ATOM + "name") == "Parinita Newsroom"
    entry = atom.find(ATOM + "entry")
    assert all(entry.find(ATOM + t) is not None for t in ("id", "title", "updated", "summary", "link"))


def test_podcast_feed_carries_only_episodes_with_directory_tags(client):
    approved_item(client, title="Just an article")
    approved_item(client, title="Episode 1", metadata={"audio_url": "https://cdn.example.com/e1.mp3", "audio_bytes": "big", "audio_duration": "12:30"})
    feed(client, name="Show", slug="pod", direction="outbound", protocol="podcast_rss",
         config={"image": "https://cdn.example.com/art.jpg", "owner_email": "pod@example.com", "category": "Technology"})
    r = client.get("/feeds/pod")
    assert r.status_code == 200  # v1.0 returned 500 on a non-numeric audio_bytes
    ch = ET.fromstring(r.text).find("channel")
    items = ch.findall("item")
    assert [i.findtext("title") for i in items] == ["Episode 1"]
    assert items[0].find("enclosure").attrib == {"url": "https://cdn.example.com/e1.mp3", "length": "0", "type": "audio/mpeg"}
    for tag in ("author", "explicit", "category", "image", "owner"):
        assert ch.find(ITUNES + tag) is not None, tag


def test_jsonfeed_has_no_dead_links(client):
    approved_item(client, title="No source")
    feed(client, name="J", slug="j", direction="outbound", protocol="jsonfeed")
    doc = client.get("/feeds/j").json()
    assert doc["version"].endswith("1.1") and doc["authors"] and "url" not in doc["items"][0]


# ------------------------------------------------------------------------------ push
def hook(client, sink, slug="hook", **config):
    return feed(client, name="Hook", slug=slug, direction="outbound", protocol="webhook", url=sink.url + "/hook", config=config)


def test_publish_is_gated_and_the_refusal_is_audited(client, sink, lan):
    cid = make(client, classification="pr", body="Revenue grew 40% last year.", claims=[])["id"]
    ep = hook(client, sink)
    r = client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)
    assert r.status_code == 409 and "Hallucination Gate" in r.json()["detail"] and sink.posts == []
    last = client.get(f"/v1/audit?content_id={cid}", headers=AUDITOR).json()[0]
    assert (last["action"], last["decision"], last["actor"]) == ("publish.push", "blocked", "Parinita GrowthOS Courier (run by pat)")


def test_publish_sends_signed_minimal_payload_once(client, sink, lan):
    cid = approved_item(client, claims=[{"text": "Routes governed content", "sources": SRC}])
    ep = hook(client, sink, bearer_token_env="GROWTHOS_SECRET_HOOK_TOKEN", signing_secret_env="GROWTHOS_SECRET_HOOK_SIGNING")
    first = client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER).json()
    again = client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER).json()
    assert first["duplicate"] is False and again["duplicate"] is True and again["delivery_id"] == first["delivery_id"]
    assert len(sink.posts) == 1  # v1.0 delivered twice
    p = sink.posts[0]
    assert p["headers"]["authorization"] == "Bearer hook-token-value" and p["headers"]["idempotency-key"] == first["delivery_id"]
    expected = hmac.new(b"hook-signing-secret", p["headers"]["x-growthos-timestamp"].encode() + b"." + p["raw"], hashlib.sha256).hexdigest()
    assert p["headers"]["x-growthos-signature"] == "sha256=" + expected
    # v1.0 pushed approval notes, internal metadata and agent scratch output to the destination.
    assert not {"approval", "state", "metadata", "derivatives", "created_by"} & set(p["json"])
    assert p["json"]["claims"][0]["sources"][0]["uri"] == SRC[0]["uri"]
    assert client.get(f"/v1/content/{cid}", headers=EDITOR).json()["state"] == "published"


def test_derivatives_are_opt_in_per_destination(client, sink, lan):
    cid = approved_item(client)
    ep = hook(client, sink, include_derivatives=True)
    client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)
    assert set(sink.posts[0]["json"]["derivatives"]) == {"signal", "media", "podcast", "amplify"}


def test_transient_failures_are_retried_with_one_idempotency_key(client, sink, lan):
    cid = approved_item(client)
    ep = hook(client, sink)
    sink.post_statuses = [503, 500]
    r = client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER).json()
    assert r["attempts"] == 3 and len({p["headers"]["idempotency-key"] for p in sink.posts}) == 1


def test_failed_delivery_is_visible_and_retryable(client, sink, lan):
    cid = approved_item(client)
    ep = hook(client, sink)
    sink.post_statuses = [500, 500, 500]
    r = client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)
    assert r.status_code == 502
    assert client.get(f"/v1/content/{cid}", headers=EDITOR).json()["state"] == "approved"  # never marked published
    d = client.get(f"/v1/content/{cid}/deliveries", headers=EDITOR).json()
    assert len(d) == 1 and d[0]["status"] == "failed" and d[0]["attempts"] == 3 and d[0]["response_code"] == 500
    assert client.get(f"/v1/audit?content_id={cid}", headers=AUDITOR).json()[0]["decision"] == "failure"
    ok = client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER).json()
    assert ok["status"] == "sent" and ok["delivery_id"] == d[0]["id"] and ok["attempts"] == 4


def test_redirects_are_not_followed_or_retried(client, sink, lan):
    cid = approved_item(client)
    ep = hook(client, sink)
    sink.post_statuses = [302]
    assert client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER).status_code == 502
    assert len(sink.posts) == 1


def test_push_to_loopback_is_blocked_by_default(client, sink):
    cid = approved_item(client)
    ep = hook(client, sink)
    r = client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)
    assert r.status_code == 400 and "non-public address" in r.json()["detail"] and sink.posts == []
    assert client.get(f"/v1/content/{cid}/deliveries", headers=EDITOR).json()[0]["status"] == "failed"


def test_destination_policy(client, sink, lan):
    inv = make(client, classification="investor")["id"]
    client.post(f"/v1/content/{inv}/approve", json={}, headers=APPROVER)
    general, ir = hook(client, sink, slug="general"), hook(client, sink, slug="ir", classifications=["investor"])
    r = client.post(f"/v1/content/{inv}/publish", json={"endpoint_id": general["id"]}, headers=PUBLISHER)
    assert r.status_code == 409 and "does not accept 'investor'" in r.json()["detail"]
    assert client.post(f"/v1/content/{inv}/publish", json={"endpoint_id": ir["id"]}, headers=PUBLISHER).status_code == 200
    client.patch(f"/v1/feeds/{ir['id']}", json={"enabled": False}, headers=BOOT)
    other = make(client, classification="investor", title="Second")["id"]
    client.post(f"/v1/content/{other}/approve", json={}, headers=APPROVER)
    assert client.post(f"/v1/content/{other}/publish", json={"endpoint_id": ir["id"]}, headers=PUBLISHER).status_code == 409
    rss = feed(client, name="r", slug="r", direction="outbound", protocol="rss")
    assert client.post(f"/v1/content/{other}/publish", json={"endpoint_id": rss["id"]}, headers=PUBLISHER).status_code == 400


def test_gate_rerun_keeps_published_state(client, sink, lan):
    cid = approved_item(client)
    ep = hook(client, sink)
    client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)
    client.post(f"/v1/content/{cid}/agents/run", json={"agent": "gate"}, headers=EDITOR)
    assert client.get(f"/v1/content/{cid}", headers=EDITOR).json()["state"] == "published"  # v1.0 regressed it to approved
