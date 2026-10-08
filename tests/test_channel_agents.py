"""v1.7 channel agents: channel-native copy, drift rejection, destination readiness, and the authority rule."""
import json

import app.agents as agents_mod
from app.agents import AGENT_MANIFEST
from app.channel_agents import CHANNEL_AGENTS, FAMILIES
from app.adapters import REGISTRY
from tests.conftest import AUDITOR, BOOT, EDITOR, PUBLISHER, feed, make, run_pipeline

BODY = "GrowthOS routes governed content (PR, social, podcast) to every feed destination."


def run(client, cid, agent, **options):
    r = client.post(f"/v1/content/{cid}/agents/run", json={"agent": agent, "options": options}, headers=EDITOR)
    assert r.status_code == 200, r.text
    return r.json()


def test_every_family_protocol_has_an_adapter_and_no_channel_agent_can_publish(client):
    for name, fam in FAMILIES.items():
        assert set(fam["protocols"]) <= set(REGISTRY), name
        assert AGENT_MANIFEST[name]["can_publish"] is False
    assert AGENT_MANIFEST["channels"]["can_publish"] is False
    assert [a for a, m in AGENT_MANIFEST.items() if m["can_publish"]] == ["feed"]
    names = {t["name"] for t in client.get("/v1/agents", headers=EDITOR).json().values()}
    assert "Parinita GrowthOS Ripple / Forums" in names and "Parinita GrowthOS Magnet / Etsy" in names


def test_channel_agent_writes_deterministic_copy_and_reports_readiness(client):
    cid = make(client, classification="social", title="GrowthOS is live", body=BODY, cta_url="https://parinita.example/growthos")["id"]
    ok = feed(client, name="r/parinita", slug="r-parinita", direction="outbound", protocol="reddit",
              config={"subreddit": "parinita", "client_id": "abcDEF123456", "client_secret_env": "GROWTHOS_SECRET_X_CK", "refresh_token_env": "GROWTHOS_SECRET_X_CS"})
    pr_only = feed(client, name="r/press", slug="r-press", direction="outbound", protocol="reddit",
                   config={"subreddit": "press", "client_id": "abcDEF123456", "client_secret_env": "GROWTHOS_SECRET_X_CK", "refresh_token_env": "GROWTHOS_SECRET_X_CS", "classifications": ["pr"]})
    r = run(client, cid, "reddit")
    assert r["generation_mode"] == "deterministic" and set(r["copy"]) == {"reddit", "lemmy"}
    assert r["copy"]["reddit"].startswith("GrowthOS is live") and "parinita.example/growthos" in r["copy"]["reddit"]
    by_slug = {d["slug"]: d for d in r["destinations"]}
    assert by_slug["r-press"]["status"] == "not-ready" and "does not accept 'social'" in by_slug["r-press"]["reasons"][0]
    assert by_slug["r-parinita"]["status"] == "ready"  # Gate passes already: the evidence is attached
    assert run_pipeline(client, cid)["state"] == "approved"
    r = run(client, cid, "reddit")
    assert {d["slug"]: d["status"] for d in r["destinations"]} == {"r-parinita": "ready", "r-press": "not-ready"}
    # The copy is recorded under the agent and surfaces as channel_copy for the adapters.
    item = client.get(f"/v1/content/{cid}", headers=EDITOR).json()
    hist = {h["agent"]: h for h in item["metadata"]["agent_history"]}
    assert hist["reddit"]["derived_from_hash"] == item["content_hash"]
    from app.content import public_projection
    from app.db import SessionLocal
    from app.models import ContentItem
    with SessionLocal() as db:
        proj = public_projection(db.get(ContentItem, cid))
    assert proj["channel_copy"]["reddit"] == r["copy"]["reddit"] and proj["channel_copy"]["lemmy"] == r["copy"]["lemmy"]
    assert ok["id"] and pr_only["id"]


def test_image_networks_report_missing_asset(client):
    cid = make(client, classification="social", title="GrowthOS is live", body=BODY)["id"]
    run_pipeline(client, cid)
    feed(client, name="ig", slug="ig", direction="outbound", protocol="instagram", config={"ig_user_id": "17841", "access_token_env": "GROWTHOS_SECRET_X_CK"})
    r = run(client, cid, "instagram")
    assert r["asset_requirement"] and r["destinations"][0]["status"] == "not-ready" and "image_url" in r["destinations"][0]["reasons"][0]
    assert "Link in bio" not in r["copy"]["instagram"]  # no CTA on this release, so no bio line
    client.patch(f"/v1/content/{cid}", json={"metadata": {"public": {"image_url": "https://cdn.parinita.example/launch.jpg"}}}, headers=EDITOR)
    run_pipeline(client, cid)
    assert run(client, cid, "instagram")["destinations"][0]["status"] == "ready"


