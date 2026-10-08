"""Reddit adapter: governed link or text posts to one subreddit.

Request shapes follow the Reddit Data API documentation as of October 2026:
  token   POST https://www.reddit.com/api/v1/access_token   (HTTP Basic client_id:client_secret;
                                                             grant_type=refresh_token, or password for script apps)
  submit  POST https://oauth.reddit.com/api/submit          (bearer token; form-encoded; api_type=json)

Reddit does not honour an idempotency key, so the submit step is never retried after it may have been processed
(see _common.call with idempotent=False). A duplicate link is refused by Reddit (ALREADY_SUB) unless config.resubmit
is true. Reddit requires a descriptive User-Agent and rate-limits per client; both are handled here.

Config (endpoint `config`):
  subreddit            required, without the r/ prefix
  client_id            required (not a secret; the Reddit app id)
  client_secret_env    required, GROWTHOS_SECRET_* name of the app secret
  refresh_token_env    recommended, GROWTHOS_SECRET_* name of a refresh token with the `submit` scope
  username + password_env   alternative for "script" apps (password grant); username is also used in the User-Agent
  kind                 "link" (default when the release has a CTA/source URL) or "self"
  flair_id             optional post flair template id
  resubmit             optional, allow a URL that was already posted to the subreddit
  max_title_chars      optional, default 300 (Reddit's limit)
  max_chars            optional, default 40000 (self-text limit)
  text_source          "auto" (Amplify copy for the reddit channel when present) or "master"
"""
import re

from . import Adapter, DeliveryResult, register
from ._common import USER_AGENT, base_url, call, failure, secret

_SUBREDDIT = re.compile(r"^[A-Za-z0-9_]{2,21}$")
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_URL = re.compile(r"^https?://", re.I)


