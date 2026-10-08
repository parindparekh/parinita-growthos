"""Identity, roles, startup hardening and the egress guard."""
import pytest

from app.config import ConfigError, Settings, settings
from app.netguard import DestinationBlocked, check_url
from tests.conftest import APPROVER, AUDITOR, BOOT, EDITOR, EDITOR_APPROVER, PUBLISHER, make

STRONG = "k" * 32


def test_missing_or_wrong_key_is_401(client):
    assert client.get("/v1/content").status_code == 401
    assert client.get("/v1/content", headers={"X-API-Key": "nope"}).status_code == 401


def test_roles_are_enforced(client):
    cid = make(client)["id"]
    assert client.post("/v1/content", json={"title": "t", "body": "b"}, headers=AUDITOR).status_code == 403
    assert client.post(f"/v1/content/{cid}/approve", json={}, headers=EDITOR).status_code == 403
    assert client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": "x"}, headers=EDITOR).status_code == 403
    assert client.post("/v1/feeds", json={"name": "n", "slug": "s", "direction": "outbound", "protocol": "rss"}, headers=EDITOR).status_code == 403
    assert client.get("/v1/audit", headers=EDITOR).status_code == 403
    assert client.get("/v1/audit", headers=AUDITOR).status_code == 200
    assert client.get("/v1/whoami", headers=PUBLISHER).json() == {"principal": "pat", "roles": ["publisher"], "source": "key"}


def test_approver_identity_comes_from_the_key_not_the_body(client):
    cid = make(client, classification="investor")["id"]
    r = client.post(f"/v1/content/{cid}/approve", json={"approver": "Chief Legal Officer"}, headers=APPROVER).json()
    assert r["approved_by"] == "ana"
    stored = client.get(f"/v1/content/{cid}", headers=EDITOR).json()["approval"]
    assert stored["approved_by"] == "ana" and stored["attested_name"] == "Chief Legal Officer"


def test_bootstrap_key_cannot_approve_in_production(client, monkeypatch):
    cid = make(client, classification="investor")["id"]
    assert client.post(f"/v1/content/{cid}/approve", json={}, headers=BOOT).status_code == 200  # development
    monkeypatch.setattr(settings, "environment", "production")
    assert client.post(f"/v1/content/{cid}/approve", json={}, headers=BOOT).status_code == 403
    assert client.post(f"/v1/content/{cid}/approve", json={}, headers=APPROVER).status_code == 200


def test_four_eyes_for_high_risk_content(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    own = client.post("/v1/content", json={"title": "t", "body": "b", "classification": "financial"}, headers=EDITOR_APPROVER).json()["id"]
    r = client.post(f"/v1/content/{own}/approve", json={}, headers=EDITOR_APPROVER)
    assert r.status_code == 403 and "four-eyes" in r.json()["detail"]
    assert client.post(f"/v1/content/{own}/approve", json={}, headers=APPROVER).status_code == 200
    # Editing someone else's item and then approving your own edit is the same conflict.
    other = make(client, classification="financial")["id"]  # created by erin
    client.patch(f"/v1/content/{other}", json={"body": "Rewritten by the would-be approver."}, headers=EDITOR_APPROVER)
    assert client.post(f"/v1/content/{other}/approve", json={}, headers=EDITOR_APPROVER).status_code == 403
    assert client.post(f"/v1/content/{other}/approve", json={}, headers=APPROVER).status_code == 200


@pytest.mark.parametrize("kw,needle", [
    (dict(api_key="change-me-now"), "weak/default"),
    (dict(api_key="short"), "weak/default"),
    (dict(api_key=STRONG, public_base_url="http://growth.example.com"), "https"),
    (dict(api_key=STRONG, api_keys="bob:approver:tiny"), "weak/default"),
])
def test_production_refuses_unsafe_config(kw, needle):
    base = dict(environment="production", public_base_url="https://growth.example.com", api_keys="")
    base.update(kw)
    with pytest.raises(ConfigError, match=needle):
        Settings(**base).validate_runtime()


def test_production_accepts_strong_config_and_rejects_bad_roles():
    Settings(environment="production", api_key=STRONG, api_keys=f"ana:approver:{'a' * 32}",
             public_base_url="https://growth.example.com").validate_runtime()
    with pytest.raises(ConfigError, match="unknown role"):
        Settings(api_key=STRONG, api_keys=f"x:root:{'b' * 32}").validate_runtime()
    with pytest.raises(ConfigError, match="No API credentials"):
        Settings(api_key="", api_keys="").validate_runtime()


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080/x", "http://localhost/x", "http://169.254.169.254/latest/meta-data/",
                                 "http://10.0.0.5/hook", "http://[::1]/x", "http://192.168.1.1/", "ftp://example.com/x",
                                 "file:///etc/passwd", "https://user:pw@example.com/", "http://0.0.0.0/"])
def test_egress_guard_blocks_internal_and_odd_destinations(url):
    with pytest.raises(DestinationBlocked):
        check_url(url)


def test_allowlist_restricts_hosts(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_destinations", True)
    monkeypatch.setattr(settings, "destination_allowlist", "hooks.partner.com, example.org")
    assert check_url("https://api.hooks.partner.com/x")
    with pytest.raises(DestinationBlocked):
        check_url("https://evil-hooks.partner.com.attacker.net/x")


def test_endpoint_config_cannot_name_arbitrary_env_vars_or_auth_headers(client):
    base = {"name": "n", "direction": "outbound", "protocol": "webhook", "url": "https://hooks.example.com/x"}
    # v1.0: bearer_token_env=SMTP_PASSWORD sent the SMTP password to the destination as a Bearer token.
    r = client.post("/v1/feeds", json={**base, "slug": "a", "config": {"bearer_token_env": "SMTP_PASSWORD"}}, headers=BOOT)
    assert r.status_code == 422
    r = client.post("/v1/feeds", json={**base, "slug": "b", "config": {"headers": {"Authorization": "Bearer inline"}}}, headers=BOOT)
    assert r.status_code == 422
    r = client.post("/v1/feeds", json={**base, "slug": "c", "url": "file:///etc/passwd"}, headers=BOOT)
    assert r.status_code == 422
    r = client.post("/v1/feeds", json={**base, "slug": "Bad Slug/../x"}, headers=BOOT)
    assert r.status_code == 422


def test_duplicate_ids_are_409_not_500(client):
    make(client, id="dup")
    assert client.post("/v1/content", json={"id": "dup", "title": "a", "body": "b"}, headers=EDITOR).status_code == 409
    assert client.post("/v1/content", json={"title": "a", "body": "b", "campaign_id": "missing"}, headers=EDITOR).status_code == 400
