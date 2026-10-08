"""More team/community messaging: Google Chat, Mattermost, Matrix, Zulip.

  Google Chat  POST <space webhook URL>                                       {"text": ...}; the URL is the credential
  Mattermost   POST <incoming webhook URL>                                    {"text": ...}; the URL is the credential
  Matrix       PUT  /_matrix/client/v3/rooms/{room}/send/m.room.message/{txn} txn = delivery id, so Matrix de-duplicates
                                                                              retries itself (fully idempotent)
  Zulip        POST /api/v1/messages                                          bot email + API key (HTTP Basic)
"""
from urllib.parse import quote

from . import Adapter, DeliveryResult, register
from ._common import call, compose, failure, secret


class GoogleChatAdapter(Adapter):
    protocols = {"google_chat"}

    def check_config(self, url, cfg):
        return "" if cfg.get("webhook_url_env") else "google_chat endpoints need config.webhook_url_env (space webhook URL, stored as a secret)"

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        text = compose(payload, "google_chat", int(cfg.get("max_chars", 4000)), text_source=cfg.get("text_source", "auto"))
        r, n, err = call("POST", secret(cfg, "webhook_url_env"), idempotent=False, json={"text": text}, headers={"Content-Type": "application/json; charset=UTF-8"})
        if r is not None and r.status_code == 200:
            return DeliveryResult(ok=True, status_code=200, attempts=n, provider_id=str(r.json().get("name", ""))[:300])
        return failure(r, n, err)


class MattermostAdapter(Adapter):
    protocols = {"mattermost"}

    def check_config(self, url, cfg):
        return "" if cfg.get("webhook_url_env") else "mattermost endpoints need config.webhook_url_env (incoming webhook URL, stored as a secret)"

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        text = compose(payload, "mattermost", int(cfg.get("max_chars", 16000)), text_source=cfg.get("text_source", "auto"))
        body = {"text": text}
        if cfg.get("channel"):
            body["channel"] = str(cfg["channel"])
        if cfg.get("username"):
            body["username"] = str(cfg["username"])
        r, n, err = call("POST", secret(cfg, "webhook_url_env"), idempotent=False, json=body, headers={"Content-Type": "application/json"})
        if r is not None and r.status_code == 200:
            return DeliveryResult(ok=True, status_code=200, attempts=n, detail="accepted by the Mattermost webhook")
        return failure(r, n, err)


class MatrixAdapter(Adapter):
    protocols = {"matrix"}

    def check_config(self, url, cfg):
        if not url:
            return "matrix endpoints need the homeserver URL"
        if not str(cfg.get("room_id", "")).startswith("!") or not cfg.get("access_token_env"):
            return "matrix endpoints need config.room_id (!room:server) and config.access_token_env"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        text = compose(payload, "matrix", int(cfg.get("max_chars", 16000)), text_source=cfg.get("text_source", "auto"))
        url = f"{endpoint.url.rstrip('/')}/_matrix/client/v3/rooms/{quote(str(cfg['room_id']), safe='')}/send/m.room.message/{quote(idempotency_key, safe='')}"
        r, n, err = call("PUT", url, idempotent=True, json={"msgtype": "m.text", "body": text},
                         headers={"Authorization": f"Bearer {secret(cfg, 'access_token_env')}", "Content-Type": "application/json"})
        if r is not None and r.status_code == 200:
            return DeliveryResult(ok=True, status_code=200, attempts=n, provider_id=str(r.json().get("event_id", ""))[:300])
        hint = {401: "access token rejected", 403: "the bot is not joined to the room"}.get(r.status_code if r is not None else 0, "")
        return failure(r, n, err, hint)


class ZulipAdapter(Adapter):
    protocols = {"zulip"}

    def check_config(self, url, cfg):
        if not url:
            return "zulip endpoints need the realm URL"
        if not cfg.get("bot_email") or not cfg.get("api_key_env") or not cfg.get("stream"):
            return "zulip endpoints need config.bot_email, config.api_key_env and config.stream"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        text = compose(payload, "zulip", int(cfg.get("max_chars", 10000)), text_source=cfg.get("text_source", "auto"))
        form = {"type": "stream", "to": str(cfg["stream"]), "topic": str(cfg.get("topic") or payload.get("title", ""))[:60], "content": text}
        r, n, err = call("POST", endpoint.url.rstrip("/") + "/api/v1/messages", idempotent=False, data=form,
                         auth=(str(cfg["bot_email"]), secret(cfg, "api_key_env")), headers={})
        if r is not None and r.status_code == 200 and r.json().get("result") == "success":
            return DeliveryResult(ok=True, status_code=200, attempts=n, provider_id=str(r.json().get("id", ""))[:300])
        return failure(r, n, err)


for _a in (GoogleChatAdapter(), MattermostAdapter(), MatrixAdapter(), ZulipAdapter()):
    register(_a)
