"""v1.6.1 hardening regressions. Each test pins one finding from the v1.6.0 review."""
import base64
import hashlib
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.config import settings
from .conftest import APPROVER, AUDITOR, BOOT, EDITOR, PUBLISHER


def _content(client, classification="general", body=None):
    payload = {
        "content_type": "pr_release", "title": "Parinita GrowthOS evidence release",
        "body": body or "Parinita GrowthOS links approved claims to supporting evidence.",
        "summary": "GrowthOS links claims to evidence.", "classification": classification,
        "source": "https://parinita.example/releases/evidence",
        "claims": [{"text": "Parinita GrowthOS links approved claims to supporting evidence.", "claim_type": "fact",
                    "sources": [{"uri": "https://evidence.example/source", "title": "Primary evidence"}]}]}
    r = client.post("/v1/content", json=payload, headers=EDITOR); assert r.status_code == 201, r.text
    return r.json()


def _ledger(client, cid):
    return {s["text"]: s for s in client.get(f"/v1/content/{cid}/assertions", headers=EDITOR).json()["sentences"]}


# ------------------------------------------------------------------------------ 1. AEO probe secret exfiltration
def test_aeo_probe_cannot_carry_non_aeo_secrets(client, sink, lan, monkeypatch):
    monkeypatch.setenv("GROWTHOS_SECRET_CHRYSALIS_TOKEN", "chrysalis-bearer-must-not-leak")
    monkeypatch.setenv("GROWTHOS_SECRET_AEO_ENGINE", "aeo-token-may-be-used")
    sink.dynamic = lambda req: (200, {}, {"answer": "Parinita", "citations": []}) if req["path"] == "/answer" else None
    base = {"engine": "t", "url": sink.url + "/answer", "prompt": "who?", "brand": "Parinita"}
    # An editor pointing a probe at a host of their choosing must not be able to attach the Chrysalis (or any provider) token.
    r = client.post("/v1/aeo/probes/run", json={**base, "bearer_token_env": "GROWTHOS_SECRET_CHRYSALIS_TOKEN"}, headers=EDITOR)
    assert r.status_code == 400 and "GROWTHOS_SECRET_AEO_" in r.json()["detail"]
    assert not any("chrysalis-bearer" in (q["headers"].get("authorization") or "") for q in sink.requests)
    # Secrets in the AEO namespace still work.
    r = client.post("/v1/aeo/probes/run", json={**base, "bearer_token_env": "GROWTHOS_SECRET_AEO_ENGINE"}, headers=EDITOR)
    assert r.status_code == 201, r.text
    assert sink.requests[-1]["headers"]["authorization"] == "Bearer aeo-token-may-be-used"


# ------------------------------------------------------------------------------ 2. rate limiter: key spraying + memory bound
def test_rate_limiter_counts_unknown_credentials_against_the_source_address(monkeypatch):
    from starlette.requests import Request
    from app import rate_limit
    rate_limit._buckets.clear()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1000)
    monkeypatch.setattr(settings, "rate_limit_per_ip_per_minute", 3)

    def req(key):
        scope = {"type": "http", "method": "GET", "path": "/v1/whoami", "query_string": b"", "headers": [(b"x-api-key", key.encode())],
                 "client": ("203.0.113.9", 1234), "scheme": "http", "server": ("h", 80)}
        return Request(scope)
    # Four different (guessed) keys from one address: the 4th is refused even though each key has a fresh credential bucket.
    results = [rate_limit.check(req(f"guess-{i}"))[0] for i in range(4)]
    assert results == [True, True, True, False]


def test_rate_limiter_bucket_table_is_bounded(monkeypatch):
    from app import rate_limit
    rate_limit._buckets.clear()
    monkeypatch.setattr(settings, "rate_limit_max_buckets", 100)
    for i in range(500):
        rate_limit._allowed(f"cred:{i}", 10)
    assert len(rate_limit._buckets) <= 100
    assert "cred:499" in rate_limit._buckets and "cred:0" not in rate_limit._buckets  # least recently seen evicted


# ------------------------------------------------------------------------------ 3. Chrysalis receipt verification
def _chrysalis(monkeypatch, sink, **extra):
    monkeypatch.setattr(settings, "chrysalis_enabled", True)
    monkeypatch.setattr(settings, "chrysalis_anchor_url", sink.url + "/chrysalis")
    monkeypatch.setattr(settings, "chrysalis_bearer_token_env", "")
    for k, v in extra.items():
        monkeypatch.setattr(settings, k, v)


