"""MCP destination: call one tool on a remote Model Context Protocol server.

This is what lets GrowthOS reach anything that has an MCP server (a CRM, a wiki, a ticketing system, an internal
control plane) without a bespoke adapter: name the tool, map release fields to its arguments.

Transport: Streamable HTTP only. Speaks protocol revision 2026-07-28 (stateless: per-request `_meta`, the
MCP-Protocol-Version / Mcp-Method / Mcp-Name headers, Mcp-Param-* mirroring for `x-mcp-header` parameters) and
falls back to the 2025-03-26..2025-11-25 `initialize` handshake for older servers. stdio servers are not
supported on purpose: launching local processes from endpoint config would be remote code execution.

The remote server is untrusted. Its tool descriptions, instructions and results are never fed to a model and
never interpreted; a result is only recorded as the delivery reference.
"""
import base64
import json
import re
import time

import httpx

from ..config import settings
from ..netguard import check_url, secret_from_env
from . import Adapter, DeliveryResult, register
from ._common import USER_AGENT, compose

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
LEGACY_VERSIONS = {"2025-03-26", "2025-06-18", "2025-11-25"}
CLIENT_INFO = {"name": "parinita-growthos", "version": "1.6.0"}
META_VERSION, META_CLIENT, META_CAPS = ("io.modelcontextprotocol/protocolVersion", "io.modelcontextprotocol/clientInfo",
                                        "io.modelcontextprotocol/clientCapabilities")
FIELDS = ("title", "summary", "body", "cta_url", "text", "content_id", "content_hash", "locale", "classification", "sources", "claims")
_PLAIN = re.compile(r"^[\x21-\x7e]([\x20-\x7e\t]*[\x21-\x7e])?$")
_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


class McpFailure(Exception):
    def __init__(self, detail: str, status: int | None = None, attempts: int = 1):
        super().__init__(detail)
        self.detail, self.status, self.attempts = detail, status, attempts


def header_value(value) -> str:
    """Mcp-Name / Mcp-Param-* encoding: plain ASCII when safe, otherwise the Base64 sentinel form."""
    s = ("true" if value else "false") if isinstance(value, bool) else str(value)
    if _PLAIN.match(s) and not (s.startswith("=?base64?") and s.endswith("?=")):
        return s
    return "=?base64?" + base64.b64encode(s.encode("utf-8")).decode() + "?="


def param_headers(schema: dict, arguments: dict) -> dict[str, str]:
    """Mirror parameters annotated with x-mcp-header (reachable through `properties` only) into Mcp-Param-* headers."""
    out: dict[str, str] = {}

    def walk(node, value):
        if not isinstance(node, dict) or not isinstance(value, dict):
            return
        for key, sub in (node.get("properties") or {}).items():
            if not isinstance(sub, dict) or key not in value or value[key] is None:
                continue
            name = sub.get("x-mcp-header")
            if isinstance(name, str) and _TOKEN.match(name) and isinstance(value[key], (str, bool, int)) and not isinstance(value[key], float):
                out[f"Mcp-Param-{name}"] = header_value(value[key])
            walk(sub, value[key])

    walk(schema or {}, arguments)
    return out


def _parse_sse(text: str, want_id) -> dict | None:
    """Return the JSON-RPC response for our request id; request-scoped notifications before it are ignored."""
    for block in re.split(r"\r?\n\r?\n", text):
        data = "\n".join(line[5:].lstrip(" ") for line in block.splitlines() if line.startswith("data:"))
        if not data:
            continue
        try:
            msg = json.loads(data)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("id") == want_id and ("result" in msg or "error" in msg):
            return msg
    return None


