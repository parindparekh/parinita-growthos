"""Meta platforms: Facebook Pages, Instagram, Threads (Graph API shapes as documented October 2026).

  Facebook   POST /{page_id}/feed                          message (+ link). Page access token with pages_manage_posts.
  Instagram  POST /{ig_user_id}/media  -> /media_publish   image container then publish. Needs a public image URL;
                                                           Instagram has no text-only post.
  Threads    POST /{user_id}/threads   -> /threads_publish TEXT container (optional link attachment) then publish.

Two-step providers record the container id as the delivery's resume point: a failed publish step is resumed with the
same container instead of creating a second one.
"""
import re

from . import Adapter, DeliveryResult, register
from ._common import base_url, call, compose, failure, secret

_NUM = re.compile(r"^\d{3,32}$")
GRAPH_VERSION = "v21.0"


def image_url(payload: dict, cfg: dict) -> str:
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    u = str(meta.get("image_url") or cfg.get("image_url") or "")
    return u if re.match(r"^https://", u, re.I) else ""


def _graph(cfg: dict, host_key: str, default: str) -> str:
    return base_url(host_key, default) + "/" + str(cfg.get("graph_version") or GRAPH_VERSION)


def _graph_error(r) -> str:
    try:
        e = (r.json() or {}).get("error") or {}
        return f"{e.get('type', 'GraphError')} {e.get('code', '')}: {e.get('message', '')}".strip()[:200]
    except ValueError:
        return ""


class FacebookPageAdapter(Adapter):
    protocols = {"facebook"}

    def check_config(self, url, cfg):
        if not _NUM.match(str(cfg.get("page_id", ""))):
            return "facebook endpoints need config.page_id (numeric Page id)"
        if not cfg.get("page_token_env"):
            return "facebook endpoints need config.page_token_env (Page access token with pages_manage_posts)"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        text = compose(payload, "facebook", int(cfg.get("max_chars", 5000)), text_source=cfg.get("text_source", "auto"))
        link = payload.get("cta_url") or ""
        if link and text.endswith(link):
            text = text[: -len(link)].rstrip()  # the link rides in its own field and renders as a preview card
        form = {"message": text, "access_token": secret(cfg, "page_token_env"), "published": "false" if cfg.get("unpublished") else "true"}
        if link:
            form["link"] = link
        r, n, err = call("POST", f"{_graph(cfg, 'meta', 'https://graph.facebook.com')}/{cfg['page_id']}/feed", idempotent=False, data=form, headers={})
        if r is not None and r.status_code == 200:
            return DeliveryResult(ok=True, status_code=200, attempts=n, provider_id=str(r.json().get("id", ""))[:300])
        hint = {190: "Page token expired or invalid", 200: "the token lacks pages_manage_posts / the user is not a Page admin",
                368: "the Page is restricted by Facebook"}.get(_code(r), "")
        return failure(r, n, err, (_graph_error(r) + (" - " + hint if hint else "")) if r is not None else "")


def _code(r) -> int:
    try:
        return int(((r.json() or {}).get("error") or {}).get("code", 0)) if r is not None else 0
    except (ValueError, TypeError):
        return 0


class InstagramAdapter(Adapter):
    protocols = {"instagram"}

    def check_config(self, url, cfg):
        if not _NUM.match(str(cfg.get("ig_user_id", ""))):
            return "instagram endpoints need config.ig_user_id (Instagram professional account id)"
        if not cfg.get("access_token_env"):
            return "instagram endpoints need config.access_token_env"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        img = image_url(payload, cfg)
        if not img:
            return DeliveryResult(ok=False, detail="Instagram needs a public https image: set metadata.public.image_url on the release (or config.image_url)")
        token = secret(cfg, "access_token_env")
        base = f"{_graph(cfg, 'meta', 'https://graph.facebook.com')}/{cfg['ig_user_id']}"
        caption = compose(payload, "instagram", int(cfg.get("max_chars", 2200)), text_source=cfg.get("text_source", "auto"))
        attempts = 0
        container = resume
        if not container:
            r, n, err = call("POST", base + "/media", idempotent=False, headers={},
                             data={"image_url": img, "caption": caption, "access_token": token})
            attempts += n
            if r is None or r.status_code != 200:
                return failure(r, attempts, err, _graph_error(r) if r is not None else "")
            container = str(r.json().get("id", ""))
            if not container:
                return DeliveryResult(ok=False, status_code=200, attempts=attempts, detail="Instagram returned no container id")
        r, n, err = call("POST", base + "/media_publish", idempotent=False, headers={},
                         data={"creation_id": container, "access_token": token})
        attempts += n
        if r is not None and r.status_code == 200:
            return DeliveryResult(ok=True, status_code=200, attempts=attempts, provider_id=str(r.json().get("id", ""))[:300])
        # Keep the container so a retry publishes it instead of creating a duplicate.
        out = failure(r, attempts, err, (_graph_error(r) + " (container kept; the retry will publish it)") if r is not None else "")
        out.provider_id = container
        return out


class ThreadsAdapter(Adapter):
    protocols = {"threads"}

    def check_config(self, url, cfg):
        if not _NUM.match(str(cfg.get("user_id", ""))):
            return "threads endpoints need config.user_id (Threads user id)"
        if not cfg.get("access_token_env"):
            return "threads endpoints need config.access_token_env"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        token = secret(cfg, "access_token_env")
        base = f"{_graph(cfg, 'threads', 'https://graph.threads.net')}/{cfg['user_id']}"
        text = compose(payload, "threads", int(cfg.get("max_chars", 500)), text_source=cfg.get("text_source", "auto"))
        attempts, container = 0, resume
        if not container:
            form = {"media_type": "TEXT", "text": text, "access_token": token}
            if payload.get("cta_url"):
                form["link_attachment"] = payload["cta_url"]
            r, n, err = call("POST", base + "/threads", idempotent=False, data=form, headers={})
            attempts += n
            if r is None or r.status_code != 200:
                return failure(r, attempts, err, _graph_error(r) if r is not None else "")
            container = str(r.json().get("id", ""))
            if not container:
                return DeliveryResult(ok=False, status_code=200, attempts=attempts, detail="Threads returned no container id")
        r, n, err = call("POST", base + "/threads_publish", idempotent=False, data={"creation_id": container, "access_token": token}, headers={})
        attempts += n
        if r is not None and r.status_code == 200:
            return DeliveryResult(ok=True, status_code=200, attempts=attempts, provider_id=str(r.json().get("id", ""))[:300])
        out = failure(r, attempts, err, (_graph_error(r) + " (container kept; the retry will publish it)") if r is not None else "")
        out.provider_id = container
        return out


for _a in (FacebookPageAdapter(), InstagramAdapter(), ThreadsAdapter()):
    register(_a)
