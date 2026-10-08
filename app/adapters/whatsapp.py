"""WhatsApp: template messages through the WhatsApp Business Platform Cloud API.

  POST https://graph.facebook.com/<version>/<phone-number-id>/messages
       {"messaging_product": "whatsapp", "to": ..., "type": "template", "template": {name, language, components}}

What WhatsApp allows shapes this adapter:
  * A business may only start a conversation with a pre-approved template. Free-form text is allowed only inside
    the 24-hour window after the person last wrote to you, which a release desk cannot rely on. So this adapter
    sends templates only, and fills the template's variables with governed release fields.
  * There is no public API for posting to a WhatsApp Channel; this sends to individual numbers or groups.
  * Recipients must have opted in. That consent is yours to hold; GrowthOS only sends to the list you configure.

The template's fixed wording is approved in WhatsApp Manager and never passes the GrowthOS gate. Keep it neutral
(for example "{{1}}\n{{2}}\nRead more: {{3}}") so that every claim a reader sees comes from the release itself.

Recipients are personal data, so they live in a GROWTHOS_SECRET_* variable (comma-separated), not in endpoint config.
"""
import re

from ..netguard import secret_from_env
from . import Adapter, DeliveryResult, register
from ._common import base_url, call, compose, failure, secret

FIELDS = ("title", "summary", "cta_url", "text", "content_id")
MAX_RECIPIENTS = 100
_HINTS = {190: "access token expired or revoked", 131047: "outside the 24-hour window; only templates can be sent",
          132001: "template name or language does not exist or is not approved", 132000: "number of template parameters does not match the template",
          131026: "recipient cannot receive this message (not on WhatsApp, or has not accepted the latest terms)",
          131056: "too many messages to this recipient in a short time", 130429: "rate limit reached"}


def _param(value: str, limit: int) -> str:
    # Template variables may not contain newlines, tabs or runs of more than four spaces.
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


class WhatsAppAdapter(Adapter):
    protocols = {"whatsapp"}

    def check_config(self, url, cfg):
        if not str(cfg.get("phone_number_id", "")).isdigit():
            return "whatsapp endpoints need config.phone_number_id (the numeric sender id from WhatsApp Manager)"
        for key in ("bearer_token_env", "recipients_env"):
            if not cfg.get(key):
                return f"whatsapp endpoints need config.{key}"
        if not re.fullmatch(r"[a-z0-9_]{1,512}", str(cfg.get("template", ""))):
            return "whatsapp endpoints need config.template (the approved template's name: lowercase letters, digits, underscores)"
        params = cfg.get("body_parameters", ["title", "cta_url"])
        if not isinstance(params, list) or [p for p in params if p not in FIELDS]:
            return f"config.body_parameters must list release fields in template order; available: {', '.join(FIELDS)}"
        if cfg.get("api_version") and not re.fullmatch(r"v\d{1,3}\.\d", str(cfg["api_version"])):
            return "config.api_version must look like v25.0"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        token = secret(cfg, "bearer_token_env")
        raw = secret_from_env(str(cfg["recipients_env"]))
        recipients = [r.strip() for r in raw.split(",") if r.strip()]
        if not recipients:
            raise ValueError(f"secret {cfg['recipients_env']} is not set or lists no recipients")
        if len(recipients) > MAX_RECIPIENTS:
            raise ValueError(f"{len(recipients)} recipients configured; this adapter sends to at most {MAX_RECIPIENTS}. Use a campaign tool for larger audiences.")
        limit = int(cfg.get("max_param_chars", 300))
        values = {"title": payload["title"], "summary": payload.get("summary", ""), "cta_url": payload.get("cta_url", ""),
                  "content_id": payload["id"], "text": compose(payload, "whatsapp", limit, text_source=cfg.get("text_source", "auto"))}
        params = [{"type": "text", "text": _param(values[f], limit)} for f in cfg.get("body_parameters", ["title", "cta_url"])]
        template = {"name": cfg["template"], "language": {"code": str(cfg.get("language", "en_US"))},
                    **({"components": [{"type": "body", "parameters": params}]} if params else {})}
        url = f"{base_url('whatsapp', 'https://graph.facebook.com')}/{cfg.get('api_version', 'v25.0')}/{cfg['phone_number_id']}/messages"
        # A retry continues after the last recipient that was reached, so nobody gets the release twice.
        done = int(resume.split(":", 1)[1]) if resume.startswith("sent:") and resume.split(":", 1)[1].isdigit() else 0
        attempts = 0
        for i, to in enumerate(recipients):
            if i < done:
                continue
            r, n, err = call("POST", url, idempotent=False, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                             json={"messaging_product": "whatsapp", "recipient_type": "group" if cfg.get("recipient_type") == "group" else "individual",
                                   "to": to, "type": "template", "template": template})
            attempts += n
            if r is None or r.status_code != 200 or not (r.json().get("messages") or [{}])[0].get("id"):
                res = failure(r, attempts, err)
                try:
                    e = r.json()["error"]
                    res.detail = f"WhatsApp refused recipient {i + 1} of {len(recipients)}: {e.get('message', '')[:200]} (code {e.get('code')})" + (
                        f" - {_HINTS[e.get('code')]}" if e.get("code") in _HINTS else "")
                except Exception:  # noqa: BLE001
                    res.detail = f"recipient {i + 1} of {len(recipients)}: {res.detail}"
                res.detail = res.detail.replace(to, "<recipient>")   # never write a phone number into the delivery record
                res.provider_id = f"sent:{i}"
                return res
        return DeliveryResult(ok=True, status_code=200, attempts=attempts, provider_id=f"sent:{len(recipients)}",
                              detail=f"template '{cfg['template']}' sent to {len(recipients)} recipient(s)")


register(WhatsAppAdapter())
