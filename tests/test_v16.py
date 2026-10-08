from datetime import datetime, timezone

from app.config import settings
from .conftest import APPROVER, AUDITOR, BOOT, EDITOR, PUBLISHER


def content(client, classification="general"):
    body = {
        "content_type": "pr_release", "title": "Parinita GrowthOS evidence release",
        "body": "Parinita GrowthOS links approved claims to supporting evidence.",
        "summary": "GrowthOS links claims to evidence.", "classification": classification,
        "source": "https://parinita.example/releases/evidence",
        "claims": [{"text": "Parinita GrowthOS links approved claims to supporting evidence.", "claim_type": "fact",
                    "sources": [{"uri": "https://evidence.example/source", "title": "Primary evidence"}]}]
    }
    r = client.post("/v1/content", json=body, headers=EDITOR); assert r.status_code == 201, r.text
    return r.json()


def approve(client, cid):
    r = client.post(f"/v1/content/{cid}/approve", json={}, headers=APPROVER); assert r.status_code == 200, r.text
    return r.json()


def test_pr_intelligence_import_and_target_ranking(client):
    for row in [
        {"provider":"licensed","external_id":"j1","name":"A. Reporter","outlet":"AI Daily","beat":"AI infrastructure enterprise software","influence_score":0.8},
        {"provider":"licensed","external_id":"j2","name":"B. Reporter","outlet":"Food Weekly","beat":"restaurants recipes dining","influence_score":0.9},
    ]:
        r=client.post("/v1/media/contacts",json=row,headers=EDITOR); assert r.status_code==201, r.text
    c=content(client)
    client.patch(f"/v1/content/{c['id']}", json={"title":"AI infrastructure enterprise software release","summary":"AI infrastructure enterprise software"}, headers=EDITOR)
    r=client.get(f"/v1/content/{c['id']}/media-targets",headers=EDITOR); assert r.status_code==200
    targets=r.json()["targets"]
    assert targets[0]["name"] == "A. Reporter"
    assert targets[0]["basis"]["topic_overlap"] > targets[1]["basis"]["topic_overlap"]
    pr=client.post(f"/v1/content/{c['id']}/agents/run",json={"agent":"pr","options":{}},headers=EDITOR)
    assert pr.status_code==200 and pr.json()["media_targets"][0]["name"] == "A. Reporter"


def test_opportunity_queue_fuses_media_aeo_inbox_and_performance(client):
    client.post("/v1/media/coverage",json={"provider":"licensed","external_id":"cov1","title":"GrowthOS governance gains attention",
                "url":"https://news.example/growthos","outlet":"News","author":"Reporter","topics":["growthos","governance"]},headers=EDITOR)
    client.post("/v1/engagement/inbox",json={"provider":"social","external_id":"m1","sender":"reporter@example.com",
                "body":"Urgent reporter interview request about the release."},headers=EDITOR)
    q=client.post("/v1/aeo/queries",json={"name":"governed comms","prompt":"Who offers governed communications?","brand":"Parinita"},headers=EDITOR).json()
    client.post("/v1/aeo/probes",json={"query_id":q["id"],"engine":"test","brand_mentioned":False,"response_text":"Other brands","citations":[]},headers=EDITOR)
    client.post("/v1/performance/events",json={"channel":"linkedin","metric":"impressions","value":2000},headers=EDITOR)
    client.post("/v1/performance/events",json={"channel":"linkedin","metric":"clicks","value":2},headers=EDITOR)
    r=client.post("/v1/opportunities/refresh?brand=Parinita&days=30",headers=EDITOR); assert r.status_code==200, r.text
    kinds={x["kind"] for x in r.json()["opportunities"]}
    assert {"earned-media","engagement","aeo","performance"} <= kinds


