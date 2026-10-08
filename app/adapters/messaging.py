"""Team and community messaging: Slack, Microsoft Teams, Discord, Telegram.

  Slack     POST /api/chat.postMessage                 bot token (chat:write). Slack answers 200 with {"ok": false} on errors.
  Teams     POST <Workflows webhook URL>               Adaptive Card in a {"type":"message","attachments":[...]} wrapper.
                                                       (Office 365 connectors are retired; Workflows is the supported path.)
  Discord   POST <webhook URL>?wait=true               mentions disabled so release text can never ping @everyone.
  Telegram  POST /bot<token>/sendMessage               bot must be a member/admin of the chat or channel.

For Teams and Discord the webhook URL *is* the credential, so it lives in a GROWTHOS_SECRET_* variable, not in endpoint config.
"""
from . import Adapter, DeliveryResult, register
from ._common import base_url, call, compose, failure, secret


def _slack_escape(text: str) -> str:
    # Slack treats & < > as control characters in message text.
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SlackAdapter(Adapter):
    protocols = {"slack"}

    def check_config(self, url, cfg):
        return "" if cfg.get("bearer_token_env") and cfg.get("channel") else "slack endpoints need config.bearer_token_env and config.channel"

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        text = compose(payload, "slack", int(cfg.get("max_chars", 4000)), text_source=cfg.get("text_source", "auto"))
        r, n, err = call("POST", base_url("slack", "https://slack.com") + "/api/chat.postMessage", idempotent=False,
                         json={"channel": str(cfg["channel"]), "text": _slack_escape(text), "unfurl_links": bool(cfg.get("unfurl_links", True))},
                         headers={"Authorization": f"Bearer {secret(cfg, 'bearer_token_env')}", "Content-Type": "application/json; charset=utf-8"})
        if r is None or r.status_code != 200:
            return failure(r, n, err)
        body = r.json()
        if not body.get("ok"):
            hint = {"not_in_channel": "invite the bot to the channel", "channel_not_found": "check config.channel",
                    "invalid_auth": "bot token rejected", "missing_scope": "the bot needs the chat:write scope"}.get(body.get("error", ""), "")
            return DeliveryResult(ok=False, status_code=200, attempts=n, detail=f"Slack refused: {body.get('error', 'unknown')}{' - ' + hint if hint else ''}")
        return DeliveryResult(ok=True, status_code=200, attempts=n, provider_id=f"{body.get('channel', cfg['channel'])}:{body.get('ts', '')}")


class TeamsAdapter(Adapter):
    protocols = {"teams"}

    def check_config(self, url, cfg):
        return "" if cfg.get("webhook_url_env") else "teams endpoints need config.webhook_url_env (the Workflows webhook URL, stored as a secret)"

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        blocks = [{"type": "TextBlock", "text": payload["title"], "weight": "Bolder", "size": "Medium", "wrap": True}]
        lead = (payload.get("summary") or payload.get("body") or "").strip()
        if lead:
            blocks.append({"type": "TextBlock", "text": lead[: int(cfg.get("max_chars", 3000))], "wrap": True})
        card = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4", "body": blocks}
        if payload.get("cta_url"):
            card["actions"] = [{"type": "Action.OpenUrl", "title": str(cfg.get("link_label", "Read more")), "url": payload["cta_url"]}]
        body = {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}]}
        r, n, err = call("POST", secret(cfg, "webhook_url_env"), idempotent=False, json=body, headers={"Content-Type": "application/json"})
        if r is not None and r.status_code in (200, 202):
            return DeliveryResult(ok=True, status_code=r.status_code, attempts=n, detail="accepted by the Teams workflow")
        return failure(r, n, err)


class DiscordAdapter(Adapter):
    protocols = {"discord"}

    def check_config(self, url, cfg):
        return "" if cfg.get("webhook_url_env") else "discord endpoints need config.webhook_url_env (the webhook URL, stored as a secret)"

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        text = compose(payload, "discord", int(cfg.get("max_chars", 2000)), text_source=cfg.get("text_source", "auto"))
        url = secret(cfg, "webhook_url_env")
        r, n, err = call("POST", url + ("&" if "?" in url else "?") + "wait=true", idempotent=False,
                         json={"content": text, "allowed_mentions": {"parse": []}}, headers={"Content-Type": "application/json"})
        if r is not None and r.status_code in (200, 204):
            pid = str(r.json().get("id", "")) if r.status_code == 200 and r.content else ""
            return DeliveryResult(ok=True, status_code=r.status_code, attempts=n, provider_id=pid)
        return failure(r, n, err)


class TelegramAdapter(Adapter):
    protocols = {"telegram"}

    def check_config(self, url, cfg):
        return "" if cfg.get("bot_token_env") and cfg.get("chat_id") else "telegram endpoints need config.bot_token_env and config.chat_id"

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        text = compose(payload, "telegram", int(cfg.get("max_chars", 4096)), text_source=cfg.get("text_source", "auto"))
        url = f"{base_url('telegram', 'https://api.telegram.org')}/bot{secret(cfg, 'bot_token_env')}/sendMessage"
        r, n, err = call("POST", url, idempotent=False, json={"chat_id": cfg["chat_id"], "text": text}, headers={"Content-Type": "application/json"})
        if r is not None and r.status_code == 200 and r.json().get("ok"):
            return DeliveryResult(ok=True, status_code=200, attempts=n, provider_id=f"{cfg['chat_id']}:{r.json()['result'].get('message_id', '')}")
        res = failure(r, n, err)
        res.detail = res.detail.replace(secret(cfg, "bot_token_env"), "<token>")  # the token is part of the URL; never echo it
        return res


for _a in (SlackAdapter(), TeamsAdapter(), DiscordAdapter(), TelegramAdapter()):
    register(_a)