def test_chrysalis_receipt_with_wrong_digest_is_rejected(client, sink, lan, monkeypatch):
    _chrysalis(monkeypatch, sink)
    sink.dynamic = lambda req: (200, {}, {"anchor_id": "chr-1", "payload_hash": "0" * 64}) if req["path"] == "/chrysalis" else None
    r = client.post("/v1/chrysalis/anchor/audit", headers=AUDITOR)
    assert r.status_code == 200 and r.json()["status"] == "failed" and "digest" in r.json()["error"]


def test_chrysalis_receipt_digest_can_be_required(client, sink, lan, monkeypatch):
    _chrysalis(monkeypatch, sink, chrysalis_require_receipt_digest=True)
    sink.dynamic = lambda req: (200, {}, {"anchor_id": "chr-1"}) if req["path"] == "/chrysalis" else None
    r = client.post("/v1/chrysalis/anchor/audit", headers=AUDITOR)
    assert r.json()["status"] == "failed" and "did not echo" in r.json()["error"]

    def echo(req):
        if req["path"] == "/chrysalis":
            return 200, {}, {"anchor_id": "chr-2", "payload_hash": hashlib.sha256(req["raw"]).hexdigest()}
    sink.dynamic = echo
    r = client.post("/v1/chrysalis/anchor/audit", headers=AUDITOR)
    assert r.json()["status"] == "anchored" and r.json()["receipt"]["_growthos_verification"]["digest_verified"] is True


