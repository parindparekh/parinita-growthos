"""OpenID Connect SSO against a mock identity provider that signs with a real RSA key and enforces PKCE."""
import base64
import hashlib
import hmac
import json
import time
import urllib.parse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from fastapi.testclient import TestClient

from app import sso
from app.main import app
from app.config import ConfigError, Settings, settings
from tests.conftest import APPROVER, AUDITOR, EDITOR, make, sso_login


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_code_flow_creates_a_session_with_mapped_roles(client, sso_on):
    assert client.get("/auth/config").json()["sso"] is True
    assert client.get("/auth/me").status_code == 401
    csrf = sso_login(client, sso_on, groups=["growthos-approver", "growthos-auditor", "some-other-group"])
    me = client.get("/auth/me").json()
    assert me == {"principal": "ana@corp.example", "roles": ["approver", "auditor"], "source": "sso", "csrf": csrf}
    assert client.get("/v1/audit").status_code == 200          # cookie alone is enough for reads
    form = sso_on.token_requests[0]["form"]
    assert form["grant_type"] == "authorization_code" and len(form["code_verifier"]) >= 43  # PKCE verifier was sent
    cookie = [c for c in client.cookies.jar if c.name == "growthos_session"][0]
    assert cookie.has_nonstandard_attr("HttpOnly") and cookie.path == "/"


def test_cookie_sessions_need_a_csrf_token_for_writes(client, sso_on):
    csrf = sso_login(client, sso_on, groups=["growthos-editor"])
    body = {"title": "t", "body": "b"}
    assert client.post("/v1/content", json=body).status_code == 403
    assert client.post("/v1/content", json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/v1/content", json=body, headers={"X-CSRF-Token": csrf}).status_code == 201
    assert client.post("/auth/logout", headers={"X-CSRF-Token": csrf}).json() == {"signed_out": True}
    assert client.get("/auth/me").status_code == 401


def test_bearer_tokens_from_the_idp_are_accepted(client, sso_on):
    tok = sso_on.token(sub="svc-1", preferred_username="release-bot", groups=["growthos-editor"])
    assert client.get("/v1/whoami", headers=bearer(tok)).json() == {"principal": "release-bot", "roles": ["editor"], "source": "sso"}
    assert client.post("/v1/content", json={"title": "t", "body": "b"}, headers=bearer(tok)).status_code == 201  # no CSRF needed: not a cookie


def _other_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.mark.parametrize("case", ["wrong_audience", "expired", "wrong_issuer", "foreign_key", "alg_none", "hs256_key_confusion",
                                  "missing_sub", "garbage"])
def test_forged_or_invalid_tokens_are_rejected(client, sso_on, case):
    idp, now = sso_on, int(time.time())
    if case == "wrong_audience":
        tok = idp.token(aud="another-app")
    elif case == "expired":
        tok = idp.token(exp=now - 3600, iat=now - 7200)
    elif case == "wrong_issuer":
        tok = idp.token(iss="https://evil.example")
    elif case == "foreign_key":
        tok = idp.token(key=_other_key())
    elif case == "alg_none":
        seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
        tok = seg({"alg": "none", "typ": "JWT"}) + "." + seg({"iss": idp.url, "aud": idp.client_id, "sub": "x", "iat": now, "exp": now + 300,
                                                               "groups": ["growthos-admin"]}) + "."
    elif case == "hs256_key_confusion":
        # Classic attack: sign with HMAC using the IdP's *public* key as the secret.
        # (Built by hand: the JWT library itself refuses to create such a token.)
        pem = idp.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
        signing_input = seg({"alg": "HS256", "typ": "JWT", "kid": idp.kid}) + "." + seg(
            {"iss": idp.url, "aud": idp.client_id, "sub": "x", "iat": now, "exp": now + 300, "groups": ["growthos-admin"]})
        mac = hmac.new(pem, signing_input.encode(), hashlib.sha256).digest()
        tok = signing_input + "." + base64.urlsafe_b64encode(mac).rstrip(b"=").decode()
    elif case == "missing_sub":
        tok = jwt.encode({"iss": idp.url, "aud": idp.client_id, "iat": now, "exp": now + 300}, idp.key, algorithm="RS256", headers={"kid": idp.kid})
    else:
        tok = "not.a.jwt"
    assert client.get("/v1/whoami", headers=bearer(tok)).status_code == 401


def test_key_rotation_is_picked_up(client, sso_on):
    assert client.get("/v1/whoami", headers=bearer(sso_on.token())).status_code == 200
    sso_on.rotate()
    assert client.get("/v1/whoami", headers=bearer(sso_on.token())).status_code == 200  # unknown kid -> JWKS refetched


def _login_parts(client):
    r = client.get("/auth/login?next=//evil.example/phish", follow_redirects=False)
    hop = httpx.get(r.headers["location"], follow_redirects=False)
    return urllib.parse.urlparse(hop.headers["location"]), dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.headers["location"]).query))


