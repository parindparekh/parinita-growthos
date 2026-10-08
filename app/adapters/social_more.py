"""More social networks: Pinterest, TikTok (photo posts), Tumblr, Lemmy.

  Pinterest  POST /v5/pins                                   board_id, title, description, link, media_source image_url
  TikTok     POST /v2/post/publish/content/init/             photo post pulled from public image URLs (Content Posting API,
                                                             video.publish/photo scope; text-only posts do not exist)
  Tumblr     POST /v2/blog/{blog}/posts                      Neue Post Format text + link blocks, OAuth 2.0 bearer
  Lemmy      POST /api/v3/user/login -> POST /api/v3/post    any Lemmy instance (fediverse link aggregator)

None of these honour an idempotency key, so the create step is never retried after it may have been processed.
"""
import re

from . import Adapter, DeliveryResult, register
from ._common import base_url, call, compose, failure, secret
from .meta import image_url


def _images(payload: dict, cfg: dict) -> list[str]:
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    urls = meta.get("image_urls") if isinstance(meta.get("image_urls"), list) else []
    urls = [str(u) for u in urls if re.match(r"^https://", str(u), re.I)]
    one = image_url(payload, cfg)
    return urls or ([one] if one else [])


class PinterestAdapter(Adapter):
    protocols = {"pinterest"}

    def check_config(self, url, cfg):
        if not cfg.get("board_id") or not cfg.get("bearer_token_env"):
            return "pinterest endpoints need config.board_id and config.bearer_token_env (pins:write)"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        img = image_url(payload, cfg)
        if not img:
            return DeliveryResult(ok=False, detail="Pinterest needs a public https image: set metadata.public.image_url on the release (or config.image_url)")
        desc = compose(payload, "pinterest", int(cfg.get("max_chars", 800)), text_source=cfg.get("text_source", "auto"))
        body = {"board_id": str(cfg["board_id"]), "title": str(payload.get("title", ""))[:100], "description": desc,
                "media_source": {"source_type": "image_url", "url": img}}
        link = payload.get("cta_url") or ""
        if link:
            body["link"] = link
        if cfg.get("alt_text"):
            body["alt_text"] = str(cfg["alt_text"])[:500]
        r, n, err = call("POST", base_url("pinterest", "https://api.pinterest.com") + "/v5/pins", idempotent=False, json=body,
                         headers={"Authorization": f"Bearer {secret(cfg, 'bearer_token_env')}", "Content-Type": "application/json"})
        if r is not None and r.status_code == 201:
            return DeliveryResult(ok=True, status_code=201, attempts=n, provider_id=str(r.json().get("id", ""))[:300])
        hint = {401: "token rejected (Pinterest user tokens expire; refresh is not automated)",
                403: "the app lacks pins:write or the board is not owned by this user"}.get(r.status_code if r is not None else 0, "")
        return failure(r, n, err, hint)