def test_chrysalis_receipt_signature_is_verified_when_key_configured(client, sink, lan, monkeypatch):
    priv = ed25519.Ed25519PrivateKey.generate()
    pem = priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    _chrysalis(monkeypatch, sink, chrysalis_receipt_verify_key=pem)

    def signed(req, tamper=False):
        if req["path"] != "/chrysalis":
            return None
        receipt = {"anchor_id": "chr-signed", "payload_hash": hashlib.sha256(req["raw"]).hexdigest(), "ledger": "chrysalis-v6"}
        body = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        sig = base64.b64encode(priv.sign(body)).decode()
        if tamper:
            receipt["ledger"] = "someone-else"
        return 200, {}, {**receipt, "signature": sig}

    sink.dynamic = lambda req: signed(req)
    r = client.post("/v1/chrysalis/anchor/audit", headers=AUDITOR)
    assert r.status_code == 200 and r.json()["status"] == "anchored", r.text
    assert r.json()["receipt"]["_growthos_verification"]["signature_verified"] is True

    # Unsigned receipt -> refused.
    sink.dynamic = lambda req: (200, {}, {"anchor_id": "chr-unsigned"}) if req["path"] == "/chrysalis" else None
    c = _content(client); client.post(f"/v1/content/{c['id']}/approve", json={}, headers=APPROVER)
    r = client.post(f"/v1/content/{c['id']}/chrysalis/attest", headers=AUDITOR)
    assert r.json()["status"] == "failed" and "not signed" in r.json()["error"]

    # Tampered receipt -> refused, and a fail-closed high-risk publish stays closed with no provider side effect.
    sink.dynamic = lambda req: signed(req, tamper=True) if req["path"] == "/chrysalis" else (200, {}, {"ok": True})
    hi = _content(client, classification="investor"); client.post(f"/v1/content/{hi['id']}/approve", json={}, headers=APPROVER)
    ep = client.post("/v1/feeds", json={"name": "inv", "slug": "inv-sig", "direction": "outbound", "protocol": "webhook",
                                       "url": sink.url + "/publish", "channel": "investor", "config": {"classifications": ["investor"]}}, headers=BOOT).json()
    r = client.post(f"/v1/content/{hi['id']}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)
    assert r.status_code == 409 and "Chrysalis" in r.text
    assert not sink.calls("POST", "/publish")
    anchors = client.get("/v1/chrysalis/status", headers=AUDITOR).json()["latest"]
    assert anchors["status"] == "failed" and "signature" in anchors["error"]


def test_unusable_receipt_key_is_a_startup_error():
    from app.config import ConfigError, Settings
    s = Settings(api_key="bootstrap-key-for-tests-0000000001", chrysalis_receipt_verify_key="-----BEGIN PUBLIC KEY-----\nnope\n-----END PUBLIC KEY-----")
    with pytest.raises(ConfigError):
        s.validate_runtime()


def test_chrysalis_attest_route_does_not_echo_transport_detail(client, sink, lan, monkeypatch):
    _chrysalis(monkeypatch, sink)
    monkeypatch.setattr(settings, "chrysalis_anchor_url", "http://127.0.0.1:1/chrysalis")  # nothing listens here
    c = _content(client); client.post(f"/v1/content/{c['id']}/approve", json={}, headers=APPROVER)
    r = client.post(f"/v1/content/{c['id']}/chrysalis/attest", headers=AUDITOR)
    assert r.status_code == 200 and r.json()["status"] == "failed"  # the failure is recorded, not raised
    # Gate refusals are still explained.
    d = _content(client, classification="pr", body="Unsourced number 42% here.")
    r = client.post(f"/v1/content/{d['id']}/chrysalis/attest", headers=AUDITOR)
    assert r.status_code == 409 and "Gate" in r.json()["detail"]


# ------------------------------------------------------------------------------ 4. approval binds reviewer dispositions
def test_editor_waiver_after_approval_cannot_release_high_risk_content(client, monkeypatch):
    """GATE_WAIVER_ROLE=editor: an approved-but-blocked investor release must not become releasable because an
    editor (not an approver) waived the open sentences after the approval was recorded."""
    monkeypatch.setattr(settings, "gate_waiver_role", "editor")
    c = _content(client, classification="investor", body="Demand remains healthy.")
    assert client.post(f"/v1/content/{c['id']}/approve", json={}, headers=APPROVER).json()["state"] == "blocked"
    for row in _ledger(client, c["id"]).values():
        if row["status"] == "open":
            assert client.put(f"/v1/content/{c['id']}/assertions/{row['hash']}/disposition", json={"disposition": "opinion"}, headers=EDITOR).status_code == 200
    g = client.get(f"/v1/content/{c['id']}/gate", headers=EDITOR).json()
    assert not g["passed"] and any("dispositions changed" in b for b in g["blockers"])
    # Re-approval by an approver clears it.
    assert client.post(f"/v1/content/{c['id']}/approve", json={}, headers=APPROVER).json()["state"] == "approved"


def test_approver_waiver_after_approval_keeps_the_approval(client):
    c = _content(client, classification="investor", body="Demand remains healthy.")
    assert client.post(f"/v1/content/{c['id']}/approve", json={}, headers=APPROVER).json()["state"] == "blocked"
    for row in _ledger(client, c["id"]).values():
        if row["status"] == "open":
            client.put(f"/v1/content/{c['id']}/assertions/{row['hash']}/disposition", json={"disposition": "opinion"}, headers=APPROVER)
    r = client.post(f"/v1/content/{c['id']}/pipeline", headers=EDITOR).json()
    assert r["state"] == "approved"
    assert client.get(f"/v1/content/{c['id']}", headers=EDITOR).json()["approval"]["dispositions_hash"]


def test_legacy_approval_without_dispositions_hash_keeps_old_semantics(client):
    from app.db import SessionLocal
    from app.models import ContentItem
    c = _content(client, classification="investor")
    client.post(f"/v1/content/{c['id']}/approve", json={}, headers=APPROVER)
    with SessionLocal() as db:
        item = db.get(ContentItem, c["id"])
        a = json.loads(item.approval_json); a.pop("dispositions_hash"); item.approval_json = json.dumps(a); db.commit()
    assert client.get(f"/v1/content/{c['id']}/gate", headers=EDITOR).json()["checks"]["human_approved"] is True


# ------------------------------------------------------------------------------ 5. landing page vs CSP, HSTS
def test_landing_page_has_no_inline_style_and_its_stylesheet_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<style" not in r.text and "style=" not in r.text
    assert "style-src 'self'" in r.headers["content-security-policy"]
    css = client.get("/console/landing.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert client.get("/console/../app/main.py").status_code in {404, 422}


def test_hsts_only_in_production(client, monkeypatch):
    assert "strict-transport-security" not in client.get("/health").headers
    monkeypatch.setattr(settings, "environment", "production")
    assert client.get("/health").headers["strict-transport-security"].startswith("max-age=")


# ------------------------------------------------------------------------------ 6. egress response cap
def test_safe_post_caps_response_size(sink, lan, monkeypatch):
    from app.netguard import FeedTooLarge, safe_post
    monkeypatch.setattr(settings, "max_feed_bytes", 1024)
    sink.dynamic = lambda req: (200, {}, b"x" * 5000) if req["path"] == "/big" else None
    with pytest.raises(FeedTooLarge):
        safe_post(sink.url + "/big", content=b"{}", headers={"Content-Type": "application/json"})
    sink.dynamic = lambda req: (200, {}, {"ok": True}) if req["path"] == "/small" else None
    r = safe_post(sink.url + "/small", content=b"{}", headers={"Content-Type": "application/json"})
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_production_requires_https_chrysalis_url():
    from app.config import ConfigError, Settings
    s = Settings(environment="production", api_key="a" * 40, public_base_url="https://x.example",
                 chrysalis_enabled=True, chrysalis_anchor_url="http://chrysalis.internal/anchor")
    with pytest.raises(ConfigError):
        s.validate_runtime()
