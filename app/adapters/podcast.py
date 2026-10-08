"""Podcast host adapters: Transistor and Buzzsprout.

Both hosts fetch the audio from a URL you already host (metadata.audio_url on the content item).
GrowthOS does not upload audio binaries.

  Transistor  POST /v1/episodes (creates a draft)  ->  PATCH /v1/episodes/{id}/publish     header x-api-key
  Buzzsprout  POST /api/{podcast_id}/episodes.json                                         header Authorization: Token token=...
"""
from datetime import datetime, timezone

from . import Adapter, DeliveryResult, register
from ._common import base_url, call, failure, secret


def _audio(payload: dict) -> str:
    return str((payload.get("media") or {}).get("audio_url", ""))


def _notes(payload: dict) -> str:
    body = payload.get("body") or ""
    return body + (f"\n\n{payload['cta_url']}" if payload.get("cta_url") else "")


class TransistorAdapter(Adapter):
    protocols = {"transistor"}

    def check_config(self, url, cfg):
        if not cfg.get("api_key_env") or not cfg.get("show_id"):
            return "transistor endpoints need config.api_key_env and config.show_id"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        if not _audio(payload):
            return DeliveryResult(ok=False, attempts=0, detail="content has no metadata.audio_url; a podcast episode needs hosted audio")
        api = base_url("transistor", "https://api.transistor.fm") + "/v1"
        headers = {"x-api-key": secret(cfg, "api_key_env")}
        episode_id, attempts = (resume.split(":", 1)[1] if resume.startswith("episode:") else ""), 0
        if not episode_id:
            form = {"episode[show_id]": str(cfg["show_id"]), "episode[title]": payload["title"],
                    "episode[summary]": (payload.get("summary") or payload["title"])[:500],
                    "episode[description]": _notes(payload), "episode[audio_url]": _audio(payload)}
            r, attempts, err = call("POST", api + "/episodes", idempotent=False, data=form, headers=headers)
            if r is None or r.status_code not in (200, 201):
                return failure(r, attempts, err)
            episode_id = str((r.json().get("data") or {}).get("id", ""))
            if not episode_id:
                return DeliveryResult(ok=False, status_code=r.status_code, attempts=attempts, detail="Transistor returned no episode id")
        if cfg.get("publish", True) is False:
            return DeliveryResult(ok=True, status_code=201, attempts=max(attempts, 1), provider_id=f"episode:{episode_id}", detail="created as draft")
        # Publishing an already-published episode is harmless, so this step may be retried.
        r, n, err = call("PATCH", f"{api}/episodes/{episode_id}/publish", idempotent=True,
                         data={"episode[status]": "published"}, headers=headers)
        if r is not None and r.status_code == 200:
            return DeliveryResult(ok=True, status_code=200, attempts=attempts + n, provider_id=f"episode:{episode_id}")
        res = failure(r, attempts + n, err, "episode was created as a draft but not published; retry resumes at the publish step")
        res.provider_id = f"episode:{episode_id}"  # lets the next attempt resume instead of duplicating
        return res


class BuzzsproutAdapter(Adapter):
    protocols = {"buzzsprout"}

    def check_config(self, url, cfg):
        if not cfg.get("api_token_env") or not str(cfg.get("podcast_id", "")).isdigit():
            return "buzzsprout endpoints need config.api_token_env and a numeric config.podcast_id"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        if not _audio(payload):
            return DeliveryResult(ok=False, attempts=0, detail="content has no metadata.audio_url; a podcast episode needs hosted audio")
        body = {"title": payload["title"], "description": _notes(payload), "summary": (payload.get("summary") or "")[:500],
                "audio_url": _audio(payload), "private": bool(cfg.get("private", False)), "guid": f"growthos-{payload['id']}"}
        if cfg.get("publish", True) is not False:
            body["published_at"] = datetime.now(timezone.utc).isoformat()
        if cfg.get("artist"):
            body["artist"] = str(cfg["artist"])
        url = f"{base_url('buzzsprout', 'https://www.buzzsprout.com')}/api/{cfg['podcast_id']}/episodes.json"
        r, n, err = call("POST", url, idempotent=False, json=body,
                         headers={"Authorization": f"Token token={secret(cfg, 'api_token_env')}", "Content-Type": "application/json"})
        if r is not None and r.status_code in (200, 201):
            return DeliveryResult(ok=True, status_code=r.status_code, attempts=n, provider_id=f"episode:{r.json().get('id', '')}")
        return failure(r, n, err)


for _a in (TransistorAdapter(), BuzzsproutAdapter()):
    register(_a)
