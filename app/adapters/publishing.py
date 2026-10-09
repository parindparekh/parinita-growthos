"""Blogs and newsletters: Dev.to, Ghost, Buttondown, Mailchimp.

  Dev.to      POST /api/articles                         api-key header; markdown body
  Ghost       POST /ghost/api/admin/posts/?source=html   Admin API key -> short-lived JWT (HS256, kid = key id)
  Buttondown  POST /v1/emails                            Token auth; status draft|about_to_send
  Mailchimp   POST /3.0/campaigns -> PUT .../content -> POST .../actions/send
              (data centre from the key suffix; the campaign id is the resume point so a failed send step never
               creates a second campaign)
"""
import re
import html
import time

from . import Adapter, DeliveryResult, register
from ._common import base_url, call, failure, secret


def _html(payload: dict, link_label: str = "Read more") -> str:
    esc = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    body = (payload.get("body") or payload.get("summary") or "").strip()
    out = "".join(f"<p>{esc(p).replace(chr(10), '<br>')}</p>" for p in re.split(r"\n\s*\n", body) if p.strip())
    if payload.get("cta_url"):
        out += f'<p><a href="{esc(payload["cta_url"])}">{esc(link_label)}</a></p>'
    return out


def _markdown(payload: dict) -> str:
    text = (payload.get("body") or payload.get("summary") or "").strip()
    if payload.get("cta_url"):
        text += f"\n\n[Read more]({payload['cta_url']})"
    return text


class DevToAdapter(Adapter):
    protocols = {"devto"}

    def check_config(self, url, cfg):
        return "" if cfg.get("api_key_env") else "devto endpoints need config.api_key_env"

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        article = {"title": str(payload.get("title", ""))[:128], "body_markdown": _markdown(payload), "published": not cfg.get("draft", False),
                   "tags": [str(t) for t in (cfg.get("tags") or [])[:4]]}
        if payload.get("summary"):
            article["description"] = str(payload["summary"])[:160]
        if payload.get("source") and str(payload["source"]).startswith("http"):
            article["canonical_url"] = payload["source"]
        if cfg.get("organization_id"):
            article["organization_id"] = int(cfg["organization_id"])
        r, n, err = call("POST", base_url("devto", "https://dev.to") + "/api/articles", idempotent=False, json={"article": article},
                         headers={"api-key": secret(cfg, "api_key_env"), "Content-Type": "application/json"})
        if r is not None and r.status_code == 201:
            j = r.json()
            return DeliveryResult(ok=True, status_code=201, attempts=n, provider_id=str(j.get("url") or j.get("id", ""))[:300], publishes=not cfg.get("draft", False))
        return failure(r, n, err, "api key rejected" if r is not None and r.status_code == 401 else "")


class GhostAdapter(Adapter):
    protocols = {"ghost"}

    def check_config(self, url, cfg):
        if not url:
            return "ghost endpoints need the site URL"
        return "" if cfg.get("admin_key_env") else "ghost endpoints need config.admin_key_env (Admin API key, id:secret)"

    @staticmethod
    def token(admin_key: str) -> str:
        import jwt
        kid, _, hexsecret = admin_key.partition(":")
        if not kid or not re.fullmatch(r"[0-9a-fA-F]+", hexsecret or ""):
            raise ValueError("Ghost admin key must look like <id>:<hex secret>")
        now = int(time.time())
        return jwt.encode({"iat": now, "exp": now + 300, "aud": "/admin/"}, bytes.fromhex(hexsecret), algorithm="HS256", headers={"kid": kid})

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        try:
            tok = self.token(secret(cfg, "admin_key_env"))
        except ValueError as exc:
            return DeliveryResult(ok=False, detail=str(exc))
        post = {"title": str(payload.get("title", ""))[:255], "html": _html(payload, str(cfg.get("link_label", "Read more"))),
                "status": "draft" if cfg.get("draft") else "published"}
        if payload.get("summary"):
            post["custom_excerpt"] = str(payload["summary"])[:300]
        if cfg.get("tags"):
            post["tags"] = [{"name": str(t)} for t in cfg["tags"][:20]]
        r, n, err = call("POST", endpoint.url.rstrip("/") + "/ghost/api/admin/posts/?source=html", idempotent=False, json={"posts": [post]},
                         headers={"Authorization": f"Ghost {tok}", "Content-Type": "application/json", "Accept-Version": str(cfg.get("accept_version", "v5.0"))})
        if r is not None and r.status_code == 201:
            p = (r.json().get("posts") or [{}])[0]
            return DeliveryResult(ok=True, status_code=201, attempts=n, provider_id=str(p.get("url") or p.get("id", ""))[:300], publishes=not cfg.get("draft", False))
        return failure(r, n, err, "Admin API key rejected" if r is not None and r.status_code == 401 else "")