class _Wire:
    """One logical exchange with one MCP endpoint."""

    def __init__(self, url: str, auth_headers: dict):
        check_url(url)
        self.url, self.auth, self.attempts, self._id = url, auth_headers, 0, 0
        self.client = httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=False)

    def close(self):
        self.client.close()

    def post(self, method: str, params: dict | None, headers: dict, *, safe: bool, notification: bool = False):
        """safe=True: nothing happens on the server if this is repeated (discovery, listing, handshake).
        safe=False (tools/call): repeated only when the request provably was not processed."""
        self._id += 1
        body = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
        if not notification:
            body["id"] = self._id
        hdrs = {"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                **self.auth, **headers}
        tries = max(1, settings.push_max_attempts)
        for n in range(1, tries + 1):
            self.attempts += 1
            try:
                with self.client.stream("POST", self.url, json=body, headers=hdrs) as r:
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > settings.max_feed_bytes:
                            raise McpFailure("MCP response exceeded the size limit", r.status_code, self.attempts)
                    status, ctype, text, rheaders = r.status_code, r.headers.get("content-type", ""), buf.decode("utf-8", "replace"), r.headers
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if n == tries:
                    raise McpFailure(f"{type(exc).__name__}: {exc}"[:300], None, self.attempts) from exc
            except httpx.TransportError as exc:
                if not safe or n == tries:
                    raise McpFailure(f"{type(exc).__name__}: {exc}"[:300], None, self.attempts) from exc
            else:
                if status == 429 or (safe and status >= 500):
                    if n < tries:
                        time.sleep(settings.push_backoff_seconds * (3 ** (n - 1)))
                        continue
                if 300 <= status < 400:
                    raise McpFailure(f"MCP endpoint answered with a redirect (HTTP {status}); redirects are not followed", status, self.attempts)
                if notification:
                    return status, rheaders, None
                msg = _parse_sse(text, body["id"]) if "text/event-stream" in ctype else None
                if msg is None:
                    try:
                        parsed = json.loads(text) if text.strip() else None
                        msg = parsed if isinstance(parsed, dict) else None
                    except ValueError:
                        msg = None
                return status, rheaders, msg
            time.sleep(settings.push_backoff_seconds * (3 ** (n - 1)))
        raise McpFailure("no response", None, self.attempts)


def _modern_meta() -> dict:
    return {META_VERSION: MODERN, META_CLIENT: CLIENT_INFO, META_CAPS: {}}


def _find_tool_modern(wire: _Wire, tool: str):
    """tools/list on a 2026-07-28 server. Returns (schema | None, era) where era is 'modern', 'legacy' or 'absent'."""
    cursor, names = None, []
    for _ in range(10):
        params = {"_meta": _modern_meta(), **({"cursor": cursor} if cursor else {})}
        status, _, msg = wire.post("tools/list", params, {"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/list"}, safe=True)
        if not (msg and isinstance(msg.get("result"), dict)):
            err = (msg or {}).get("error") or {}
            if err.get("code") == -32022:  # UnsupportedProtocolVersion: the server told us what it speaks
                supported = (err.get("data") or {}).get("supported") or []
                if MODERN not in supported and LEGACY_VERSIONS & set(supported):
                    return None, "legacy"
                raise McpFailure(f"MCP server supports protocol versions {supported}; this adapter speaks {MODERN} and {sorted(LEGACY_VERSIONS)}", status, wire.attempts)
            if status in (401, 403):
                raise McpFailure(f"MCP server refused the credentials (HTTP {status})", status, wire.attempts)
            return None, "legacy"  # not a modern answer: try the initialize-based protocol
        for t in msg["result"].get("tools") or []:
            names.append(t.get("name"))
            if t.get("name") == tool:
                return t.get("inputSchema") or {}, "modern"
        cursor = msg["result"].get("nextCursor")
        if not cursor:
            break
    raise McpFailure(f"MCP server has no tool named '{tool}'. It offers: {', '.join(str(n) for n in names[:20]) or 'none'}", 200, wire.attempts)


def _call_legacy(wire: _Wire, tool: str, arguments: dict) -> dict:
    status, headers, msg = wire.post("initialize", {"protocolVersion": LEGACY, "capabilities": {}, "clientInfo": CLIENT_INFO}, {}, safe=True)
    if not (msg and isinstance(msg.get("result"), dict)):
        detail = ((msg or {}).get("error") or {}).get("message") or f"HTTP {status}"
        raise McpFailure(f"MCP server did not accept a {MODERN} request or an initialize handshake: {detail}", status, wire.attempts)
    version = msg["result"].get("protocolVersion", LEGACY)
    if version not in LEGACY_VERSIONS:
        raise McpFailure(f"MCP server negotiated unsupported protocol version {version}", status, wire.attempts)
    session = {"MCP-Protocol-Version": version, **({"Mcp-Session-Id": headers["mcp-session-id"]} if headers.get("mcp-session-id") else {})}
    try:
        wire.post("notifications/initialized", None, session, safe=True, notification=True)
        status, _, msg = wire.post("tools/call", {"name": tool, "arguments": arguments}, session, safe=False)
    finally:
        if "Mcp-Session-Id" in session:  # be a good citizen: end the session we opened
            try:
                wire.client.delete(wire.url, headers={**wire.auth, **session})
            except httpx.HTTPError:
                pass
    return _result(status, msg, wire)


def _result(status: int, msg: dict | None, wire: _Wire) -> dict:
    if not msg:
        raise McpFailure(f"MCP server gave no JSON-RPC response (HTTP {status})", status, wire.attempts)
    if msg.get("error"):
        e = msg["error"]
        raise McpFailure(f"MCP error {e.get('code')}: {str(e.get('message', ''))[:300]}", status, wire.attempts)
    return msg.get("result") or {}


def _reference(result: dict, id_field: str) -> str:
    sc = result.get("structuredContent")
    if isinstance(sc, dict) and sc.get(id_field) is not None:
        return str(sc[id_field])[:300]
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                parsed = json.loads(block.get("text", ""))
                if isinstance(parsed, dict) and parsed.get(id_field) is not None:
                    return str(parsed[id_field])[:300]
            except ValueError:
                pass
            return str(block.get("text", ""))[:120]
    return ""


class McpAdapter(Adapter):
    protocols = {"mcp"}

    def check_config(self, url, cfg):
        if not cfg.get("tool") or not isinstance(cfg.get("tool"), str):
            return "mcp endpoints need config.tool (the tool to call) and the server's Streamable HTTP URL"
        amap = cfg.get("argument_map") or {}
        if not isinstance(amap, dict) or not isinstance(cfg.get("static_arguments") or {}, dict):
            return "config.argument_map and config.static_arguments must be objects"
        bad = sorted(str(v) for v in amap.values() if v not in FIELDS)
        if bad:
            return f"argument_map refers to unknown release field(s) {bad}; available: {', '.join(FIELDS)}"
        if not amap and not cfg.get("static_arguments"):
            return "mcp endpoints need config.argument_map: {<tool argument>: <release field>}"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        auth = {}
        if cfg.get("bearer_token_env"):
            token = secret_from_env(cfg["bearer_token_env"])
            if not token:
                raise ValueError(f"secret {cfg['bearer_token_env']} is not set in the environment")
            auth["Authorization"] = f"Bearer {token}"
        values = {"title": payload["title"], "summary": payload.get("summary", ""), "body": payload["body"],
                  "cta_url": payload.get("cta_url", ""), "content_id": payload["id"], "content_hash": payload.get("content_hash", ""),
                  "locale": payload.get("locale", ""), "classification": payload.get("classification", ""), "claims": payload.get("claims", []),
                  "text": compose(payload, str(cfg.get("channel", "mcp")), int(cfg.get("max_chars", 4000)), text_source=cfg.get("text_source", "auto")),
                  "sources": sorted({s["uri"] for c in payload.get("claims", []) for s in c.get("sources", []) if s.get("uri")})}
        arguments = {**(cfg.get("static_arguments") or {}), **{arg: values[field] for arg, field in (cfg.get("argument_map") or {}).items()}}
        tool, wire = cfg["tool"], None
        try:
            wire = _Wire(endpoint.url, auth)
            schema, era = _find_tool_modern(wire, tool)
            if era == "modern":
                headers = {"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call", "Mcp-Name": header_value(tool), **param_headers(schema, arguments)}
                status, _, msg = wire.post("tools/call", {"name": tool, "arguments": arguments, "_meta": _modern_meta()}, headers, safe=False)
                result = _result(status, msg, wire)
            else:
                result = _call_legacy(wire, tool, arguments)
            if result.get("resultType") == "input_required":
                raise McpFailure("the tool asked for interactive input, which an unattended publisher cannot provide", 200, wire.attempts)
            if result.get("isError"):
                text = " ".join(str(b.get("text", "")) for b in result.get("content") or [] if isinstance(b, dict))[:300]
                raise McpFailure(f"tool '{tool}' reported an error: {text or 'no detail'}", 200, wire.attempts)
            return DeliveryResult(ok=True, status_code=200, attempts=wire.attempts, provider_id=_reference(result, str(cfg.get("id_field", "id"))),
                                  detail=f"tool '{tool}' called over MCP ({MODERN if era == 'modern' else 'initialize handshake'})")
        except McpFailure as f:
            return DeliveryResult(ok=False, status_code=f.status, attempts=f.attempts, detail=f.detail)
        finally:
            if wire is not None:
                wire.close()


register(McpAdapter())
