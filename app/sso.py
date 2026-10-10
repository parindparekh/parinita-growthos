"""OpenID Connect single sign-on.

Two entry points share one token validator:
  * browser sessions for the console: Authorization Code flow with PKCE, state and nonce;
    the result is a signed, HttpOnly session cookie plus a CSRF token for unsafe methods.
  * API bearer tokens: a JWT issued by the same IdP, validated against its JWKS and audience.

Only asymmetric signature algorithms are accepted. Roles come from a configurable claim mapped
through OIDC_ROLE_MAP; a user whose groups map to nothing can sign in but can do nothing.

Sessions are stateless: sign-out clears the cookie, and a stolen cookie stays valid until it
expires (SESSION_TTL_SECONDS). Removing a user at the IdP takes effect at their next sign-in.
"""
import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from urllib.parse import urlencode

import httpx
import jwt

from .config import settings

log = logging.getLogger("growthos.sso")

ASYMMETRIC = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512", "EdDSA"}
DISCOVERY_TTL = 3600
JWKS_MIN_REFRESH = 30  # seconds between forced JWKS refetches (unknown kid)
FLOW_COOKIE = "growthos_oidc"
FLOW_TTL = 600


class SSOError(Exception):
    pass


def session_cookie_name() -> str:
    # __Host- prefix: browser only accepts it with Secure, Path=/ and no Domain.
    return "__Host-growthos_session" if settings.is_production else "growthos_session"


_lock = threading.Lock()
_cache: dict = {"issuer": None, "discovery": None, "discovery_at": 0.0, "jwks": None, "jwks_at": 0.0}


def reset_cache() -> None:
    with _lock:
        _cache.update(issuer=None, discovery=None, discovery_at=0.0, jwks=None, jwks_at=0.0)


def _get_json(url: str) -> dict:
    # The IdP is operator-configured infrastructure (like the database); it is not subject to the
    # destination egress policy. Redirects are not followed.
    r = httpx.get(url, timeout=settings.http_timeout_seconds, follow_redirects=False)
    r.raise_for_status()
    return r.json()


def discovery() -> dict:
    issuer = settings.oidc_issuer.rstrip("/")
    with _lock:
        fresh = _cache["discovery"] and _cache["issuer"] == issuer and time.time() - _cache["discovery_at"] < DISCOVERY_TTL
        if fresh:
            return _cache["discovery"]
    try:
        doc = _get_json(issuer + "/.well-known/openid-configuration")
    except Exception as exc:  # noqa: BLE001
        raise SSOError(f"identity provider discovery failed: {type(exc).__name__}") from exc
    if doc.get("issuer", "").rstrip("/") != issuer:
        raise SSOError("identity provider discovery document names a different issuer")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not doc.get(field):
            raise SSOError(f"identity provider discovery document lacks {field}")
    with _lock:
        _cache.update(issuer=issuer, discovery=doc, discovery_at=time.time(), jwks=None, jwks_at=0.0)
    return doc


def _jwks(force: bool = False) -> dict:
    doc = discovery()
    with _lock:
        have, age = _cache["jwks"], time.time() - _cache["jwks_at"]
    if have and not (force and age >= JWKS_MIN_REFRESH):
        return have
    try:
        keys = _get_json(doc["jwks_uri"])
    except Exception as exc:  # noqa: BLE001
        raise SSOError(f"identity provider key fetch failed: {type(exc).__name__}") from exc
    with _lock:
        _cache.update(jwks=keys, jwks_at=time.time())
    return keys


def _signing_key(token: str):
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise SSOError("malformed token") from exc
    allowed = {a.strip() for a in settings.oidc_algorithms.split(",") if a.strip()} & ASYMMETRIC
    alg = header.get("alg")
    if alg not in allowed:  # rejects "none" and every HMAC algorithm (key-confusion attacks)
        raise SSOError(f"token algorithm '{alg}' is not accepted")
    kid = header.get("kid")
    for attempt in (False, True):
        for k in _jwks(force=attempt).get("keys", []):
            if (kid is None or k.get("kid") == kid) and k.get("use", "sig") == "sig":
                try:
                    return jwt.PyJWK.from_dict(k).key, alg
                except jwt.PyJWTError:
                    continue
    raise SSOError("no identity provider key matches this token")