def reddit_title(payload: dict, limit: int = 300) -> str:
    title = " ".join(str(payload.get("title") or "").split())
    if len(title) <= limit:
        return title
    cut = title[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,;:-") + "…"


def reddit_text(payload: dict, limit: int, text_source: str = "auto") -> str:
    """Self-post body: Amplify copy for the reddit channel when it exists (drift-checked), else summary/body + CTA.
    The title is Reddit's own field, so it is not repeated in the body."""
    copy = (payload.get("channel_copy") or {}).get("reddit") if text_source != "master" else None
    cta = payload.get("cta_url") or ""
    if copy:
        text = copy.strip()
    else:
        text = (payload.get("summary") or payload.get("body") or "").strip()
        if cta and cta not in text:
            text += ("\n\n" if text else "") + cta
    if len(text) <= limit:
        return text
    keep = text[: limit - len(cta) - 4] if cta and text.endswith(cta) else text[: limit - 1]
    keep = keep[: keep.rindex(" ")] if " " in keep else keep
    return keep.rstrip(" ,;:-\n") + "…" + ("\n\n" + cta if cta and text.endswith(cta) else "")


class RedditAdapter(Adapter):
    protocols = {"reddit"}

    def check_config(self, url, cfg):
        if not _SUBREDDIT.match(str(cfg.get("subreddit", ""))):
            return "reddit endpoints need config.subreddit (name only, no r/ prefix)"
        if not _CLIENT_ID.match(str(cfg.get("client_id", ""))):
            return "reddit endpoints need config.client_id (the Reddit app id)"
        if not cfg.get("client_secret_env"):
            return "reddit endpoints need config.client_secret_env"
        if not cfg.get("refresh_token_env") and not (cfg.get("username") and cfg.get("password_env")):
            return "reddit endpoints need config.refresh_token_env, or config.username + config.password_env for a script app"
        if cfg.get("kind") not in (None, "", "link", "self"):
            return "config.kind must be link or self"
        if cfg.get("flair_id") and not re.fullmatch(r"[A-Za-z0-9-]{1,64}", str(cfg["flair_id"])):
            return "config.flair_id must be a flair template id"
        return ""

    def _user_agent(self, cfg: dict) -> str:
        who = f" (by /u/{cfg['username']})" if cfg.get("username") else ""
        return f"server:parinita.growthos:{USER_AGENT.split('/')[-1]}{who}"

    def _token(self, cfg: dict) -> tuple[str | None, int, str, object]:
        if cfg.get("refresh_token_env"):
            form = {"grant_type": "refresh_token", "refresh_token": secret(cfg, "refresh_token_env")}
        else:
            form = {"grant_type": "password", "username": str(cfg["username"]), "password": secret(cfg, "password_env")}
        r, n, err = call("POST", base_url("reddit_auth", "https://www.reddit.com") + "/api/v1/access_token", idempotent=True,
                         data=form, auth=(str(cfg["client_id"]), secret(cfg, "client_secret_env")),
                         headers={"User-Agent": self._user_agent(cfg)})
        if r is None or r.status_code != 200:
            return None, n, err, r
        try:
            tok = r.json().get("access_token")
        except ValueError:
            tok = None
        return (str(tok) if tok else None), n, err, r

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        token, n, err, r = self._token(cfg)
        if not token:
            return failure(r, n, err, "Reddit token request failed (check client_id, client_secret_env and the refresh token / script credentials)")
        link = payload.get("cta_url") or (payload.get("source") if _URL.match(str(payload.get("source") or "")) else "")
        kind = cfg.get("kind") or ("link" if link else "self")
        if kind == "link" and not link:
            kind = "self"  # nothing to link to; fall back rather than fail
        form = {"api_type": "json", "sr": str(cfg["subreddit"]), "kind": kind, "title": reddit_title(payload, int(cfg.get("max_title_chars", 300))),
                "sendreplies": "true" if cfg.get("sendreplies") else "false", "nsfw": "false", "spoiler": "false",
                "resubmit": "true" if cfg.get("resubmit") else "false"}
        if kind == "link":
            form["url"] = link
        else:
            form["text"] = reddit_text(payload, int(cfg.get("max_chars", 40000)), text_source=cfg.get("text_source", "auto"))
        if cfg.get("flair_id"):
            form["flair_id"] = str(cfg["flair_id"])
        r, n2, err = call("POST", base_url("reddit", "https://oauth.reddit.com") + "/api/submit", idempotent=False, data=form,
                          headers={"Authorization": f"Bearer {token}", "User-Agent": self._user_agent(cfg)})
        attempts = n + n2 - 1
        if r is not None and r.status_code == 200:
            try:
                j = r.json().get("json") or {}
            except ValueError:
                j = {}
            errors = j.get("errors") or []
            if not errors:
                data = j.get("data") or {}
                return DeliveryResult(ok=True, status_code=200, attempts=attempts, provider_id=str(data.get("url") or data.get("name") or "")[:300])
            code = str(errors[0][0]) if errors and errors[0] else "error"
            hint = {"ALREADY_SUB": "this link was already posted to the subreddit (set config.resubmit to allow it)",
                    "SUBREDDIT_NOTALLOWED": "the account may not post in this subreddit",
                    "RATELIMIT": "Reddit rate limit for this account; try later",
                    "NO_TEXT": "self posts need text", "NO_URL": "link posts need a URL"}.get(code, code)
            return DeliveryResult(ok=False, status_code=200, attempts=attempts,
                                  detail=f"Reddit refused the post: {'; '.join(str(e[1]) for e in errors if len(e) > 1)[:200] or code} - {hint}")
        hint = {401: "access token rejected (refresh token revoked, or the app lacks the submit scope)",
                403: "forbidden by Reddit (banned from the subreddit, or wrong app type)",
                429: "Reddit rate limit (per-client, 10-minute windows)"}.get(r.status_code if r is not None else 0, "")
        return failure(r, n2, err, hint)


register(RedditAdapter())
