"""Small in-process rate limiter (defence in depth; use an edge limiter when scaled horizontally).

v1.6.1 hardening:
  * Every request is counted against its source address as well as its credential. Before this, a caller could mint
    a fresh bucket per request simply by sending a different (invalid) API key, which made credential guessing
    invisible to the limiter and let the bucket table grow without bound.
  * The bucket table is a bounded LRU; the least-recently-seen bucket is evicted when the cap is reached.
  * Credentials are hashed before they are retained in memory.
"""
import hashlib
import threading
import time
from collections import OrderedDict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import settings

_lock = threading.Lock()
_buckets: "OrderedDict[str, deque[float]]" = OrderedDict()


def _client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _bucket_keys(request: Request) -> list[tuple[str, int]]:
    """(key, limit) pairs this request must pass. The address bucket always applies."""
    path = request.url.path
    per_ip = settings.rate_limit_per_ip_per_minute
    if path.startswith("/feeds/"):
        return [("ip:feed:" + _client_host(request), settings.public_feed_rate_limit_per_minute)]
    keys = [("ip:" + _client_host(request), per_ip)]
    credential = request.headers.get("authorization", "") or request.headers.get("x-api-key", "")
    if credential:
        keys.append(("cred:" + hashlib.sha256(credential.encode()).hexdigest()[:24], settings.rate_limit_per_minute))
    return keys


def _allowed(key: str, limit: int) -> tuple[bool, int]:
    now = time.monotonic()
    cutoff = now - 60.0
    with _lock:
        q = _buckets.get(key)
        if q is None:
            q = _buckets[key] = deque()
        else:
            _buckets.move_to_end(key)
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= limit:
            retry = max(1, int(60 - (now - q[0])))
            return False, retry
        q.append(now)
        cap = max(100, settings.rate_limit_max_buckets)
        while len(_buckets) > cap:
            _buckets.popitem(last=False)  # least recently seen
        return True, 0


def check(request: Request) -> tuple[bool, int]:
    """All buckets must admit the request; the first refusal wins. Admitted buckets are charged."""
    for key, limit in _bucket_keys(request):
        ok, retry = _allowed(key, max(1, limit))
        if not ok:
            return False, retry
    return True, 0


async def middleware(request: Request, call_next):
    if not settings.rate_limit_enabled or request.url.path in {"/", "/health"}:
        return await call_next(request)
    ok, retry = check(request)
    if not ok:
        return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"}, headers={"Retry-After": str(retry)})
    return await call_next(request)
