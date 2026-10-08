from datetime import datetime, timedelta, timezone

from .conftest import APPROVER, BOOT, EDITOR, PUBLISHER


def make_content(client, **overrides):
    body = {
        "content_type": "article",
        "title": "Parinita GrowthOS release",
        "body": "Parinita GrowthOS publishes a governed communications release.",
        "summary": "A governed communications release.",
        "classification": "general",
        "claims": [{
            "text": "Parinita GrowthOS publishes a governed communications release.",
            "claim_type": "fact",
            "sources": [{"uri": "https://example.com/evidence", "title": "Evidence"}],
        }],
    }
    body.update(overrides)
    r = client.post("/v1/content", json=body, headers=EDITOR)
    assert r.status_code == 201, r.text
    return r.json()


def approve(client, cid):
    r = client.post(f"/v1/content/{cid}/approve", json={}, headers=APPROVER)
    assert r.status_code == 200, r.text
    return r.json()


def test_agent_manifest_distinguishes_acting_and_transforming_agents(client):
    rows = client.get("/v1/agents", headers=EDITOR).json()
    assert rows["signal"]["mode"] == "acts"
    assert rows["social"]["mode"] == "acts"
    assert rows["performance"]["mode"] == "learns"
    assert rows["pr"]["mode"] == "transforms"
    assert rows["feed"]["can_publish"] is True
    assert all(not v["can_publish"] for k, v in rows.items() if k != "feed")


def test_signal_agent_monitors_inbound_corpus(client):
    for i in range(3):
        r = client.post("/v1/content", json={
            "content_type": "feed_item", "title": f"AI infrastructure expansion {i}",
            "body": "AI infrastructure demand is expanding.", "summary": "AI infrastructure demand expands.",
            "source": f"https://news.example/{i}"}, headers=EDITOR)
        assert r.status_code == 201
    r = client.get("/v1/agents/signal/monitor?hours=24&limit=10", headers=EDITOR)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["items_scanned"] == 3 and len(data["signals"]) == 3
    assert any("infrastructure" in s["repeated_keywords"] for s in data["signals"])


def test_claim_candidates_are_executable_not_readme_only(client):
    c = make_content(client, body="Revenue increased 20% in 2026.", claims=[])
    r = client.post(f"/v1/content/{c['id']}/claims/candidates", headers=EDITOR)
    assert r.status_code == 200
    candidates = r.json()["candidates"]
    assert candidates and "numeric" in candidates[0]["reasons"]


def test_social_agent_can_schedule_but_not_publish_itself(client):
    c = make_content(client)
    approve(client, c["id"])
    ep = client.post("/v1/feeds", json={
        "name": "future hook", "slug": "future-hook", "direction": "outbound", "protocol": "webhook",
        "url": "https://example.com/hook", "channel": "social"}, headers=BOOT)
    assert ep.status_code == 201, ep.text
    run_at = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    r = client.post(f"/v1/content/{c['id']}/schedule", json={"endpoint_id": ep.json()["id"], "run_at": run_at}, headers=PUBLISHER)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "scheduled"
    schedules = client.get("/v1/schedules?status=scheduled", headers=EDITOR).json()
    assert len(schedules) == 1 and schedules[0]["content_id"] == c["id"]


def test_social_agent_endpoint_requires_publisher_authority(client):
    c = make_content(client)
    approve(client, c["id"])
    ep = client.post("/v1/feeds", json={"name": "h", "slug": "h", "direction": "outbound", "protocol": "webhook",
                                              "url": "https://example.com/h"}, headers=BOOT).json()
    run_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    r = client.post(f"/v1/content/{c['id']}/schedule", json={"endpoint_id": ep["id"], "run_at": run_at}, headers=EDITOR)
    assert r.status_code == 403


def test_engagement_reads_normalized_inbox_and_triages(client):
    r = client.post("/v1/engagement/inbox", json={
        "provider": "social-webhook", "external_id": "m-1", "sender": "reporter@example.com",
        "body": "I am a reporter requesting an interview for a press story."}, headers=EDITOR)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["intent"] == "media" and data["state"] == "triaged"
    inbox = client.get("/v1/engagement/inbox", headers=EDITOR).json()
    assert inbox[0]["response_draft"] and inbox[0]["provider"] == "social-webhook"