class TikTokAdapter(Adapter):
    protocols = {"tiktok"}

    def check_config(self, url, cfg):
        if not cfg.get("access_token_env"):
            return "tiktok endpoints need config.access_token_env (Content Posting API user token)"
        if cfg.get("privacy_level") not in (None, "", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"):
            return "config.privacy_level must be a TikTok privacy level"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        imgs = _images(payload, cfg)
        if not imgs:
            return DeliveryResult(ok=False, detail="TikTok photo posts need public https images: set metadata.public.image_urls (or image_url) on the release")
        text = compose(payload, "tiktok", int(cfg.get("max_chars", 4000)), text_source=cfg.get("text_source", "auto"))
        body = {"post_info": {"title": str(payload.get("title", ""))[:90], "description": text,
                              "privacy_level": str(cfg.get("privacy_level") or "SELF_ONLY"),  # safe default: creator reviews before public
                              "disable_comment": bool(cfg.get("disable_comment", False)), "auto_add_music": bool(cfg.get("auto_add_music", False))},
                "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0, "photo_images": imgs[:35]},
                "post_mode": "DIRECT_POST" if cfg.get("direct_post") else "MEDIA_UPLOAD", "media_type": "PHOTO"}
        r, n, err = call("POST", base_url("tiktok", "https://open.tiktokapis.com") + "/v2/post/publish/content/init/", idempotent=False, json=body,
                         headers={"Authorization": f"Bearer {secret(cfg, 'access_token_env')}", "Content-Type": "application/json; charset=UTF-8"})
        if r is not None and r.status_code == 200:
            j = r.json()
            code = str((j.get("error") or {}).get("code", "ok"))
            if code == "ok":
                mode = "sent to the creator's inbox for review" if body["post_mode"] == "MEDIA_UPLOAD" else "posted directly"
                return DeliveryResult(ok=True, status_code=200, attempts=n, provider_id=str((j.get("data") or {}).get("publish_id", ""))[:300], detail=mode)
            return DeliveryResult(ok=False, status_code=200, attempts=n, detail=f"TikTok refused: {code} {(j.get('error') or {}).get('message', '')}"[:300])
        hint = {401: "access token expired (TikTok user tokens last 24 h; refresh is not automated)",
                403: "the app is not approved for the Content Posting API photo scope, or the image domain is not verified"}.get(r.status_code if r is not None else 0, "")
        return failure(r, n, err, hint)


class TumblrAdapter(Adapter):
    protocols = {"tumblr"}

    def check_config(self, url, cfg):
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,100}", str(cfg.get("blog", ""))) or not cfg.get("bearer_token_env"):
            return "tumblr endpoints need config.blog (blog identifier) and config.bearer_token_env (OAuth 2.0)"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        lead = (payload.get("summary") or payload.get("body") or "").strip()[: int(cfg.get("max_chars", 4096))]
        content = [{"type": "text", "subtype": "heading1", "text": str(payload.get("title", ""))}]
        if lead:
            content.append({"type": "text", "text": lead})
        if payload.get("cta_url"):
            content.append({"type": "link", "url": payload["cta_url"]})
        body = {"content": content, "state": str(cfg.get("state", "published")),
                "tags": ",".join(str(t) for t in (cfg.get("tags") or [])[:30])}
        r, n, err = call("POST", f"{base_url('tumblr', 'https://api.tumblr.com')}/v2/blog/{cfg['blog']}/posts", idempotent=False, json=body,
                         headers={"Authorization": f"Bearer {secret(cfg, 'bearer_token_env')}", "Content-Type": "application/json"})
        if r is not None and r.status_code == 201:
            return DeliveryResult(ok=True, status_code=201, attempts=n, provider_id=str((r.json().get("response") or {}).get("id", ""))[:300])
        return failure(r, n, err, "Tumblr OAuth 2.0 token rejected" if r is not None and r.status_code == 401 else "")


class LemmyAdapter(Adapter):
    protocols = {"lemmy"}

    def check_config(self, url, cfg):
        if not url:
            return "lemmy endpoints need the instance URL"
        if not str(cfg.get("community_id", "")).isdigit() or not cfg.get("username") or not cfg.get("password_env"):
            return "lemmy endpoints need config.community_id (numeric), config.username and config.password_env"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        inst = endpoint.url.rstrip("/")
        r, n, err = call("POST", inst + "/api/v3/user/login", idempotent=True, headers={"Content-Type": "application/json"},
                         json={"username_or_email": str(cfg["username"]), "password": secret(cfg, "password_env")})
        if r is None or r.status_code != 200 or not r.json().get("jwt"):
            return failure(r, n, err, "Lemmy sign-in failed")
        jwt = r.json()["jwt"]
        body = {"name": str(payload.get("title", ""))[:200], "community_id": int(cfg["community_id"]),
                "body": (payload.get("summary") or payload.get("body") or "")[: int(cfg.get("max_chars", 10000))], "nsfw": False}
        if payload.get("cta_url"):
            body["url"] = payload["cta_url"]
        r, n2, err = call("POST", inst + "/api/v3/post", idempotent=False, json=body,
                          headers={"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"})
        if r is not None and r.status_code == 200:
            pv = r.json().get("post_view") or {}
            return DeliveryResult(ok=True, status_code=200, attempts=n + n2 - 1, provider_id=str((pv.get("post") or {}).get("ap_id") or (pv.get("post") or {}).get("id", ""))[:300])
        return failure(r, n2, err)


for _a in (PinterestAdapter(), TikTokAdapter(), TumblrAdapter(), LemmyAdapter()):
    register(_a)
