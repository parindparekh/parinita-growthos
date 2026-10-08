import hashlib
import hmac
import json
import time

import httpx

from ..config import settings
from ..netguard import clean_headers, safe_post, secret_from_env
from . import Adapter, DeliveryResult, register

RETRYABLE = {408, 425, 429, 500, 502, 503, 504}


class WebhookAdapter(Adapter):
    """Generic JSON POST. Sends a stable Idempotency-Key and, when a signing secret is configured,
    X-GrowthOS-Signature = hex(HMAC-SHA256(secret, f"{timestamp}.{body}"))."""
    protocols = {"webhook", "rest_json"}

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ts = str(int(time.time()))
        headers = {**clean_headers(cfg.get("headers")), "Content-Type": "application/json",
                   "Idempotency-Key": idempotency_key, "X-GrowthOS-Content-Hash": payload.get("content_hash", ""),
                   "X-GrowthOS-Timestamp": ts}
        if cfg.get("bearer_token_env"):
            token = secret_from_env(cfg["bearer_token_env"])
            if not token:
                return DeliveryResult(ok=False, detail=f"secret {cfg['bearer_token_env']} is not set", attempts=0)
            headers["Authorization"] = "Bearer " + token
        if cfg.get("signing_secret_env"):
            secret = secret_from_env(cfg["signing_secret_env"])
            if not secret:
                return DeliveryResult(ok=False, detail=f"secret {cfg['signing_secret_env']} is not set", attempts=0)
            headers["X-GrowthOS-Signature"] = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()

        last = DeliveryResult(ok=False, detail="not attempted", attempts=0)
        attempts = max(1, settings.push_max_attempts)
        for n in range(1, attempts + 1):
            try:
                r = safe_post(endpoint.url, content=body, headers=headers)
                if 200 <= r.status_code < 300:
                    return DeliveryResult(ok=True, status_code=r.status_code, attempts=n,
                                          provider_id=r.headers.get("x-request-id", "")[:300])
                last = DeliveryResult(ok=False, status_code=r.status_code, attempts=n, detail=f"HTTP {r.status_code}")
                if r.status_code not in RETRYABLE:
                    return last  # 3xx/4xx: retrying will not help
            except httpx.TransportError as exc:
                last = DeliveryResult(ok=False, attempts=n, detail=f"{type(exc).__name__}: {exc}"[:500])
            if n < attempts:
                time.sleep(settings.push_backoff_seconds * (3 ** (n - 1)))
        return last


register(WebhookAdapter())
