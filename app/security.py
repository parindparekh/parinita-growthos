"""Authentication and role checks.

Three credentials, tried in this order:
  1. X-API-Key          - service accounts and bootstrap (can be disabled with API_KEYS_ENABLED=false)
  2. Authorization: Bearer <JWT from the IdP>   - API use with an SSO identity
  3. session cookie     - the console, after the OIDC code flow; unsafe methods also need X-CSRF-Token

Identity always comes from the credential, never from the request body.
"""
import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request

from . import sso
from .config import settings

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class Principal:
    name: str
    roles: frozenset[str]
    source: str = "key"  # key | sso
    csrf: str = ""

    def has(self, role: str) -> bool:
        # admin implies every role except approver: approval must be an explicit grant.
        return role in self.roles or ("admin" in self.roles and role != "approver")


def authenticate(request: Request, x_api_key: str = Header(default=""), authorization: str = Header(default=""),
                 x_csrf_token: str = Header(default="")) -> Principal:
    if x_api_key:
        presented, match = x_api_key.encode(), None
        for key, name, roles in settings.parsed_keys():  # constant-time, no short-circuit
            if hmac.compare_digest(presented, key.encode()):
                match = Principal(name=name, roles=roles, source="key")
        if match is None:
            raise HTTPException(status_code=401, detail="invalid API key")
        return match

    if settings.sso_enabled:
        if authorization.lower().startswith("bearer "):
            try:
                claims = sso.validate_token(authorization[7:].strip(), audience=settings.oidc_audience or settings.oidc_client_id)
            except sso.SSOError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc
            return Principal(name=sso.name_from_claims(claims), roles=sso.roles_from_claims(claims), source="sso")
        cookie = request.cookies.get(sso.session_cookie_name())
        if cookie:
            try:
                s = sso.read_session(cookie)
            except sso.SSOError as exc:
                raise HTTPException(status_code=401, detail="session expired; sign in again") from exc
            if request.method in UNSAFE and not (x_csrf_token and hmac.compare_digest(x_csrf_token, s.get("csrf", ""))):
                raise HTTPException(status_code=403, detail="missing or invalid CSRF token")
            return Principal(name=s["name"], roles=frozenset(s.get("roles", [])), source="sso", csrf=s.get("csrf", ""))
    raise HTTPException(status_code=401, detail="not authenticated")


def optional_principal(request: Request, x_api_key: str = Header(default=""), authorization: str = Header(default=""),
                       x_csrf_token: str = Header(default="")) -> Principal | None:
    """Who is calling, if anyone. Lets the console ask 'am I signed in?' without provoking a 401."""
    try:
        return authenticate(request, x_api_key, authorization, x_csrf_token)
    except HTTPException:
        return None


def require_role(role: str):
    def dep(principal: Principal = Depends(authenticate)) -> Principal:
        if not principal.has(role):
            raise HTTPException(status_code=403, detail=f"role '{role}' required")
        return principal
    return dep


def require_human(role: str):
    """For acts that must be attributable to a person (approve, revoke, waive a sentence):
    when SSO is configured, an API key is not enough."""
    def dep(principal: Principal = Depends(authenticate)) -> Principal:
        if not principal.has(role):
            raise HTTPException(status_code=403, detail=f"role '{role}' required")
        if settings.approvals_need_sso and principal.source != "sso":
            raise HTTPException(status_code=403, detail="this action requires an SSO identity, not an API key")
        return principal
    return dep
