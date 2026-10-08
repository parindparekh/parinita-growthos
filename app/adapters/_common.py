"""Shared plumbing for provider adapters: base URLs, secrets, retry policy, text fitting."""
import re
import time

import httpx

from ..config import settings
from ..netguard import check_url, secret_from_env, safe_request, FeedTooLarge
from . import DeliveryResult

USER_AGENT = "Parinita-GrowthOS/1.8"
_URL = re.compile(r"https?://\S+")


def base_url(protocol: str, default: str) -> str:
    return settings.provider_bases.get(protocol, default).rstrip("/")


def secret(cfg: dict, key: str) -> str:
    """Resolve a GROWTHOS_SECRET_* reference from endpoint config. Raises with a usable message."""
    name = cfg.get(key)
    if not name:
        raise ValueError(f"endpoint config is missing {key}")
    value = secret_from_env(str(name))
    if not value:
        raise ValueError(f"secret {name} is not set in the environment")
    return value


def call(method: str, url: str, *, headers: dict, idempotent: bool, json=None, data=None, auth=None):
    """One provider request with the right retry policy.

    idempotent=True  (provider honours an idempotency key): retry on transport errors, 429 and 5xx.
    idempotent=False (most social/podcast APIs): retry only when the request provably was not
    processed - connection could not be established, or the provider answered 429. A timeout or a
    5xx after the request was sent is NOT retried, because the post may already exist.

    Returns (response | None, attempts, error_text).
    """
    check_url(url)
    attempts, last_err = max(1, settings.push_max_attempts), ""
    for n in range(1, attempts + 1):
        try:
            r = safe_request(method, url, headers={"User-Agent": USER_AGENT, **headers}, json=json, data=data, auth=auth)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_err, retry = f"{type(exc).__name__}: {exc}"[:300], True
        except FeedTooLarge:
            return None, n, "provider response exceeded limit; delivery outcome is uncertain (reconcile before retry)"
        except httpx.TransportError as exc:
            last_err, retry = f"{type(exc).__name__}: {exc}"[:300], idempotent
        else:
            if r.status_code == 429 or (idempotent and r.status_code >= 500):
                last_err, retry = f"HTTP {r.status_code}", True
                wait = r.headers.get("retry-after", "")
                if wait.isdigit() and int(wait) > 30:
                    return r, n, last_err  # do not hold a request thread for a long provider cool-down
            else:
                return r, n, ""
            if n == attempts:
                return r, n, last_err
        if not retry or n == attempts:
            return None, n, last_err
        time.sleep(settings.push_backoff_seconds * (3 ** (n - 1)))
    return None, attempts, last_err


def failure(r, attempts: int, err: str, hint: str = "") -> DeliveryResult:
    if r is None:
        return DeliveryResult(ok=False, attempts=attempts, detail=err or "no response")
    snippet = (r.text or "")[:200].replace("\n", " ")
    return DeliveryResult(ok=False, status_code=r.status_code, attempts=attempts,
                          detail=f"HTTP {r.status_code}{' - ' + hint if hint else ''}: {snippet}")


# ----------------------------------------------------------------------------- text
def compose(payload: dict, channel: str, limit: int, weigh=len, text_source: str = "auto") -> str:
    """Post text for one channel. Uses the Amplify copy generated from this exact content version when there
    is one (already drift-checked), otherwise title + summary/body + CTA. Always fits `limit`; the CTA link is
    never truncated."""
    cta = payload.get("cta_url") or ""
    copy = (payload.get("channel_copy") or {}).get(channel) if text_source != "master" else None
    if copy:
        text = copy.strip()
        head, tail = (text[: -len(cta)].rstrip(), cta) if cta and text.endswith(cta) else (text, "")
    else:
        head = payload["title"].strip()
        lead = (payload.get("summary") or payload.get("body") or "").strip()
        if lead and lead != head:
            head += "\n\n" + lead
        tail = cta
    sep = "\n\n" if tail else ""
    if weigh(head + sep + tail) <= limit:
        return head + sep + tail
    budget = limit - weigh(sep + tail) - 1  # one character for the ellipsis
    cut = head
    while cut and weigh(cut) > budget:
        cut = cut[:-1]
    if cut and len(cut) < len(head) and not head[len(cut)].isspace() and " " in cut:
        cut = cut[: cut.rindex(" ")]  # back up to a word boundary
    return cut.rstrip(" ,;:-\n") + "\u2026" + sep + tail


def x_weight(text: str) -> int:
    """X counts every URL as 23 and most non-Latin code points as 2 (twitter-text v3 weighting)."""
    total = 23 * len(_URL.findall(text))
    for ch in _URL.sub("", text):
        cp = ord(ch)
        total += 1 if (cp <= 4351 or 8192 <= cp <= 8205 or 8208 <= cp <= 8223 or 8242 <= cp <= 8247) else 2
    return total


def link_spans_utf8(text: str) -> list[tuple[int, int, str]]:
    """(byteStart, byteEnd, uri) for each URL, as Bluesky rich-text facets need."""
    out = []
    for m in _URL.finditer(text):
        uri = m.group(0).rstrip(".,);!?")
        start = len(text[: m.start()].encode("utf-8"))
        out.append((start, start + len(uri.encode("utf-8")), uri))
    return out
