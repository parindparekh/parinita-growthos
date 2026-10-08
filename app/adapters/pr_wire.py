"""PR wire adapter.

The major wires (PR Newswire, Business Wire, GlobeNewswire) do not publish a self-serve submission API:
releases go in through the wire's portal, its editorial desk, or an API made available under contract.
This adapter therefore does not pretend to know any wire's private API. It builds one wire-ready release
package and hands it over in one of two ways:

  mode "email"  send the formatted release to the wire's editorial/submission address over SMTP
  mode "api"    POST the package to the endpoint in your wire contract, using a field map you supply

Either way the wire's own editorial review still applies before anything is distributed.
"""
import json
from datetime import datetime, timezone

from . import Adapter, DeliveryResult, register
from ._common import call, failure, secret
from .smtp import send_mail

PACKAGE_FIELDS = ("headline", "subheadline", "dateline", "body", "contact", "cta_url", "release_text",
                  "release_at", "locale", "content_id", "content_hash", "sources")


def build_package(payload: dict, cfg: dict) -> dict:
    """Wire-ready release: label, headline, dateline + body, media contact, end mark.

    The adapter adds structure only. Every sentence of prose comes from the governed content, so the
    company boilerplate ("About ...") belongs in the body where the gate can see it, not in endpoint config."""
    when = datetime.now(timezone.utc)
    city = str(cfg.get("dateline_city", "")).strip()
    dateline = f"{city.upper() + ', ' if city else ''}{when.strftime('%B')} {when.day}, {when.year}"
    contact = cfg.get("contact") or {}
    contact_text = "\n".join(str(contact[k]) for k in ("name", "title", "email", "phone") if contact.get(k))
    sources = [s["uri"] for c in payload.get("claims", []) for s in c.get("sources", []) if s.get("uri", "").startswith("http")]
    lines = [str(cfg.get("release_label", "FOR IMMEDIATE RELEASE")), "", payload["title"]]
    if payload.get("summary"):
        lines += [payload["summary"]]
    lines += ["", f"{dateline} -- {payload['body'].strip()}"]
    if payload.get("cta_url"):
        lines += ["", payload["cta_url"]]
    if contact_text:
        lines += ["", "Media contact:", contact_text]
    lines += ["", "###"]
    return {"headline": payload["title"], "subheadline": payload.get("summary", ""), "dateline": dateline,
            "body": payload["body"], "contact": contact, "cta_url": payload.get("cta_url", ""),
            "release_text": "\n".join(lines), "release_at": str(cfg.get("release_at", "immediate")),
            "locale": payload.get("locale", ""), "content_id": payload["id"], "content_hash": payload.get("content_hash", ""),
            "sources": sorted(set(sources))}


class PrWireAdapter(Adapter):
    protocols = {"pr_wire"}

    def check_config(self, url, cfg):
        mode = cfg.get("mode", "api")
        if mode == "email":
            return "" if cfg.get("to") else "pr_wire email mode needs config.to (the wire desk address)"
        if mode != "api":
            return "pr_wire config.mode must be 'api' or 'email'"
        fm = cfg.get("field_map")
        if not isinstance(fm, dict) or not fm:
            return "pr_wire api mode needs config.field_map: {wire field name: package field}"
        bad = sorted(str(v) for v in fm.values() if v not in PACKAGE_FIELDS)
        if bad:
            return f"field_map refers to unknown package field(s) {bad}; available: {', '.join(PACKAGE_FIELDS)}"
        auth = cfg.get("auth") or {}
        if auth.get("scheme", "bearer") not in {"bearer", "header", "basic"} or not auth.get("secret_env"):
            return "pr_wire api mode needs config.auth: {scheme: bearer|header|basic, secret_env: GROWTHOS_SECRET_...}"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        package = build_package(payload, cfg)
        if cfg.get("mode", "api") == "email":
            to = cfg["to"] if isinstance(cfg["to"], list) else [cfg["to"]]
            return send_mail(to, str(cfg.get("subject_prefix", "Press release: ")) + package["headline"],
                             package["release_text"], idempotency_key, package["content_hash"])
        auth_cfg = cfg["auth"]
        token = secret(auth_cfg, "secret_env")
        headers, auth = {"Content-Type": "application/json", "Idempotency-Key": idempotency_key}, None
        scheme = auth_cfg.get("scheme", "bearer")
        if scheme == "bearer":
            headers["Authorization"] = f"Bearer {token}"
        elif scheme == "header":
            headers[str(auth_cfg.get("header", "X-Api-Key"))] = token
        else:
            auth = (str(auth_cfg.get("username", "")), token)
        body = {**(cfg.get("static") or {}), **{wire_field: package[src] for wire_field, src in cfg["field_map"].items()}}
        # Not assumed idempotent: a wire submission that might have been accepted is never re-sent automatically.
        r, n, err = call("POST", endpoint.url, idempotent=False, json=body, headers=headers, auth=auth)
        if r is not None and 200 <= r.status_code < 300:
            try:
                rid = str(r.json().get(str(cfg.get("id_field", "id")), ""))
            except (json.JSONDecodeError, AttributeError):
                rid = ""
            return DeliveryResult(ok=True, status_code=r.status_code, attempts=n, provider_id=rid[:300],
                                  detail="submitted to the wire; distribution is subject to the wire's editorial review")
        return failure(r, n, err)


register(PrWireAdapter())
