"""Egress policy for every server-initiated request (feed ingestion, webhooks).

Blocks SSRF to loopback, private, link-local (cloud metadata) and reserved
ranges, enforces an optional destination allowlist, re-validates every redirect
hop, and caps response size.

Residual risk: validation resolves DNS before the request, so a hostile
resolver can still race it (DNS rebinding). Close that with a network egress
proxy/firewall in production; this module is the application-layer control.
"""
import ipaddress
import os
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

from .config import settings

SECRET_ENV_PATTERN = re.compile(r"^GROWTHOS_SECRET_[A-Z0-9_]+$")
FORBIDDEN_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-api-key", "host", "content-length"}
MAX_REDIRECTS = 3


class DestinationBlocked(ValueError):
    """The URL is not an allowed egress destination."""


class FeedTooLarge(ValueError):
    pass


def check_url(url: str) -> str:
    try:
        u = urlparse(url)
    except ValueError as exc:
        raise DestinationBlocked(f"unparseable URL: {exc}") from exc
    if u.scheme not in {"http", "https"}:
        raise DestinationBlocked("only http/https destinations are allowed")
    if settings.is_production and u.scheme != "https" and not settings.allow_private_destinations:
        raise DestinationBlocked("https is required in production")
    if u.username or u.password:
        raise DestinationBlocked("credentials in URLs are not allowed; use bearer_token_env")
    host = (u.hostname or "").lower()
    if not host:
        raise DestinationBlocked("URL has no host")
    allow = settings.allowlist
    if allow and not any(host == a or host.endswith("." + a) for a in allow):
        raise DestinationBlocked(f"host '{host}' is not in DESTINATION_ALLOWLIST")
    if settings.allow_private_destinations:
        return url
    if any(host == t or host.endswith("." + t) for t in settings.trusted_internal):
        return url  # operator-declared internal service (e.g. vaakd, a Tapestry fabric): private addresses expected
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DestinationBlocked(f"host '{host}' does not resolve") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise DestinationBlocked(f"host '{host}' resolves to a non-public address ({ip})")
    return url


def secret_from_env(name: str) -> str:
    """Resolve a destination secret. Only GROWTHOS_SECRET_* variables are readable, so
    endpoint configuration cannot be used to exfiltrate arbitrary process environment."""
    if not SECRET_ENV_PATTERN.match(name or ""):
        raise DestinationBlocked("secret env names must match GROWTHOS_SECRET_[A-Z0-9_]+")
    return os.getenv(name, "")


def clean_headers(headers: dict | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (headers or {}).items():
        k, v = str(k), str(v)
        if k.lower() in FORBIDDEN_HEADERS:
            raise DestinationBlocked(f"header '{k}' may not be set in endpoint config; use bearer_token_env")
        if any(c in k + v for c in "\r\n"):
            raise DestinationBlocked("header names/values may not contain newlines")
        out[k] = v
    return out


PUSH_ONLY = {"webhook", "rest_json", "smtp", "linkedin", "x", "mastodon", "bluesky", "transistor", "buzzsprout", "pr_wire",
             "slack", "teams", "discord", "telegram", "whatsapp", "wordpress", "mcp", "vaak",
             "reddit", "facebook", "instagram", "threads", "pinterest", "tiktok", "tumblr", "lemmy", "etsy", "shopify", "google_business", "devto", "ghost", "buttondown", "mailchimp", "google_chat", "mattermost", "matrix", "zulip"}


def _env_refs(obj):
    """Every '<something>_env' value anywhere in the config, however deeply nested."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.endswith("_env") and isinstance(v, str):
                yield k, v
            else:
                yield from _env_refs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _env_refs(v)


def validate_endpoint_config(url: str, config: dict, *, needs_url: bool, protocol: str = "", direction: str = "") -> None:
    """Static validation at endpoint creation time (no DNS; that happens at use time)."""
    if protocol in PUSH_ONLY and direction and direction != "outbound":
        raise DestinationBlocked(f"'{protocol}' endpoints must be outbound")
    if needs_url:
        if not url:
            raise DestinationBlocked("this protocol/direction requires a URL")
        u = urlparse(url)
        if u.scheme not in {"http", "https"} or not u.hostname:
            raise DestinationBlocked("only absolute http/https URLs are allowed")
        if u.username or u.password:
            raise DestinationBlocked("credentials in URLs are not allowed; use bearer_token_env")
    clean_headers(config.get("headers"))
    for field, value in _env_refs(config):
        if not SECRET_ENV_PATTERN.match(value):
            raise DestinationBlocked(f"{field} must match GROWTHOS_SECRET_[A-Z0-9_]+")
    if protocol:
        from .adapters import REGISTRY  # local import: adapters import this module
        adapter = REGISTRY.get(protocol)
        problem = adapter.check_config(url, config) if adapter else ""
        if problem:
            raise DestinationBlocked(problem)


def safe_get(url: str, headers: dict | None = None) -> bytes:
    """GET with per-hop destination validation and a hard size cap."""
    headers = dict(headers or {})
    current = url
    origin = urlparse(url).netloc
    with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(current)
            send_headers = headers if urlparse(current).netloc == origin else \
                {k: v for k, v in headers.items() if k.lower() != "authorization"}
            with client.stream("GET", current, headers=send_headers) as r:
                if r.status_code in {301, 302, 303, 307, 308} and r.headers.get("location"):
                    current = urljoin(current, r.headers["location"])
                    continue
                r.raise_for_status()
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > settings.max_feed_bytes:
                        raise FeedTooLarge(f"response exceeds MAX_FEED_BYTES ({settings.max_feed_bytes})")
                return bytes(buf)
    raise DestinationBlocked("too many redirects")


def safe_request(method: str, url: str, *, max_bytes: int | None = None, **kwargs) -> httpx.Response:
    """POST without following redirects (a redirect could re-target an internal host). The response body is capped
    (default MAX_FEED_BYTES) so a misbehaving peer cannot make GrowthOS buffer an unbounded reply."""
    check_url(url)
    cap = settings.max_feed_bytes if max_bytes is None else max_bytes
    if cap <= 0:
        raise ValueError("response cap must be positive")
    with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=False) as client:
        with client.stream(method, url, **kwargs) as r:
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf.extend(chunk)
                if len(buf) > cap:
                    raise FeedTooLarge(f"response exceeds {cap} bytes")
            r._content = bytes(buf)  # noqa: SLF001 - keeps .json()/.text/.raise_for_status() usable after streaming
            return r


def safe_post(url: str, *, content: bytes, headers: dict[str, str], max_bytes: int | None = None) -> httpx.Response:
    return safe_request("POST", url, content=content, headers=headers, max_bytes=max_bytes)