def test_login_request_uses_pkce_state_nonce_and_refuses_open_redirects(client, sso_on):
    back, asked = _login_parts(client)
    assert asked["response_type"] == "code" and asked["code_challenge_method"] == "S256" and asked["state"] and asked["nonce"]
    assert asked["redirect_uri"] == "http://localhost:8080/auth/callback"
    r = client.get(f"{back.path}?{back.query}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/console"   # not //evil.example


def test_state_nonce_and_replay_are_enforced(client, sso_on):
    back, _ = _login_parts(client)
    q = dict(urllib.parse.parse_qsl(back.query))
    assert client.get(f"/auth/callback?code={q['code']}&state=forged", follow_redirects=False).status_code == 400
    # Same code again, correct state: the IdP has already consumed it.
    back, _ = _login_parts(client)
    q = dict(urllib.parse.parse_qsl(back.query))
    assert client.get(f"/auth/callback?code={q['code']}&state={q['state']}", follow_redirects=False).status_code == 302
    assert client.get(f"/auth/callback?code={q['code']}&state={q['state']}", follow_redirects=False).status_code == 400
    # ID token minted for a different login attempt (nonce mismatch).
    sso_on.nonce_override = "someone-elses-nonce"
    back, _ = _login_parts(client)
    q = dict(urllib.parse.parse_qsl(back.query))
    r = client.get(f"/auth/callback?code={q['code']}&state={q['state']}", follow_redirects=False)
    assert r.status_code == 400 and "nonce" in r.json()["detail"]


def test_production_cookies_are_host_bound_secure_and_clearable(sso_on, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    client = TestClient(app, base_url="https://testserver")   # Secure cookies only travel over https
    back, _ = _login_parts(client)
    r = client.get(f"{back.path}?{back.query}", follow_redirects=False)
    set_cookie = [v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("__Host-growthos_session=")][0]
    assert all(flag in set_cookie for flag in ("Secure", "HttpOnly", "SameSite=lax", "Path=/")) and "Domain" not in set_cookie
    out = client.post("/auth/logout", headers=bearer(sso_on.token(groups=["growthos-editor"])))
    cleared = [v for k, v in out.headers.multi_items() if k == "set-cookie"][0]
    assert cleared.startswith('__Host-growthos_session="";') and "Secure" in cleared and "Max-Age=0" in cleared


def test_tampered_or_foreign_session_cookie_is_rejected(client, sso_on):
    forged = jwt.encode({"name": "attacker", "roles": ["admin", "approver"], "csrf": "x", "exp": int(time.time()) + 600},
                        "not-the-session-secret-not-the-session-secret", algorithm="HS256")
    client.cookies.set("growthos_session", forged)
    assert client.get("/auth/me").status_code == 401


def test_user_without_mapped_groups_can_sign_in_but_do_nothing(client, sso_on):
    csrf = sso_login(client, sso_on, groups=["marketing-all"])
    assert client.get("/auth/me").json()["roles"] == []
    assert client.post("/v1/content", json={"title": "t", "body": "b"}, headers={"X-CSRF-Token": csrf}).status_code == 403


def test_with_sso_on_approvals_need_an_idp_identity_not_an_api_key(client, sso_on):
    cid = make(client, classification="investor")["id"]                      # created by the editor key
    r = client.post(f"/v1/content/{cid}/approve", json={}, headers=APPROVER)   # approver *key*
    assert r.status_code == 403 and "SSO identity" in r.json()["detail"]
    csrf = sso_login(client, sso_on, email="clo@corp.example", groups=["growthos-approver"])
    r = client.post(f"/v1/content/{cid}/approve", json={"note": "reviewed"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["approved_by"] == "clo@corp.example" and r.json()["state"] == "approved"
    approval = client.get(f"/v1/content/{cid}", headers=EDITOR).json()["approval"]
    assert approval["identity"] == "sso"
    assert client.get(f"/v1/audit?content_id={cid}", headers=AUDITOR).json()[0]["actor"] == "clo@corp.example"
    # Sentence waivers and revocations are human acts too.
    h = client.get(f"/v1/content/{cid}/assertions", headers=EDITOR).json()["sentences"][0]["hash"]
    assert client.put(f"/v1/content/{cid}/assertions/{h}/disposition", json={"disposition": "opinion"}, headers=APPROVER).status_code == 403
    assert client.post(f"/v1/content/{cid}/revoke", json={}, headers=APPROVER).status_code == 403


def test_api_keys_can_be_switched_off(client, sso_on, monkeypatch):
    assert client.get("/v1/content", headers=EDITOR).status_code == 200
    monkeypatch.setattr(settings, "api_keys_enabled", False)
    assert client.get("/v1/content", headers=EDITOR).status_code == 401
    assert client.get("/auth/config").json()["api_keys"] is False
    assert client.get("/v1/whoami", headers=bearer(sso_on.token(groups=["growthos-auditor"]))).status_code == 200


def test_sso_routes_are_absent_when_not_configured(client):
    assert client.get("/auth/config").json()["sso"] is False
    assert client.get("/auth/login", follow_redirects=False).status_code == 404
    assert client.get("/v1/whoami", headers=bearer("x.y.z")).status_code == 401


def test_idp_outage_is_a_clean_502(client, sso_on, monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "http://127.0.0.1:1")
    sso.reset_cache()
    assert client.get("/auth/login", follow_redirects=False).status_code == 502


@pytest.mark.parametrize("kw,needle", [
    (dict(session_secret="short"), "SESSION_SECRET"),
    (dict(environment="production", oidc_issuer="http://idp.internal", public_base_url="https://g.example.com"), "OIDC_ISSUER must be https"),
    (dict(oidc_role_map='{"g": ["root"]}'), "unknown role"),
    (dict(oidc_role_map="not json"), "must be JSON"),
])
def test_sso_config_is_validated_at_startup(kw, needle):
    base = dict(oidc_issuer="https://idp.example.com", oidc_client_id="c", session_secret="s" * 40, api_key="", api_keys="")
    base.update(kw)
    with pytest.raises(ConfigError, match=needle):
        Settings(**base).validate_runtime()


# ------------------------------------------------------------------------------ Witness profile (Keycloak-style tokens)
def test_witness_profile_reads_client_roles_from_the_access_token(client, sso_on, monkeypatch):
    monkeypatch.setattr(settings, "identity_provider", "witness")
    assert client.get("/auth/config").json()["sso_label"] == "Witness"
    # Keycloak default: the ID token carries identity only; roles are in the access token (aud "account", azp = client).
    sso_on.access_claims = {"resource_access": {sso_on.client_id: {"roles": ["approver", "auditor"]}, "account": {"roles": ["manage-account"]}},
                            "realm_access": {"roles": ["offline_access", "admin"]}}
    csrf = sso_login(client, sso_on, sub="w-7", email="clo@parinita.example", preferred_username="clo", groups=[])
    me = client.get("/auth/me").json()
    assert me["principal"] == "clo@parinita.example" and me["roles"] == ["approver", "auditor"]   # realm role "admin" grants nothing
    cid = make(client, classification="investor")["id"]
    r = client.post(f"/v1/content/{cid}/approve", json={}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["approved_by"] == "clo@parinita.example"


def test_witness_bearer_tokens_and_role_prefix(client, sso_on, monkeypatch):
    monkeypatch.setattr(settings, "identity_provider", "witness")
    tok = sso_on.token(sub="svc-9", preferred_username="release-agent", resource_access={sso_on.client_id: {"roles": ["editor"]}},
                       realm_access={"roles": ["publisher"]}, groups=["growthos-auditor"])
    assert client.get("/v1/whoami", headers=bearer(tok)).json() == {"principal": "release-agent", "roles": ["auditor", "editor"], "source": "sso"}
    monkeypatch.setattr(settings, "oidc_role_prefix", "growthos:")
    tok = sso_on.token(sub="svc-9", realm_access={"roles": ["growthos:publisher", "growthos:root", "publisher"]})
    assert client.get("/v1/whoami", headers=bearer(tok)).json()["roles"] == ["publisher"]
    monkeypatch.setattr(settings, "oidc_name_claim", "preferred_username")
    tok = sso_on.token(sub="svc-9", email="x@parinita.example", preferred_username="marshal-svc")
    assert client.get("/v1/whoami", headers=bearer(tok)).json()["principal"] == "marshal-svc"


def test_access_token_roles_are_only_trusted_for_this_client_and_this_user(client, sso_on, monkeypatch):
    monkeypatch.setattr(settings, "identity_provider", "witness")
    roles = {"resource_access": {sso_on.client_id: {"roles": ["admin", "approver"]}}}
    sso_on.access_claims = {**roles, "azp": "some-other-client"}            # issued to a different client
    sso_login(client, sso_on, sub="w-1", groups=[])
    assert client.get("/auth/me").json()["roles"] == []
    client.cookies.clear()
    sso_on.access_claims = {**roles, "sub": "someone-else"}                 # for a different subject
    sso_login(client, sso_on, sub="w-1", groups=[])
    assert client.get("/auth/me").json()["roles"] == []
    # Without the Witness profile, a role-named value outside the role map grants nothing, wherever it sits.
    client.cookies.clear()
    monkeypatch.setattr(settings, "identity_provider", "")
    sso_on.access_claims = None
    sso_login(client, sso_on, sub="w-1", groups=["admin", "approver"])
    assert client.get("/auth/me").json()["roles"] == []
    with pytest.raises(ConfigError, match="IDENTITY_PROVIDER"):
        Settings(api_key="k" * 32, identity_provider="okta").validate_runtime()


def test_sso_only_deployment_needs_no_api_keys():
    Settings(environment="production", public_base_url="https://g.example.com", oidc_issuer="https://idp.example.com",
             oidc_client_id="c", session_secret="s" * 40, api_key="", api_keys="").validate_runtime()
