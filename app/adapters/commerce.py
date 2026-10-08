"""Commerce and local-business surfaces: Etsy, Shopify, Google Business Profile.

  Etsy             PUT   /v3/application/shops/{shop_id}                        mode "announcement": the shop announcement
                   PATCH /v3/application/shops/{shop_id}/listings/{listing_id}  mode "listing": title/description of an existing listing
                   (x-api-key = keystring, OAuth 2.0 bearer with shops_w / listings_w). Etsy has no "post"; governed copy
                   lands in the two text surfaces Etsy exposes. Creating listings (price, inventory, shipping) stays manual.
  Shopify          POST /admin/api/{version}/blogs/{blog_id}/articles.json       Admin API access token; blog article
  Google Business  POST /v4/accounts/{account}/locations/{location}/localPosts   "What's new" post with optional CTA
"""
import re

from . import Adapter, DeliveryResult, register
from ._common import base_url, call, compose, failure, secret
from .meta import image_url

_DIGITS = re.compile(r"^\d{1,32}$")


class EtsyAdapter(Adapter):
    protocols = {"etsy"}

    def check_config(self, url, cfg):
        if not _DIGITS.match(str(cfg.get("shop_id", ""))):
            return "etsy endpoints need config.shop_id (numeric)"
        if not cfg.get("keystring") or not cfg.get("bearer_token_env"):
            return "etsy endpoints need config.keystring (app key) and config.bearer_token_env (OAuth 2.0 token)"
        mode = cfg.get("mode") or "announcement"
        if mode not in ("announcement", "listing"):
            return "config.mode must be announcement or listing"
        if mode == "listing" and not _DIGITS.match(str(cfg.get("listing_id", ""))):
            return "etsy listing mode needs config.listing_id (numeric)"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        headers = {"x-api-key": str(cfg["keystring"]), "Authorization": f"Bearer {secret(cfg, 'bearer_token_env')}"}
        base = f"{base_url('etsy', 'https://openapi.etsy.com')}/v3/application/shops/{cfg['shop_id']}"
        mode = cfg.get("mode") or "announcement"
        if mode == "announcement":
            text = compose(payload, "etsy", int(cfg.get("max_chars", 1000)), text_source=cfg.get("text_source", "auto"))
            r, n, err = call("PUT", base, idempotent=True, data={"announcement": text}, headers=headers)
            ref = f"shop:{cfg['shop_id']}:announcement"
        else:
            desc = (payload.get("body") or payload.get("summary") or "").strip()[: int(cfg.get("max_chars", 100000))]
            r, n, err = call("PATCH", f"{base}/listings/{cfg['listing_id']}", idempotent=True, headers=headers,
                             data={"title": str(payload.get("title", ""))[:140], "description": desc})
            ref = f"listing:{cfg['listing_id']}"
        if r is not None and r.status_code == 200:
            return DeliveryResult(ok=True, status_code=200, attempts=n, provider_id=ref, detail=f"Etsy {mode} updated")
        hint = {401: "OAuth token rejected (Etsy access tokens last 1 h; refresh is not automated)",
                403: "the token lacks shops_w / listings_w, or the shop is not owned by this user"}.get(r.status_code if r is not None else 0, "")
        return failure(r, n, err, hint)


class ShopifyAdapter(Adapter):
    protocols = {"shopify"}

    def check_config(self, url, cfg):
        if not url or not re.match(r"^https?://[^/]+/?$", url):
            return "shopify endpoints need the store URL (https://<store>.myshopify.com, no path)"
        if not _DIGITS.match(str(cfg.get("blog_id", ""))) or not cfg.get("access_token_env"):
            return "shopify endpoints need config.blog_id (numeric) and config.access_token_env (Admin API token with write_content)"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        version = str(cfg.get("api_version") or "2026-07")
        lead = (payload.get("body") or payload.get("summary") or "").strip()
        html = "".join(f"<p>{p}</p>" for p in _paragraphs(lead))
        if payload.get("cta_url"):
            html += f"<p><a href=\"{payload['cta_url']}\">{str(cfg.get('link_label', 'Read more'))}</a></p>"
        article = {"title": str(payload.get("title", ""))[:255], "body_html": html, "published": not cfg.get("draft", False),
                   "author": str(cfg.get("author", "Parinita GrowthOS"))}
        if payload.get("summary"):
            article["summary_html"] = f"<p>{payload['summary']}</p>"
        tags = cfg.get("tags") or []
        if tags:
            article["tags"] = ", ".join(str(t) for t in tags[:50])
        img = image_url(payload, cfg)
        if img:
            article["image"] = {"src": img}
        r, n, err = call("POST", f"{endpoint.url.rstrip('/')}/admin/api/{version}/blogs/{cfg['blog_id']}/articles.json", idempotent=False,
                         json={"article": article}, headers={"X-Shopify-Access-Token": secret(cfg, "access_token_env"), "Content-Type": "application/json"})
        if r is not None and r.status_code in (200, 201):
            a = r.json().get("article") or {}
            return DeliveryResult(ok=True, status_code=r.status_code, attempts=n, provider_id=str(a.get("admin_graphql_api_id") or a.get("id", ""))[:300])
        hint = {401: "Admin API token rejected", 403: "the token lacks write_content", 404: "blog_id not found in this store"}.get(r.status_code if r is not None else 0, "")
        return failure(r, n, err, hint)


def _paragraphs(text: str) -> list[str]:
    esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return [p.strip().replace("\n", "<br>") for p in re.split(r"\n\s*\n", esc) if p.strip()]


class GoogleBusinessAdapter(Adapter):
    protocols = {"google_business"}

    def check_config(self, url, cfg):
        if not _DIGITS.match(str(cfg.get("account_id", ""))) or not _DIGITS.match(str(cfg.get("location_id", ""))):
            return "google_business endpoints need config.account_id and config.location_id (numeric)"
        if not cfg.get("bearer_token_env"):
            return "google_business endpoints need config.bearer_token_env (OAuth 2.0 token with business.manage)"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        text = compose(payload, "google_business", int(cfg.get("max_chars", 1500)), text_source=cfg.get("text_source", "auto"))
        link = payload.get("cta_url") or ""
        if link and text.endswith(link):
            text = text[: -len(link)].rstrip()
        body = {"languageCode": (payload.get("locale") or "en")[:2], "summary": text, "topicType": "STANDARD"}
        if link:
            body["callToAction"] = {"actionType": str(cfg.get("action_type", "LEARN_MORE")), "url": link}
        img = image_url(payload, cfg)
        if img:
            body["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": img}]
        r, n, err = call("POST", f"{base_url('google_business', 'https://mybusiness.googleapis.com')}/v4/accounts/{cfg['account_id']}/locations/{cfg['location_id']}/localPosts",
                         idempotent=False, json=body, headers={"Authorization": f"Bearer {secret(cfg, 'bearer_token_env')}", "Content-Type": "application/json"})
        if r is not None and r.status_code == 200:
            return DeliveryResult(ok=True, status_code=200, attempts=n, provider_id=str(r.json().get("name", ""))[:300])
        hint = {401: "OAuth token expired (Google access tokens last 1 h; refresh is not automated)",
                403: "the account lacks business.manage on this location"}.get(r.status_code if r is not None else 0, "")
        return failure(r, n, err, hint)


for _a in (EtsyAdapter(), ShopifyAdapter(), GoogleBusinessAdapter()):
    register(_a)
