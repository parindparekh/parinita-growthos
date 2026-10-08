"""Approval binding, state machine, agents and audit chain."""
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError

import app.agents as agents_mod
from app.audit import _hash_v1, record_event, verify_chain
from app.db import SessionLocal, engine
from app.models import AuditEvent
from tests.conftest import APPROVER, AUDITOR, EDITOR, SRC, make, run_pipeline


def get(client, cid):
    return client.get(f"/v1/content/{cid}", headers=EDITOR).json()


def test_safe_content_reaches_approved(client):
    cid = make(client, classification="pr", cta_url="https://example.com/try")["id"]
    out = run_pipeline(client, cid)
    assert out["state"] == "approved" and out["results"]["gate"]["passed"]
    assert "utm_source=growthos" in get(client, cid)["cta_url"]


def test_edit_after_approval_invalidates_it(client):
    cid = make(client, classification="investor")["id"]
    assert client.post(f"/v1/content/{cid}/approve", json={}, headers=APPROVER).json()["state"] == "approved"
    r = client.patch(f"/v1/content/{cid}", json={"body": "Materially different wording."}, headers=EDITOR).json()
    assert r["state"] == "draft"
    g = client.get(f"/v1/content/{cid}/gate", headers=EDITOR).json()
    assert not g["passed"] and g["checks"]["approval_stale"]


def test_cta_rewrite_after_approval_invalidates_it(client):
    # v1.0: the Acquire agent could repoint an approved financial item at any URL and the approval still held.
    cid = make(client, classification="financial", cta_url="https://parinita.ai/x")["id"]
    run_pipeline(client, cid)
    client.post(f"/v1/content/{cid}/approve", json={}, headers=APPROVER)
    assert get(client, cid)["state"] == "approved"
    r = client.post(f"/v1/content/{cid}/agents/run", json={"agent": "acquire", "options": {"cta_url": "https://evil.example/phish"}}, headers=EDITOR)
    assert r.status_code == 200 and r.json()["changed"]
    assert get(client, cid)["state"] == "draft"
    assert not client.get(f"/v1/content/{cid}/gate", headers=EDITOR).json()["passed"]
    bad = client.post(f"/v1/content/{cid}/agents/run", json={"agent": "acquire", "options": {"cta_url": "javascript:alert(1)"}}, headers=EDITOR)
    assert bad.status_code == 400


def test_claims_can_be_attached_to_unblock(client):
    cid = make(client, classification="pr", body="We serve 42 states.", claims=[])["id"]
    assert run_pipeline(client, cid)["state"] == "blocked"
    client.patch(f"/v1/content/{cid}", json={"claims": [{"text": "Launch note: we serve 42 states", "sources": SRC}]}, headers=EDITOR)
    assert run_pipeline(client, cid)["state"] == "approved"