def validate_token(token: str, *, audience: str, nonce: str | None = None) -> dict:
    """Signature, issuer, audience, expiry (and nonce for ID tokens). Returns the claims."""
    key, alg = _signing_key(token)
    try:
        claims = jwt.decode(token, key=key, algorithms=[alg], audience=audience, issuer=discovery()["issuer"],
                            leeway=60, options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except jwt.PyJWTError as exc:
        raise SSOError(f"token rejected: {type(exc).__name__}") from exc
    if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SSOError("token rejected: nonce mismatch")
    assert_company(claims)
    return claims


def _dig(claims: dict, path: str):
    node = claims
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def assert_company(claims: dict) -> None:
    if not settings.company_id:
        return  # legacy single-workspace deployment; no cross-company membership claim
    value = _dig(claims, settings.oidc_company_claim)
    if not isinstance(value, str) or not hmac.compare_digest(value.encode(), settings.company_id.encode()):
        raise SSOError("This identity does not belong to this company workspace")


def roles_from_claims(claims: dict) -> frozenset[str]:
    """Group/role values -> GrowthOS roles.

    A value becomes a role through OIDC_ROLE_MAP. It may name a role directly only where that cannot be an accident:
    under the GrowthOS client's own roles (resource_access.<client id>.roles, the Keycloak/Witness layout), or when
    it carries OIDC_ROLE_PREFIX. A realm-wide group that merely happens to be called "admin" grants nothing."""
    from .config import ROLES
    mapping, prefix, out = settings.role_map, settings.oidc_role_prefix, set()
    for path in settings.role_claim_paths:
        raw = _dig(claims, path)
        if isinstance(raw, str):
            raw = raw.replace(",", " ").split()
        for value in raw if isinstance(raw, list) else []:
            value = str(value)
            out.update(mapping.get(value, []))
            if path == settings.client_roles_path and value in ROLES:
                out.add(value)
            if prefix and value.startswith(prefix) and value[len(prefix):] in ROLES:
                out.add(value[len(prefix):])
    return frozenset(out)


def name_from_claims(claims: dict) -> str:
    if settings.oidc_name_claim and claims.get(settings.oidc_name_claim):
        return str(claims[settings.oidc_name_claim])[:100]
    email = claims.get("email")
    if email and claims.get("email_verified", True) is not False:
        return str(email).lower()[:100]
    return str(claims.get("preferred_username") or claims.get("sub"))[:100]


def _access_token_roles(access_token, sub: str) -> frozenset[str]:
    """Keycloak (and so Witness) puts roles in the access token and, by default, not in the ID token. The access token
    here came straight from the token endpoint over the back channel, for this client and this login; it is accepted
    only if it is signed by the IdP, unexpired, issued to this client (azp) and for the same subject."""
    if not isinstance(access_token, str) or access_token.count(".") != 2:
        return frozenset()
    try:
        key, alg = _signing_key(access_token)
        claims = jwt.decode(access_token, key=key, algorithms=[alg], issuer=discovery()["issuer"], leeway=60,
                            options={"require": ["exp", "iss", "sub"], "verify_aud": False})
    except (SSOError, jwt.PyJWTError):
        return frozenset()
    if claims.get("azp") != settings.oidc_client_id or str(claims.get("sub")) != sub:
        return frozenset()
    try:
        assert_company(claims)
    except SSOError:
        return frozenset()
    return roles_from_claims(claims)


# ----------------------------------------------------------------------------- browser flow
def _sign(payload: dict, ttl: int) -> str:
    return jwt.encode({**payload, "exp": int(time.time()) + ttl}, settings.session_secret, algorithm="HS256")


def _unsign(token: str) -> dict:
    try:
        return jwt.decode(token, settings.session_secret, algorithms=["HS256"], options={"require": ["exp"]})
    except jwt.PyJWTError as exc:
        raise SSOError("invalid or expired cookie") from exc


def redirect_uri() -> str:
    return settings.public_base_url.rstrip("/") + "/auth/callback"


def safe_next(target: str | None) -> str:
    """Only same-site relative paths, never a scheme, host or protocol-relative URL."""
    t = target or "/console"
    return t if t.startswith("/") and not t.startswith("//") and "\\" not in t and "\n" not in t and "\r" not in t else "/console"


def begin_login(next_path: str | None) -> tuple[str, str]:
    """Returns (authorization URL, flow cookie value)."""
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {"response_type": "code", "client_id": settings.oidc_client_id, "redirect_uri": redirect_uri(),
              "scope": settings.oidc_scopes, "state": state, "nonce": nonce,
              "code_challenge": challenge, "code_challenge_method": "S256"}
    url = discovery()["authorization_endpoint"]
    flow = _sign({"state": state, "nonce": nonce, "verifier": verifier, "next": safe_next(next_path)}, FLOW_TTL)
    return url + ("&" if "?" in url else "?") + urlencode(params), flow


def complete_login(code: str, state: str, flow_cookie: str) -> tuple[str, str]:
    """Exchange the code, validate the ID token, mint a session. Returns (session cookie value, next path)."""
    flow = _unsign(flow_cookie or "")
    if not state or not hmac.compare_digest(flow.get("state", ""), state):
        raise SSOError("state mismatch")
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
            "client_id": settings.oidc_client_id, "code_verifier": flow["verifier"]}
    auth = (settings.oidc_client_id, settings.oidc_client_secret) if settings.oidc_client_secret else None
    try:
        r = httpx.post(discovery()["token_endpoint"], data=data, auth=auth,
                       timeout=settings.http_timeout_seconds, follow_redirects=False)
        r.raise_for_status()
        tokens = r.json()
        id_token = tokens["id_token"]
    except Exception as exc:  # noqa: BLE001
        raise SSOError(f"code exchange failed: {type(exc).__name__}") from exc
    claims = validate_token(id_token, audience=settings.oidc_client_id, nonce=flow["nonce"])
    roles = roles_from_claims(claims) | _access_token_roles(tokens.get("access_token"), str(claims["sub"]))
    session = _sign({"sub": str(claims["sub"]), "name": name_from_claims(claims),
                     "company_id": settings.company_id, "roles": sorted(roles), "csrf": secrets.token_urlsafe(24)},
                    settings.session_ttl_seconds)
    return session, flow.get("next", "/console")


def read_session(cookie: str) -> dict:
    session = _unsign(cookie)
    if settings.company_id and session.get("company_id") != settings.company_id:
        raise SSOError("Session belongs to another company workspace")
    return session
