"""Parinita Vaak: render an approved release as governed audio.

GrowthOS decides *what* may be said (evidence, sentence accounting, approval). Vaak decides whether its voice may
say it (consent, envelope, its own policy checks) and proves that it did (session manifest, anchoring). This
adapter joins the two: only copy that has passed the gate is ever sent to Vaak, and the manifest hash Vaak
returns is stored on the delivery record and on the content item next to the audio.

Flow (vaakd owner API):  open session -> [disclose on call channels] -> speak each paragraph -> close -> anchor.
The audio is written under MEDIA_DIR and served from /media, so Podcast RSS and the podcast-host adapters can
use it as the episode enclosure. Rendering does not mark the release as sent.

Built against the vaakd owner API routes as of the reference daemon (POST /twins/{id}/sessions,
/sessions/{id}/speak -> audio/L16, /sessions/{id}/close -> manifest, /anchor). If your vaakd build moved a route
or added authentication, set config.routes / config.bearer_token_env; no code change is needed.
"""
import hashlib
import io
import os
import re
import wave
from urllib.parse import quote

from ..config import settings
from . import Adapter, DeliveryResult, register
from ._common import call, failure, secret

ROUTES = {"open": "/twins/{twin_id}/sessions", "disclose": "/sessions/{session_id}/disclose", "speak": "/sessions/{session_id}/speak",
          "close": "/sessions/{session_id}/close", "anchor": "/anchor"}
_URL = re.compile(r"https?://\S+")


def media_filename(content_id: str, hash12: str) -> str:
    return f"{hashlib.sha256(content_id.encode()).hexdigest()[:24]}.{hash12}.wav"


def spoken_segments(payload: dict, max_chars: int) -> list[str]:
    """What Vaak is asked to say: the headline, the summary, then each paragraph. Links and separators are not spoken."""
    parts = [payload["title"], payload.get("summary") or ""] + re.split(r"\r?\n", payload.get("body") or "")
    out, used = [], 0
    for p in parts:
        p = _URL.sub("", p).strip()
        if not p or set(p) <= set("#*-_=~ "):
            continue
        if used + len(p) > max_chars:
            break
        out.append(p)
        used += len(p)
    return out


class VaakAdapter(Adapter):
    protocols = {"vaak"}

    def check_config(self, url, cfg):
        if not cfg.get("twin_id"):
            return "vaak endpoints need the vaakd URL and config.twin_id (the enrolled voice that will speak)"
        if cfg.get("routes") is not None and (not isinstance(cfg["routes"], dict) or set(cfg["routes"]) - set(ROUTES)):
            return f"config.routes may only override: {', '.join(ROUTES)}"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        if not settings.media_dir:
            return DeliveryResult(ok=False, attempts=0, detail="MEDIA_DIR is not configured; GrowthOS has nowhere to keep rendered audio")
        segments = spoken_segments(payload, int(cfg.get("max_chars", 20000)))
        if not segments:
            return DeliveryResult(ok=False, attempts=0, detail="nothing to speak")
        base, routes = endpoint.url.rstrip("/"), {**ROUTES, **(cfg.get("routes") or {})}
        headers = {"Content-Type": "application/json"}
        if cfg.get("bearer_token_env"):
            headers["Authorization"] = f"Bearer {secret(cfg, 'bearer_token_env')}"
        twin, attempts = str(cfg["twin_id"]), 0

        def post(route, body=None, **ids):
            nonlocal attempts
            r, n, err = call("POST", base + routes[route].format(twin_id=quote(twin, safe=""), **ids), idempotent=False, json=body or {}, headers=headers)
            attempts += n
            return r, err

        def refused(r, err, step):
            res = failure(r, attempts, err, f"Vaak refused to {step}")
            try:  # vaakd explains refusals as {"error": "..."}: surface that, it is the useful part
                res.detail = f"Vaak refused to {step}: {r.json()['error']}"[:500]
            except Exception:  # noqa: BLE001
                pass
            return res

        opening = {"verb": cfg.get("verb", "speak_public"), "channel": cfg.get("channel", "local"),
                   "language": (payload.get("locale") or "en")[:2], "presence_checked": bool(cfg.get("presence_checked", False))}
        if cfg.get("register"):
            opening["register"] = cfg["register"]
        r, err = post("open", opening)
        if r is None or r.status_code != 200:
            return refused(r, err, "open a voice session")
        sid = quote(str(r.json()["session_id"]), safe="")

        pcm, rate = bytearray(), 16000
        if opening["channel"] == "call":
            post("disclose", session_id=sid)
        for text in segments:
            r, err = post("speak", {"text": text, **({"prosody": cfg["prosody"]} if isinstance(cfg.get("prosody"), dict) else {})}, session_id=sid)
            if r is None or r.status_code != 200:
                post("close", session_id=sid)  # never leave a session open; the manifest records what was said before the refusal
                return refused(r, err, "speak this copy")
            m = re.search(r"rate=(\d+)", r.headers.get("content-type", ""))
            rate = int(m.group(1)) if m else rate
            pcm.extend(r.content)
        r, err = post("close", session_id=sid)
        if r is None or r.status_code != 200:
            return refused(r, err, "close the session")
        manifest = r.json()
        root = ""
        if cfg.get("anchor", True):
            r, err = post("anchor")
            root = str(r.json().get("root", "")) if r is not None and r.status_code == 200 else ""

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(pcm))
        hash12 = payload["content_hash"][:12]
        os.makedirs(settings.media_dir, exist_ok=True)
        path = os.path.join(settings.media_dir, media_filename(payload["id"], hash12))
        with open(path + ".part", "wb") as f:
            f.write(buf.getvalue())
        os.replace(path + ".part", path)
        seconds = len(pcm) // 2 // rate
        artifacts = {"audio_url": f"{settings.public_base_url.rstrip('/')}/media/{quote(payload['id'], safe='')}/{hash12}.wav",
                     "audio_type": "audio/wav", "audio_bytes": len(buf.getvalue()), "audio_duration": f"{seconds // 60:02d}:{seconds % 60:02d}",
                     "vaak": {"twin_id": twin, "session_id": manifest.get("session_id", ""), "manifest_hash": manifest.get("manifest_hash", ""),
                              "content_digest": manifest.get("content_digest", ""), "anchored_root": root, "rendered_hash": payload["content_hash"]}}
        return DeliveryResult(ok=True, status_code=200, attempts=attempts, provider_id=f"manifest:{manifest.get('manifest_hash', '')}",
                              publishes=False, artifacts=artifacts,
                              detail=f"rendered {len(segments)} segment(s), {artifacts['audio_duration']} of audio" + ("" if root or not cfg.get("anchor", True) else "; anchoring did not confirm"))


register(VaakAdapter())