def test_claim_graph_connects_release_delivery_coverage_aeo_and_performance(client, sink, lan):
    c=content(client); approve(client,c["id"])
    ep=client.post("/v1/feeds",json={"name":"hook","slug":"cg-hook","direction":"outbound","protocol":"webhook",
        "url":sink.url+"/publish","channel":"web"},headers=BOOT).json()
    r=client.post(f"/v1/content/{c['id']}/publish",json={"endpoint_id":ep["id"]},headers=PUBLISHER); assert r.status_code==200, r.text
    cov=client.post("/v1/media/coverage",json={"provider":"licensed","external_id":"cov2","title":"GrowthOS links claims to evidence",
        "url":"https://news.example/proof","outlet":"News","author":"Reporter",
        "body":"Parinita GrowthOS links approved claims to supporting evidence.","content_id":c["id"]},headers=EDITOR)
    assert cov.status_code==201 and cov.json()["claim_observations"] >= 1
    client.post("/v1/aeo/probes",json={"engine":"test","prompt":"proof","brand":"Parinita","brand_mentioned":True,
        "response_text":"Parinita", "citations":["https://evidence.example/source"]},headers=EDITOR)
    client.post("/v1/performance/events",json={"content_id":c["id"],"channel":"web","metric":"views","value":100},headers=EDITOR)
    g=client.get(f"/v1/content/{c['id']}/claim-graph",headers=EDITOR); assert g.status_code==200, g.text
    types={n["type"] for n in g.json()["nodes"]}
    assert {"source","claim","release","delivery","earned-media","aeo-citation","performance"} <= types


def test_chrysalis_audit_and_release_receipts_are_stored(client, sink, lan, monkeypatch):
    monkeypatch.setattr(settings,"chrysalis_enabled",True)
    monkeypatch.setattr(settings,"chrysalis_anchor_url",sink.url+"/chrysalis")
    monkeypatch.setattr(settings,"chrysalis_bearer_token_env","")
    def dynamic(req):
        if req["path"] == "/chrysalis":
            return 200, {}, {"anchor_id":"chr-"+str(len(sink.posts)+1)}
    sink.dynamic=dynamic
    a=client.post("/v1/chrysalis/anchor/audit",headers=AUDITOR); assert a.status_code==200, a.text
    assert a.json()["status"]=="anchored" and a.json()["chrysalis_ref"].startswith("chr-")
    c=content(client); approve(client,c["id"])
    r=client.post(f"/v1/content/{c['id']}/chrysalis/attest",headers=AUDITOR); assert r.status_code==200, r.text
    assert r.json()["content_hash"] and r.json()["status"]=="anchored"


def test_high_risk_publish_fails_closed_without_chrysalis_receipt(client, sink, lan, monkeypatch):
    monkeypatch.setattr(settings,"chrysalis_enabled",True)
    monkeypatch.setattr(settings,"chrysalis_anchor_url",sink.url+"/chrysalis")
    monkeypatch.setattr(settings,"chrysalis_bearer_token_env","")
    monkeypatch.setattr(settings,"chrysalis_fail_closed_high_risk",True)
    sink.dynamic=lambda req: (500, {}, {"error":"down"}) if req["path"]=="/chrysalis" else None
    c=content(client,classification="investor"); approve(client,c["id"])
    ep=client.post("/v1/feeds",json={"name":"investor hook","slug":"investor-hook","direction":"outbound","protocol":"webhook",
        "url":sink.url+"/publish","channel":"investor","config":{"classifications":["investor"]}},headers=BOOT).json()
    r=client.post(f"/v1/content/{c['id']}/publish",json={"endpoint_id":ep["id"]},headers=PUBLISHER)
    assert r.status_code==409 and "Chrysalis" in r.text
    assert not sink.calls("POST","/publish")


def test_high_risk_publish_proceeds_after_chrysalis_attestation(client, sink, lan, monkeypatch):
    monkeypatch.setattr(settings,"chrysalis_enabled",True)
    monkeypatch.setattr(settings,"chrysalis_anchor_url",sink.url+"/chrysalis")
    monkeypatch.setattr(settings,"chrysalis_bearer_token_env","")
    monkeypatch.setattr(settings,"chrysalis_fail_closed_high_risk",True)
    def dynamic(req):
        if req["path"]=="/chrysalis": return 200, {}, {"anchor_id":"chr-release-1"}
        if req["path"]=="/publish": return 200, {}, {"ok":True}
    sink.dynamic=dynamic
    c=content(client,classification="investor"); approve(client,c["id"])
    ep=client.post("/v1/feeds",json={"name":"investor hook","slug":"investor-hook2","direction":"outbound","protocol":"webhook",
        "url":sink.url+"/publish","channel":"investor","config":{"classifications":["investor"]}},headers=BOOT).json()
    r=client.post(f"/v1/content/{c['id']}/publish",json={"endpoint_id":ep["id"]},headers=PUBLISHER); assert r.status_code==200, r.text
    assert r.json()["chrysalis_anchor"]=="chr-release-1"
    assert len(sink.calls("POST","/publish"))==1
