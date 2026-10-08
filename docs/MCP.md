# MCP

GrowthOS speaks the Model Context Protocol in both directions, over Streamable HTTP, at protocol revision
**2026-07-28** (stateless) with fallback to the 2025-03-26 .. 2025-11-25 `initialize` handshake.

## 1. GrowthOS as an MCP server: `POST /mcp`

Point any MCP client (an agent runtime, an IDE, Tapestry, Weaver) at `<PUBLIC_BASE_URL>/mcp` with an API key
(`X-API-Key`) or an IdP token (`Authorization: Bearer`). Tools run under that credential's roles and are audited
as `<principal> via MCP`.

| Tool | Role | What it does |
|---|---|---|
| `list_releases`, `get_release` | any | Browse and read releases |
| `get_sentence_ledger` | any | Which sentences are covered, let stand, exempt or open |
| `check_release` | any | Evaluate the gate without changing anything |
| `create_draft`, `update_copy` | editor | Write copy (a change creates a new version) |
| `attach_evidence` | editor | Add a sourced claim, optionally linked to one sentence |
| `run_checks` | editor | Run agents + gate; sets approved or blocked |
| `list_destinations` | any | Where a release can go |
| `send_release` | publisher | Send a clear release to one destination |
| `verify_audit_chain` | auditor | Recompute the audit chain |

**There is no tool to approve a release, withdraw an approval, or let a sentence stand without evidence.**
Those stay with people in the console. An agent can do the work; it cannot sign for it. Give an agent the
`editor` role only if it should not send.

Conformance implemented: `server/discover`; `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name` validation with
`-32020 HeaderMismatch`; `-32022 UnsupportedProtocolVersion` listing supported versions; `resultType`, `ttlMs`,
`cacheScope`; `404` + `-32601` for unknown methods; `Origin` validation (set `MCP_ALLOWED_ORIGINS` for browser
clients); `405` on GET/DELETE; no sessions. With SSO on, `/.well-known/oauth-protected-resource` names your
identity provider. Not implemented: resources, prompts, subscriptions, tasks, multi round-trip input requests.
Turn the endpoint off with `MCP_ENABLED=false`.

Release copy returned by tools can contain text written by third parties (for example ingested feed items).
The server says so in its instructions; treat it as data in whatever agent consumes it.

## 2. MCP as a destination: `protocol: "mcp"`

Send a release by calling one tool on a remote MCP server. This is the route to systems that have an MCP server
but no native GrowthOS adapter.

```json
{"name": "Wiki newsroom", "slug": "wiki-mcp", "direction": "outbound", "protocol": "mcp",
 "url": "https://mcp.example.com/mcp",
 "config": {"tool": "create_page", "bearer_token_env": "GROWTHOS_SECRET_MCP_TOKEN",
            "static_arguments": {"space": "NEWS"},
            "argument_map": {"title": "title", "body": "body", "link": "cta_url"},
            "id_field": "id", "classifications": ["pr"]}}
```

Release fields for `argument_map`: `title`, `summary`, `body`, `cta_url`, `text` (channel-ready text, see
`max_chars`), `content_id`, `content_hash`, `locale`, `classification`, `sources`, `claims`.

Behaviour: lists tools first (clear error if the tool is missing), mirrors `x-mcp-header` parameters into
`Mcp-Param-*` headers, accepts JSON or SSE responses, never repeats a `tools/call` that may have run, refuses
tools that ask for interactive input, records the returned id as the delivery reference. The gate, destination
policy, idempotency and audit apply as for every adapter, and so does the egress policy.

Remote servers are untrusted: their descriptions, instructions and results are never given to a model and never
interpreted. stdio servers are not supported, because starting local processes from endpoint config would be
remote code execution.

**Internal MCP servers (Tapestry fabrics, internal tools)** usually sit on private addresses. List their host
suffixes in `TRUSTED_INTERNAL_HOSTS`; nothing else is exempt from the public-address rule.

## Verification status

Both directions were run against the official MCP Python SDK 2.2.0: its client drove the GrowthOS server through
a full draft-to-send flow at 2026-07-28, and the adapter called a server built with the SDK in JSON and SSE
response modes. Not verified: other SDKs, OAuth-protected third-party servers, a Tapestry fabric.
