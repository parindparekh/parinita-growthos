"""Optional OpenAI-compatible model gateway.

Model output is untrusted. Callers must validate its shape and run the gate's drift
check before storing it; on any failure they fall back to deterministic output and
the reason is recorded (never silently swallowed).
"""
import json
import logging

import httpx

from .config import settings

log = logging.getLogger("growthos.model")


def configured() -> bool:
    return bool(settings.text_model_base_url and settings.text_model_name)


def generate_json(system: str, user: str, fallback: dict) -> tuple[dict, str]:
    """Returns (payload, mode). mode is 'deterministic', 'model', or 'deterministic-fallback: <reason>'."""
    if not configured():
        return fallback, "deterministic"
    url = settings.text_model_base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.text_model_api_key:
        headers["Authorization"] = "Bearer " + settings.text_model_api_key
    payload = {
        "model": settings.text_model_name,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    try:
        # The gateway is operator-configured infrastructure (often on a private network), so it is
        # not subject to the destination egress policy. Redirects are not followed.
        r = httpx.post(url, json=payload, headers=headers, timeout=settings.http_timeout_seconds, follow_redirects=False)
        r.raise_for_status()
        out = json.loads(r.json()["choices"][0]["message"]["content"])
        if not isinstance(out, dict):
            return fallback, "deterministic-fallback: model returned non-object JSON"
        return out, "model"
    except Exception as exc:  # noqa: BLE001 - any gateway failure degrades to deterministic output
        log.warning("model gateway failed: %s", exc)
        return fallback, f"deterministic-fallback: {type(exc).__name__}"
