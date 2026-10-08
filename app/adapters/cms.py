"""Newsroom / CMS: WordPress.

  WordPress  POST <site>/wp-json/wp/v2/posts    Basic auth with an application password (Users > Profile > Application Passwords).

The body is sent as escaped HTML paragraphs: release copy is text, and nothing in it is allowed to become markup on your site.
"""
import html
import re

from . import Adapter, DeliveryResult, register
from ._common import call, failure, secret

_URL = re.compile(r"(https?://[^\s<]+)")


def to_html(text: str) -> str:
    out = []
    for para in re.split(r"\n\s*\n|\r?\n", text or ""):
        para = para.strip()
        if para:
            out.append("<p>" + html.escape(para, quote=False) + "</p>")
    return "\n".join(out)


class WordPressAdapter(Adapter):
    protocols = {"wordpress"}

    def check_config(self, url, cfg):
        if not cfg.get("username") or not cfg.get("app_password_env"):
            return "wordpress endpoints need the site URL, config.username and config.app_password_env"
        if cfg.get("status", "publish") not in {"publish", "draft", "pending", "private"}:
            return "config.status must be publish, draft, pending or private"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        content = to_html(payload["body"])
        if payload.get("cta_url"):
            link = html.escape(payload["cta_url"], quote=True)
            content += f'\n<p><a href="{link}">{html.escape(str(cfg.get("link_label", "Read more")))}</a></p>'
        body = {"title": payload["title"], "content": content, "excerpt": payload.get("summary", ""), "status": cfg.get("status", "publish")}
        for key in ("categories", "tags", "author"):
            if cfg.get(key):
                body[key] = cfg[key]
        r, n, err = call("POST", endpoint.url.rstrip("/") + "/wp-json/wp/v2/posts", idempotent=False, json=body,
                         headers={"Content-Type": "application/json"}, auth=(str(cfg["username"]), secret(cfg, "app_password_env")))
        if r is not None and r.status_code == 201:
            j = r.json()
            return DeliveryResult(ok=True, status_code=201, attempts=n, provider_id=str(j.get("link") or j.get("id", ""))[:300],
                                  publishes=body["status"] == "publish")
        hint = {401: "application password rejected", 403: "this user may not create posts"}.get(r.status_code if r is not None else 0, "")
        return failure(r, n, err, hint)


register(WordPressAdapter())
