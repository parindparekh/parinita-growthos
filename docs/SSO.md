# Single sign-on

Using Parinita Witness as the identity provider? Start with `WITNESS.md`; this page is the generic reference.

GrowthOS speaks standard OpenID Connect, so it works with Okta, Microsoft Entra ID, Keycloak, Google Workspace,
or any other compliant provider (including an internal one). Code: `app/sso.py`, `app/security.py`.

## Set up

1. In the identity provider, register a web application:
   - redirect URI `<PUBLIC_BASE_URL>/auth/callback`
   - grant type Authorization Code, PKCE (S256) enabled
   - scopes `openid profile email`, and a groups (or roles) claim in the ID token
2. In `.env`:

```
OIDC_ISSUER=https://idp.example.com/realms/corp
OIDC_CLIENT_ID=growthos
OIDC_CLIENT_SECRET=...                 # leave empty for a public client (PKCE only)
OIDC_ROLE_CLAIM=groups
OIDC_ROLE_MAP={"Comms-Editors":["editor"],"Legal-Approvers":["approver","auditor"],"Comms-Publishers":["publisher"],"Platform-Admins":["admin"]}
SESSION_SECRET=<48+ random hex chars>   # deploy.sh generates one
```

3. Restart. `/console` now offers "Sign in with your company account".

## What you get

| | |
|---|---|
| Console sessions | Authorization Code flow with PKCE, `state` and `nonce`. Session is a signed cookie: `HttpOnly`, `SameSite=Lax`, `Secure` and `__Host-` prefixed in production. Writes also need `X-CSRF-Token`. |
| API access | `Authorization: Bearer <JWT>` issued by the same IdP (audience `OIDC_AUDIENCE`, default the client id). For scripts and service principals. |
| Roles | Values of `OIDC_ROLE_CLAIM` are mapped through `OIDC_ROLE_MAP`. A user whose groups map to nothing can sign in and can do nothing. `admin` never implies `approver`. |
| Human approvals | With SSO configured, approve / revoke / sentence waivers are refused for API keys (`APPROVAL_REQUIRES_SSO`, default true). The audit trail then names a person from your directory. |
| Keys | API keys keep working for automation unless `API_KEYS_ENABLED=false`. |

## Token validation

Signature against the IdP's JWKS (refetched on an unknown key id, so key rotation needs no restart), issuer,
audience, expiry with 60 s leeway, required `sub`. Only asymmetric algorithms are accepted; `none` and HMAC
tokens are rejected, which closes the key-confusion attack. Tests: `tests/test_sso.py`.

## Limits to know

- Sessions are stateless. Sign-out clears the cookie; a copied cookie stays valid until `SESSION_TTL_SECONDS`
  (default 8 h). Removing someone at the IdP takes effect at their next sign-in or token expiry.
- Roles are read at sign-in. A group change applies to the next session.
- No SCIM, no per-campaign permissions, no back-channel logout.
- Tested against a mock OIDC provider that signs with a real RSA key and enforces PKCE, not against a named
  commercial IdP. Verify with yours during acceptance.