def test_approval_binds_to_recomputed_hash_not_stored_column(client):
    # Rows written by v1.0 carry a hash from a different scheme; approval must still bind correctly.
    cid = make(client, classification="investor")["id"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE content_items SET content_hash = 'legacy-hash' WHERE id = :i"), {"i": cid})
    r = client.post(f"/v1/content/{cid}/approve", json={}, headers=APPROVER).json()
    assert r["state"] == "approved" and r["content_hash"] != "legacy-hash" and r["gate"]["checks"]["human_approved"]


def test_revoke_blocks(client):
    cid = make(client, classification="legal")["id"]
    client.post(f"/v1/content/{cid}/approve", json={}, headers=APPROVER)
    assert client.post(f"/v1/content/{cid}/revoke", json={"note": "pulled"}, headers=APPROVER).json()["state"] == "blocked"
    assert not client.get(f"/v1/content/{cid}/gate", headers=EDITOR).json()["passed"]


def test_agent_history_is_bounded_and_versioned(client):
    cid = make(client)["id"]
    for _ in range(4):
        run_pipeline(client, cid)
    c = get(client, cid)
    hist = c["metadata"]["agent_history"]
    assert len(hist) == 8 and {h["derived_from_hash"] for h in hist} == {c["content_hash"]}


def test_content_hash_is_stable_across_agent_runs(client):
    c = make(client)
    run_pipeline(client, c["id"])
    assert get(client, c["id"])["content_hash"] == c["content_hash"]  # no CTA, so nothing governed changed


def test_list_filters_and_bounds(client):
    a = make(client, classification="pr", body="We serve 42 states.", claims=[])["id"]
    make(client)
    run_pipeline(client, a)
    assert [c["id"] for c in client.get("/v1/content?state=blocked", headers=EDITOR).json()] == [a]
    assert client.get("/v1/content?limit=0", headers=EDITOR).status_code == 422
    assert client.get("/v1/content?limit=-5", headers=EDITOR).status_code == 422


# ---------------------------------------------------------------- model output is untrusted
def _model(monkeypatch, payload):
    monkeypatch.setattr(agents_mod, "generate_json", lambda system, user, fallback: (payload, "model"))


def test_model_output_with_invented_facts_is_rejected(client, monkeypatch):
    cid = make(client, body="GrowthOS routes governed content to feed destinations.")["id"]
    _model(monkeypatch, {"posts": [{"channel": "x", "copy": "GrowthOS cuts costs 73% - the #1 platform! https://evil.example/x"}]})
    r = client.post(f"/v1/content/{cid}/agents/run", json={"agent": "amplify", "options": {"channels": ["x"]}}, headers=EDITOR).json()
    assert r["generation_mode"].startswith("deterministic-fallback")
    assert {"number:73%", "superlative:#1", "url:https://evil.example/x"} <= set(r["rejected_ungrounded"])
    assert "73%" not in json.dumps(r["derivatives"])


def test_grounded_model_output_is_accepted(client, monkeypatch):
    cid = make(client, body="GrowthOS routes governed content to feed destinations.")["id"]
    _model(monkeypatch, {"posts": [{"channel": "x", "copy": "Governed content, routed to every feed."}]})
    r = client.post(f"/v1/content/{cid}/agents/run", json={"agent": "amplify", "options": {"channels": ["x"]}}, headers=EDITOR).json()
    assert r["generation_mode"] == "model" and r["derivatives"][0]["copy"].startswith("Governed")


@pytest.mark.parametrize("payload", [["not", "a", "dict"], {"posts": "nope"}, {"posts": [{"channel": "myspace", "copy": "x"}]}, {}])
def test_malformed_model_output_falls_back_instead_of_500(client, monkeypatch, payload):
    cid = make(client)["id"]
    _model(monkeypatch, payload)
    r = client.post(f"/v1/content/{cid}/agents/run", json={"agent": "amplify", "options": {"channels": ["x"]}}, headers=EDITOR)
    assert r.status_code == 200 and r.json()["generation_mode"].startswith("deterministic-fallback")


# ---------------------------------------------------------------- audit chain
def test_audit_chain_verifies_and_records_actors(client):
    cid = make(client, classification="investor")["id"]
    run_pipeline(client, cid)
    client.post(f"/v1/content/{cid}/approve", json={}, headers=APPROVER)
    v = client.get("/v1/audit/verify", headers=AUDITOR).json()
    assert v["ok"] and v["events"] == 10 and len(v["head_hash"]) == 64
    events = client.get(f"/v1/audit?content_id={cid}", headers=AUDITOR).json()
    assert events[0]["action"] == "content.approve" and events[0]["actor"] == "ana"
    assert events[-1]["action"] == "content.create" and events[-1]["actor"] == "erin"
    assert all(e["ts"] for e in events)


def test_database_rejects_audit_mutation(client):
    make(client)
    for stmt in ("UPDATE audit_events SET actor = 'nobody'", "DELETE FROM audit_events"):
        with pytest.raises(DatabaseError, match="append-only"):
            with engine.begin() as conn:
                conn.execute(text(stmt))
    assert client.get("/v1/audit/verify", headers=AUDITOR).json()["ok"]


def test_verify_detects_tampering_when_triggers_are_removed(client):
    cid = make(client)["id"]
    run_pipeline(client, cid)
    with engine.begin() as conn:  # what a database superuser could do
        if conn.dialect.name == "postgresql":
            conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
        else:
            conn.execute(text("DROP TRIGGER growthos_audit_no_update"))
        conn.execute(text("UPDATE audit_events SET ts = '2020-01-01T00:00:00+00:00' WHERE seq = (SELECT MIN(seq) + 2 FROM audit_events)"))
    v = client.get("/v1/audit/verify", headers=AUDITOR).json()
    assert not v["ok"] and v["reason"] == "event content does not match its hash"


def test_chain_cannot_fork():
    with SessionLocal() as db:
        record_event(db, content_id=None, actor="a", action="x")
        db.commit()
        head = db.query(AuditEvent).order_by(AuditEvent.seq.desc()).first()
        db.add(AuditEvent(event_id="forged", actor="a", action="x", event_hash="f" * 64, prev_hash=head.prev_hash, ts="t"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_legacy_v1_rows_still_verify():
    with SessionLocal() as db:
        h1 = _hash_v1("e1", "c1", "api", "content.create", "", '{"type": "article"}', "")
        db.add(AuditEvent(event_id="e1", content_id="c1", actor="api", action="content.create", decision="",
                          details_json='{"type": "article"}', event_hash=h1, prev_hash="", hash_version=1))
        db.commit()
        record_event(db, content_id="c1", actor="erin", action="content.update")
        db.commit()
        assert verify_chain(db) == {"ok": True, "events": 2, "head_seq": 2, "head_hash": db.query(AuditEvent).order_by(AuditEvent.seq.desc()).first().event_hash}