class ButtondownAdapter(Adapter):
    protocols = {"buttondown"}

    def check_config(self, url, cfg):
        return "" if cfg.get("api_key_env") else "buttondown endpoints need config.api_key_env"

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        body = {"subject": str(payload.get("title", ""))[:200], "body": _markdown(payload),
                "status": "draft" if cfg.get("draft") else "about_to_send"}
        if payload.get("summary"):
            body["description"] = str(payload["summary"])[:300]
        r, n, err = call("POST", base_url("buttondown", "https://api.buttondown.com") + "/v1/emails", idempotent=False, json=body,
                         headers={"Authorization": f"Token {secret(cfg, 'api_key_env')}", "Content-Type": "application/json"})
        if r is not None and r.status_code == 201:
            return DeliveryResult(ok=True, status_code=201, attempts=n, provider_id=str(r.json().get("id", ""))[:300],
                                  publishes=not cfg.get("draft", False), detail="draft created" if cfg.get("draft") else "queued to send")
        return failure(r, n, err)


class MailchimpAdapter(Adapter):
    protocols = {"mailchimp"}

    def check_config(self, url, cfg):
        if not cfg.get("api_key_env") or not cfg.get("list_id"):
            return "mailchimp endpoints need config.api_key_env and config.list_id (audience id)"
        if not cfg.get("from_name") or not cfg.get("reply_to"):
            return "mailchimp endpoints need config.from_name and config.reply_to"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        key = secret(cfg, "api_key_env")
        dc = key.rsplit("-", 1)[-1] if "-" in key else "us1"
        base = base_url("mailchimp", f"https://{dc}.api.mailchimp.com") + "/3.0"
        auth, attempts = ("anystring", key), 0
        campaign = resume
        if not campaign:
            body = {"type": "regular", "recipients": {"list_id": str(cfg["list_id"])},
                    "settings": {"subject_line": str(payload.get("title", ""))[:150], "title": f"GrowthOS {idempotency_key[:8]} {payload.get('title', '')}"[:100],
                                 "from_name": str(cfg["from_name"]), "reply_to": str(cfg["reply_to"])}}
            if payload.get("summary"):
                body["settings"]["preview_text"] = str(payload["summary"])[:150]
            r, n, err = call("POST", base + "/campaigns", idempotent=False, json=body, auth=auth, headers={"Content-Type": "application/json"})
            attempts += n
            if r is None or r.status_code != 200:
                return failure(r, attempts, err, "API key rejected" if r is not None and r.status_code == 401 else "")
            campaign = str(r.json().get("id", ""))
            if not campaign:
                return DeliveryResult(ok=False, status_code=200, attempts=attempts, detail="Mailchimp returned no campaign id")
        r, n, err = call("PUT", f"{base}/campaigns/{campaign}/content", idempotent=True, auth=auth, headers={"Content-Type": "application/json"},
                         json={"html": f"<h1>{str(payload.get('title', '')).replace('<', '&lt;')}</h1>" + _html(payload, str(cfg.get("link_label", "Read more")))})
        attempts += n
        if r is None or r.status_code != 200:
            out = failure(r, attempts, err, "content step failed (campaign kept; retry resumes it)")
            out.provider_id = campaign
            return out
        if cfg.get("draft"):
            return DeliveryResult(ok=True, status_code=200, attempts=attempts, provider_id=campaign, publishes=False, detail="campaign drafted, not sent")
        r, n, err = call("POST", f"{base}/campaigns/{campaign}/actions/send", idempotent=False, auth=auth, headers={})
        attempts += n
        if r is not None and r.status_code == 204:
            return DeliveryResult(ok=True, status_code=204, attempts=attempts, provider_id=campaign, detail="campaign sent")
        out = failure(r, attempts, err, "send step failed (campaign kept; retry resumes it)")
        out.provider_id = campaign
        return out


for _a in (DevToAdapter(), GhostAdapter(), ButtondownAdapter(), MailchimpAdapter()):
    register(_a)