def test_performance_feedback_loop_records_and_learns(client):
    c = make_content(client)
    for metric, value in [("impressions", 2000), ("clicks", 4), ("engagements", 20), ("conversions", 0)]:
        r = client.post("/v1/performance/events", json={"content_id": c["id"], "channel": "linkedin", "metric": metric, "value": value}, headers=EDITOR)
        assert r.status_code == 201, r.text
    s = client.get(f"/v1/performance?content_id={c['id']}", headers=EDITOR).json()
    assert s["totals"]["impressions"] == 2000 and s["derived"]["click_through_rate"] == 0.002
    learn = client.get(f"/v1/performance/learn?content_id={c['id']}", headers=EDITOR).json()
    assert any(a["action"] == "test-cta-or-opening-copy" for a in learn["actions"])


def test_aeo_public_claim_manifest_and_jsonld_are_gated(client):
    c = make_content(client)
    assert client.get(f"/aeo/claims/{c['id']}.json").status_code == 404
    approve(client, c["id"])
    m = client.get(f"/aeo/claims/{c['id']}.json")
    assert m.status_code == 200, m.text
    assert m.json()["schema"] == "parinita.growthos.claim-manifest.v1"
    assert m.json()["claims"][0]["sources"][0]["uri"] == "https://example.com/evidence"
    j = client.get(f"/aeo/content/{c['id']}.jsonld")
    assert j.status_code == 200 and j.json()["@context"] == "https://schema.org"


def test_aeo_observations_compute_visibility_and_citations(client):
    q = client.post("/v1/aeo/queries", json={"name": "category", "prompt": "Which communications platforms are governed?", "brand": "Parinita",
                                                       "engines": ["chatgpt", "gemini"]}, headers=EDITOR)
    assert q.status_code == 201
    qid = q.json()["id"]
    for engine, mentioned, urls in [
        ("chatgpt", True, ["https://news.example/story"]),
        ("gemini", False, ["https://competitor.example/page"]),
    ]:
        r = client.post("/v1/aeo/probes", json={"query_id": qid, "engine": engine, "brand_mentioned": mentioned,
                                                        "response_text": "Observed answer", "citations": urls}, headers=EDITOR)
        assert r.status_code == 201, r.text
    v = client.get("/v1/aeo/visibility?brand=Parinita&days=30", headers=EDITOR).json()
    assert v["probes"] == 2 and v["mentions"] == 1 and v["visibility_rate"] == 0.5
    assert {x["domain"] for x in v["top_citation_domains"]} == {"news.example", "competitor.example"}


def test_aeo_agent_does_not_export_unapproved_evidence(client):
    c = make_content(client)
    r = client.post(f"/v1/content/{c['id']}/agents/run", json={"agent": "aeo", "options": {}}, headers=EDITOR)
    assert r.status_code == 200 and r.json()["status"] == "pending-gate"


def test_performance_agent_works_on_recorded_data(client):
    c = make_content(client)
    client.post("/v1/performance/events", json={"content_id": c["id"], "channel": "x", "metric": "views", "value": 100}, headers=EDITOR)
    r = client.post(f"/v1/content/{c['id']}/agents/run", json={"agent": "performance", "options": {"days": 30}}, headers=EDITOR)
    assert r.status_code == 200 and r.json()["summary"]["events"] == 1


def test_pr_social_engagement_agents_are_explicit_and_nonpublishing(client):
    c = make_content(client)
    for agent in ("pr", "social", "engagement"):
        r = client.post(f"/v1/content/{c['id']}/agents/run", json={"agent": agent, "options": {}}, headers=EDITOR)
        assert r.status_code == 200, (agent, r.text)
    assert client.get("/v1/agents", headers=EDITOR).json()["social"]["can_publish"] is False


def test_rate_limiter_enforces_window_when_enabled(monkeypatch):
    from app import rate_limit
    from app.config import settings
    rate_limit._buckets.clear()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    ok1, _ = rate_limit._allowed("unit-test", 2)
    ok2, _ = rate_limit._allowed("unit-test", 2)
    ok3, retry = rate_limit._allowed("unit-test", 2)
    assert ok1 and ok2 and not ok3 and retry >= 1


def test_aeo_can_run_configured_live_rest_probe(client, sink, lan):
    def dynamic(req):
        if req["path"] == "/answer":
            assert req["json"]["question"] == "Who provides governed communications?"
            return 200, {}, {"result": {"text": "Parinita provides governed communications.",
                                        "sources": [{"url": "https://news.example/proof"}]}}
    sink.dynamic = dynamic
    r = client.post("/v1/aeo/probes/run", json={
        "engine": "test-engine", "url": sink.url + "/answer",
        "prompt": "Who provides governed communications?", "brand": "Parinita",
        "prompt_field": "question", "answer_path": "result.text", "citations_path": "result.sources"
    }, headers=EDITOR)
    assert r.status_code == 201, r.text
    assert r.json()["brand_mentioned"] is True
    assert r.json()["citations"] == ["https://news.example/proof"]