def test_model_copy_that_drifts_is_replaced_per_protocol(client, monkeypatch):
    cid = make(client, classification="social", title="GrowthOS is live", body=BODY, cta_url="https://parinita.example/growthos")["id"]
    monkeypatch.setattr(agents_mod, "generate_json", lambda s, u, f: ({"copy": {
        "facebook": "GrowthOS is live: governed content routed to every destination. https://parinita.example/growthos"}}, "model"))
    # agents.generate_json is patched for the legacy agents; channel_agents has its own import.
    import app.channel_agents as ca
    monkeypatch.setattr(ca, "generate_json", lambda s, u, f: ({"copy": {
        "facebook": "GrowthOS is live, trusted by 900 enterprises and rated #1 by analysts."}}, "model"))
    r = run(client, cid, "facebook")
    assert r["generation_mode"].startswith("model (partial")
    assert any(x.startswith("facebook:number:900") for x in r["rejected_ungrounded"]) and any("superlative" in x for x in r["rejected_ungrounded"])
    assert r["copy"]["facebook"].startswith("GrowthOS is live")  # deterministic copy kept
    monkeypatch.setattr(ca, "generate_json", lambda s, u, f: ({"copy": {"facebook": "GrowthOS is live. Governed content, routed to every destination."}}, "model"))
    r = run(client, cid, "facebook")
    assert r["generation_mode"] == "model" and r["copy"]["facebook"].startswith("GrowthOS is live. Governed")


def test_channels_orchestrator_runs_only_configured_families(client):
    cid = make(client, classification="social", title="GrowthOS is live", body=BODY)["id"]
    run_pipeline(client, cid)
    feed(client, name="etsy", slug="etsy", direction="outbound", protocol="etsy", config={"shop_id": "1", "keystring": "k", "bearer_token_env": "GROWTHOS_SECRET_X_CK"})
    feed(client, name="slack", slug="slack", direction="outbound", protocol="slack", config={"bearer_token_env": "GROWTHOS_SECRET_SLACK", "channel": "#news"})
    r = run(client, cid, "channels")
    assert set(r["ran"]) == {"etsy", "community"} and "reddit" in r["skipped"]
    assert r["readiness"]["ready"] == 2
    hist = {h["agent"] for h in client.get(f"/v1/content/{cid}", headers=EDITOR).json()["metadata"]["agent_history"]}
    assert {"etsy", "community", "channels"} <= hist
    ev = [e for e in client.get(f"/v1/audit?content_id={cid}", headers=AUDITOR).json() if e["action"] == "agent.run"]
    assert any(e["actor"].startswith("Parinita GrowthOS Cadence") for e in ev)
    assert set(run(client, cid, "channels", all=True)["ran"]) == set(CHANNEL_AGENTS)


def test_channel_agent_copy_reaches_the_adapter(client, sink, lan, monkeypatch):
    import app.channel_agents as ca
    monkeypatch.setattr(ca, "generate_json", lambda s, u, f: ({"copy": {"slack": "GrowthOS is live. Governed content for every destination."}}, "model"))
    cid = make(client, classification="social", title="GrowthOS is live", body=BODY)["id"]
    run_pipeline(client, cid)
    run(client, cid, "community", protocols=["slack"])
    from app.config import settings
    monkeypatch.setattr(settings, "provider_base_overrides", json.dumps({"slack": sink.url}))
    sink.reply("POST", "/api/chat.postMessage", (200, {}, {"ok": True, "channel": "C1", "ts": "1.2"}))
    ep = feed(client, name="slack", slug="slack", direction="outbound", protocol="slack", config={"bearer_token_env": "GROWTHOS_SECRET_SLACK", "channel": "#news"})
    r = client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)
    assert r.status_code == 200, r.text
    assert sink.calls("POST", "/api/chat.postMessage")[0]["json"]["text"] == "GrowthOS is live. Governed content for every destination."


def test_mcp_exposes_no_channel_send_and_agents_cannot_approve(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=BOOT)
    names = [t["name"] for t in r.json()["result"]["tools"]]
    assert "send_release" in names and not any("approve" in n or "waive" in n for n in names)
