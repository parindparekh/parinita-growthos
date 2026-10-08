"""Social network adapters: LinkedIn, X, Mastodon, Bluesky.

Request shapes follow each provider's public API documentation as of October 2026:
  LinkedIn  POST /rest/posts                         (Posts API; LinkedIn-Version + X-Restli-Protocol-Version headers)
  X         POST /2/tweets                           (OAuth 1.0a user context, or an OAuth 2.0 user token)
  Mastodon  POST /api/v1/statuses                    (bearer token; honours Idempotency-Key)
  Bluesky   com.atproto.server.createSession -> com.atproto.repo.createRecord (app password)

Each needs a provider developer app / account and credentials supplied as GROWTHOS_SECRET_* variables.
"""
import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import quote

from . import Adapter, DeliveryResult, register
from ._common import base_url, call, compose, failure, link_spans_utf8, secret, x_weight

_URL = re.compile(r"https?://\S+")
_LI_RESERVED = re.compile(r"[\\|{}@\[\]()<>*_~]|#(?![A-Za-z0-9])")


def linkedin_escape(text: str) -> str:
    """LinkedIn 'little' text format: reserved characters must be backslash-escaped or the post is truncated
    at the first one. URLs are left intact so they still link; #hashtags stay hashtags."""
    out, pos = [], 0
    for m in _URL.finditer(text):
        out.append(_LI_RESERVED.sub(lambda x: "\\" + x.group(0), text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_LI_RESERVED.sub(lambda x: "\\" + x.group(0), text[pos:]))
    return "".join(out)


class LinkedInAdapter(Adapter):
    protocols = {"linkedin"}

    def check_config(self, url, cfg):
        if not re.fullmatch(r"urn:li:(organization|person):[A-Za-z0-9_-]+", str(cfg.get("author_urn", ""))):
            return "linkedin endpoints need config.author_urn (urn:li:organization:<id> or urn:li:person:<id>)"
        if not cfg.get("bearer_token_env"):
            return "linkedin endpoints need config.bearer_token_env"
        if cfg.get("api_version") and not re.fullmatch(r"20\d{4}", str(cfg["api_version"])):
            return "config.api_version must be YYYYMM"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        token = secret(cfg, "bearer_token_env")
        # LinkedIn publishes a version monthly and retires them after about a year. Pin one in config; the
        # default (two months back) is a version that normally exists and is still supported.
        now = datetime.now(timezone.utc)
        y, m = (now.year, now.month - 2) if now.month > 2 else (now.year - 1, now.month + 10)
        version = str(cfg.get("api_version") or f"{y}{m:02d}")
        text = compose(payload, "linkedin", int(cfg.get("max_chars", 3000)), text_source=cfg.get("text_source", "auto"))
        body = {"author": cfg["author_urn"], "commentary": linkedin_escape(text), "visibility": cfg.get("visibility", "PUBLIC"),
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
                "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
        r, n, err = call("POST", base_url("linkedin", "https://api.linkedin.com") + "/rest/posts", idempotent=False, json=body,
                         headers={"Authorization": f"Bearer {token}", "LinkedIn-Version": version,
                                  "X-Restli-Protocol-Version": "2.0.0", "Content-Type": "application/json"})
        if r is not None and r.status_code == 201:
            return DeliveryResult(ok=True, status_code=201, attempts=n, provider_id=r.headers.get("x-restli-id", "")[:300])
        hint = {401: "access token expired or revoked (LinkedIn tokens last 60 days)",
                426: "api_version is not available; set config.api_version to a current YYYYMM"}.get(r.status_code if r is not None else 0, "")
        return failure(r, n, err, hint)


def _pct(s: str) -> str:
    return quote(str(s), safe="-._~")


def oauth1_header(method: str, url: str, consumer_key: str, consumer_secret: str, token: str, token_secret: str,
                  nonce: str | None = None, timestamp: str | None = None) -> str:
    """RFC 5849 HMAC-SHA1 Authorization header. A JSON body is not part of the signature base string."""
    params = {"oauth_consumer_key": consumer_key, "oauth_nonce": nonce or secrets.token_hex(16),
              "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": timestamp or str(int(time.time())),
              "oauth_token": token, "oauth_version": "1.0"}
    base = "&".join([method.upper(), _pct(url), _pct("&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(params.items())))])
    key = f"{_pct(consumer_secret)}&{_pct(token_secret)}".encode()
    params["oauth_signature"] = base64.b64encode(hmac.new(key, base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(params.items()))


class XAdapter(Adapter):
    protocols = {"x"}
    _OAUTH1 = ("consumer_key_env", "consumer_secret_env", "access_token_env", "access_token_secret_env")

    def check_config(self, url, cfg):
        if cfg.get("bearer_token_env") or all(cfg.get(k) for k in self._OAUTH1):
            return ""
        return "x endpoints need either config.bearer_token_env (OAuth 2.0 user token) or all of " + ", ".join(self._OAUTH1)

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        url = base_url("x", "https://api.x.com") + "/2/tweets"
        if all(cfg.get(k) for k in self._OAUTH1):
            auth = oauth1_header("POST", url, *(secret(cfg, k) for k in self._OAUTH1))
        else:
            auth = "Bearer " + secret(cfg, "bearer_token_env")
        text = compose(payload, "x", int(cfg.get("max_chars", 280)), weigh=x_weight, text_source=cfg.get("text_source", "auto"))
        r, n, err = call("POST", url, idempotent=False, json={"text": text},
                         headers={"Authorization": auth, "Content-Type": "application/json"})
        if r is not None and r.status_code in (200, 201):
            return DeliveryResult(ok=True, status_code=r.status_code, attempts=n,
                                  provider_id=str((r.json().get("data") or {}).get("id", ""))[:300])
        hint = {401: "credentials rejected (OAuth 2.0 user tokens expire after two hours; OAuth 1.0a tokens do not)",
                403: "refused by X (duplicate text, or the app lacks write access)"}.get(r.status_code if r is not None else 0, "")
        return failure(r, n, err, hint)


class MastodonAdapter(Adapter):
    protocols = {"mastodon"}

    def check_config(self, url, cfg):
        return "" if cfg.get("bearer_token_env") else "mastodon endpoints need config.bearer_token_env and the instance URL"

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        token = secret(cfg, "bearer_token_env")
        text = compose(payload, "mastodon", int(cfg.get("max_chars", 500)), text_source=cfg.get("text_source", "auto"))
        body = {"status": text, "visibility": cfg.get("visibility", "public"), "language": (payload.get("locale") or "en")[:2]}
        r, n, err = call("POST", endpoint.url.rstrip("/") + "/api/v1/statuses", idempotent=True, json=body,
                         headers={"Authorization": f"Bearer {token}", "Idempotency-Key": idempotency_key})
        if r is not None and r.status_code == 200:
            j = r.json()
            return DeliveryResult(ok=True, status_code=200, attempts=n, provider_id=str(j.get("url") or j.get("id", ""))[:300])
        return failure(r, n, err)


class BlueskyAdapter(Adapter):
    protocols = {"bluesky"}

    def check_config(self, url, cfg):
        if not cfg.get("identifier") or not cfg.get("app_password_env"):
            return "bluesky endpoints need config.identifier (handle) and config.app_password_env"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        pds = (endpoint.url or base_url("bluesky", "https://bsky.social")).rstrip("/")
        r, n, err = call("POST", pds + "/xrpc/com.atproto.server.createSession", idempotent=True,
                         json={"identifier": cfg["identifier"], "password": secret(cfg, "app_password_env")},
                         headers={"Content-Type": "application/json"})
        if r is None or r.status_code != 200:
            return failure(r, n, err, "sign-in with the app password failed")
        session = r.json()
        text = compose(payload, "bluesky", int(cfg.get("max_chars", 300)), text_source=cfg.get("text_source", "auto"))
        record = {"$type": "app.bsky.feed.post", "text": text, "langs": [(payload.get("locale") or "en")[:2]],
                  "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        facets = [{"index": {"byteStart": a, "byteEnd": b}, "features": [{"$type": "app.bsky.richtext.facet#link", "uri": u}]}
                  for a, b, u in link_spans_utf8(text)]
        if facets:
            record["facets"] = facets  # without facets a URL is plain text, not a link
        r, n2, err = call("POST", pds + "/xrpc/com.atproto.repo.createRecord", idempotent=False,
                          json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
                          headers={"Authorization": f"Bearer {session['accessJwt']}", "Content-Type": "application/json"})
        if r is not None and r.status_code == 200:
            return DeliveryResult(ok=True, status_code=200, attempts=n + n2 - 1, provider_id=str(r.json().get("uri", ""))[:300])
        return failure(r, n2, err)


for _a in (LinkedInAdapter(), XAdapter(), MastodonAdapter(), BlueskyAdapter()):
    register(_a)
