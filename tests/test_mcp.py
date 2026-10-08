"""MCP in both directions.
  * GrowthOS as an MCP server (/mcp): protocol conformance, tools, roles, and what is deliberately absent.
  * The `mcp` destination adapter: 2026-07-28 stateless calls, SSE responses, fallback to the older handshake.
  * Interop with the official MCP Python SDK (run when MCP_SDK_PYTHON points at an interpreter that has `mcp` installed)."""
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

from app.config import settings
from tests.conftest import AUDITOR, BOOT, EDITOR, PUBLISHER, feed, make, run_pipeline

V = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": V, "io.modelcontextprotocol/clientInfo": {"name": "t", "version": "0"},
        "io.modelcontextprotocol/clientCapabilities": {}}
SDK_PY = os.environ.get("MCP_SDK_PYTHON", "")
needs_sdk = pytest.mark.skipif(not (SDK_PY and Path(SDK_PY).exists()), reason="set MCP_SDK_PYTHON to an interpreter with the mcp SDK installed")
INTEROP = Path(__file__).parent / "interop"


def rpc(client, method, params=None, key=EDITOR, headers=None, rid=1):
    params = {**(params or {}), "_meta": META}
    h = {**key, "MCP-Protocol-Version": V, "Mcp-Method": method, **({"Mcp-Name": params["name"]} if method == "tools/call" else {}), **(headers or {})}
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params}, headers=h)


def call(client, name, args=None, key=EDITOR):
    r = rpc(client, "tools/call", {"name": name, "arguments": args or {}}, key=key)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    return res, (res.get("structuredContent") if not res["isError"] else res["content"][0]["text"])


# ------------------------------------------------------------------------------ server: protocol
def test_discover_and_tool_list_follow_the_2026_07_28_shapes(client):
    d = rpc(client, "server/discover").json()["result"]
    assert d["supportedVersions"][0] == V and d["capabilities"] == {"tools": {"listChanged": False}} and d["resultType"] == "complete"
    assert d["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "parinita-growthos" and "human-only" in d["instructions"]
    r = rpc(client, "tools/list").json()["result"]
    assert r["resultType"] == "complete" and r["ttlMs"] > 0 and r["cacheScope"] == "public"
    names = [t["name"] for t in r["tools"]]
    assert names == ["list_releases", "get_release", "get_sentence_ledger", "check_release", "create_draft", "update_copy", "attach_evidence",
                     "run_checks", "list_destinations", "send_release", "verify_audit_chain"]
    assert all(t["inputSchema"]["type"] == "object" for t in r["tools"])
    # The human-only acts have no tool at all.
    assert not [n for n in names if any(w in n for w in ("approve", "revoke", "waive", "disposition", "stand"))]


def test_header_and_version_validation(client):
    assert rpc(client, "tools/list", headers={"Mcp-Method": "tools/call"}).json()["error"]["code"] == -32020
    r = rpc(client, "tools/call", {"name": "get_release", "arguments": {"id": "x"}}, headers={"Mcp-Name": "send_release"})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32020
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": META}},
                    headers={**EDITOR, "MCP-Protocol-Version": "2025-11-25", "Mcp-Method": "tools/list"})
    assert r.status_code == 200          # an older client: body _meta is ignored, header decides
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": META}}, headers={**EDITOR, "Mcp-Method": "tools/list"})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32020   # modern body without the version header
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 7, "method": "tools/list"}, headers={**EDITOR, "MCP-Protocol-Version": "1999-01-01"})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32022 and V in r.json()["error"]["data"]["supported"] and r.json()["id"] == 7
    r = rpc(client, "resources/list")
    assert r.status_code == 404 and r.json()["error"]["code"] == -32601
    # Base64 sentinel form of Mcp-Name is decoded before comparison.
    r = rpc(client, "tools/call", {"name": "list_releases", "arguments": {}}, headers={"Mcp-Name": "=?base64?bGlzdF9yZWxlYXNlcw==?="})
    assert r.status_code == 200 and r.json()["result"]["isError"] is False


def test_transport_rules(client):
    assert client.get("/mcp", headers=EDITOR).status_code == 405 and client.delete("/mcp", headers=EDITOR).status_code == 405
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "server/discover"})
    assert r.status_code == 401 and "Bearer" in r.headers["www-authenticate"]
    assert rpc(client, "tools/list", headers={"Origin": "https://evil.example"}).status_code == 403     # DNS-rebinding protection
    assert rpc(client, "tools/list", headers={"Origin": "http://localhost:8080"}).status_code == 200
    assert client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], headers=EDITOR).status_code == 400   # no batches
    assert client.post("/mcp", content=b"{not json", headers={**EDITOR, "Content-Type": "application/json"}).json()["error"]["code"] == -32700


def test_older_clients_can_use_the_initialize_handshake(client):
    def old(method, params=None, rid=1, version=None):
        body = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {}), **({"id": rid} if rid is not None else {})}
        return client.post("/mcp", json=body, headers={**EDITOR, **({"MCP-Protocol-Version": version} if version else {})})
    init = old("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "old", "version": "1"}})
    res = init.json()["result"]
    assert res["protocolVersion"] == "2025-06-18" and res["serverInfo"]["name"] == "parinita-growthos" and "resultType" not in res
    assert "mcp-session-id" not in init.headers                                    # stateless: no sessions minted
    assert old("notifications/initialized", rid=None, version="2025-06-18").status_code == 202
    assert len(old("tools/list", version="2025-06-18").json()["result"]["tools"]) == 11
    assert old("ping", version="2025-06-18").json()["result"] == {}
    r = old("tools/call", {"name": "list_releases", "arguments": {}}, version="2025-06-18").json()["result"]
    assert r["isError"] is False and r["structuredContent"] == {"releases": []}
    assert old("nope/nope", version="2025-06-18").json()["error"]["code"] == -32601


# ------------------------------------------------------------------------------ server: tools and governance
def test_an_agent_can_draft_source_check_and_send_but_not_sign(client, sink, lan):
    feed(client, name="Newsroom", slug="newsroom", direction="outbound", protocol="webhook", url=sink.url + "/hook")
    key = {"X-API-Key": BOOT["X-API-Key"]}   # bootstrap: editor + publisher via admin
    _, draft = call(client, "create_draft", {"title": "Agent drafted release", "classification": "pr", "body": "GrowthOS now speaks MCP.\nCustomers love it."}, key)
    rid = draft["id"]
    _, checks = call(client, "run_checks", {"id": rid}, key)
    assert checks["clear_to_release"] is False and checks["sentences"]["open"] == 3
    res, text = call(client, "send_release", {"id": rid, "destination": "newsroom"}, key)
    assert res["isError"] and "Hallucination Gate" in text and sink.posts == []
    _, ledger = call(client, "get_sentence_ledger", {"id": rid}, key)
    for s in ledger["sentences"]:
        _, out = call(client, "attach_evidence", {"id": rid, "text": s["text"], "source_uri": "internal://launch-brief", "sentence_hash": s["hash"]}, key)
    assert out["open_sentences"] == []
    assert call(client, "run_checks", {"id": rid}, key)[1]["state"] == "approved"
    _, sent = call(client, "send_release", {"id": rid, "destination": "newsroom"}, key)
    assert sent["status"] == "sent" and sent["duplicate"] is False and len(sink.posts) == 1
    assert call(client, "send_release", {"id": rid, "destination": "newsroom"}, key)[1]["duplicate"] is True and len(sink.posts) == 1
    actors = {e["actor"] for e in client.get(f"/v1/audit?content_id={rid}", headers=AUDITOR).json()}
    assert "bootstrap via MCP" in actors and any("run by bootstrap via MCP" in a for a in actors)


def test_tools_run_under_the_callers_roles_and_bad_input_is_a_tool_error(client):
    res, text = call(client, "create_draft", {"title": "t", "body": "b"}, AUDITOR)
    assert res["isError"] and "'editor' role" in text
    assert call(client, "verify_audit_chain", {}, EDITOR)[0]["isError"] and call(client, "verify_audit_chain", {}, AUDITOR)[1]["ok"] is True
    assert "missing argument(s): body" in call(client, "create_draft", {"title": "t"})[1]
    assert "unknown argument(s): approve" in call(client, "create_draft", {"title": "t", "body": "b", "approve": True})[1]
    assert "No release with id" in call(client, "get_release", {"id": "nope"})[1]
    cid = make(client)["id"]
    res, text = call(client, "attach_evidence", {"id": cid, "text": "x", "source_uri": "trust me"})
    assert res["isError"] and "source uri must use one of" in text          # an agent cannot attach a made-up source
    assert rpc(client, "tools/call", {"name": "approve_release", "arguments": {}}).json()["error"]["code"] == -32602


def test_high_risk_content_stays_blocked_until_a_human_approves(client):
    cid = make(client, classification="investor", title="Investor update")["id"]
    _, checks = call(client, "run_checks", {"id": cid})
    assert checks["clear_to_release"] is False and any("human approval required" in b for b in checks["blockers"]) and checks["human_approved"] is False


@needs_sdk
def test_interop_official_sdk_client_drives_the_growthos_server(client, live_server, sink, lan):
    feed(client, name="Newsroom", slug="newsroom", direction="outbound", protocol="webhook", url=sink.url + "/hook")
    out = subprocess.run([SDK_PY, str(INTEROP / "sdk_client.py"), live_server + "/mcp", BOOT["X-API-Key"], "newsroom"],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["protocol_version"] == V and r["server"] == "parinita-growthos" and len(r["tools"]) == 11
    assert r["blocked_first"] is False and r["clear_after_evidence"] is True and r["state"] == "approved"
    assert r["send_is_error"] is False and r["sent"]["status"] == "sent" and len(sink.posts) == 1
    assert r["auditor_tool_refused"] is False   # bootstrap is admin, which implies auditor
    assert sink.posts[0]["json"]["title"] == "Agent drafted release"


# ------------------------------------------------------------------------------ client adapter
TOOL = {"name": "create_page", "description": "d", "inputSchema": {"type": "object", "properties": {
    "space": {"type": "string", "x-mcp-header": "Space"}, "title": {"type": "string"}, "body": {"type": "string"}, "link": {"type": "string"}}}}


class MockMcp:
    def __init__(self, mode="modern-json", result=None, call_status=200):
        self.mode, self.calls, self.call_status = mode, [], call_status
        self.result = result or {"content": [{"type": "text", "text": "created"}], "structuredContent": {"id": "page-9"}, "isError": False}

    def __call__(self, req):
        m, h, rid = req["json"].get("method"), req["headers"], req["json"].get("id")
        ok = lambda res, extra=None: (200, extra or {}, {"jsonrpc": "2.0", "id": rid, "result": res})  # noqa: E731
        modern_req = h.get("mcp-protocol-version") == V
        if self.mode.startswith("legacy"):
            if modern_req:
                if self.mode == "legacy-says-so":
                    return 400, {}, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32022, "message": "unsupported", "data": {"supported": ["2025-11-25"], "requested": V}}}
                return 400, {"Content-Type": "text/plain"}, b"Bad Request: Missing session ID"
            if m == "initialize":
                return ok({"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "old", "version": "1"}}, {"Mcp-Session-Id": "sess-1"})
            if m == "notifications/initialized":
                return 202, {}, b""
            assert h.get("mcp-session-id") == "sess-1" and h.get("mcp-protocol-version") == "2025-06-18"
        else:
            assert modern_req and h.get("mcp-method") == m and req["json"]["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] == V
        if m == "tools/list":
            return ok({"tools": [TOOL, {"name": "other", "inputSchema": {"type": "object"}}], "resultType": "complete", "ttlMs": 1000, "cacheScope": "public"})
        if m == "tools/call":
            self.calls.append(req)
            if self.call_status != 200:
                return self.call_status, {}, {}
            res = {**self.result, **({"resultType": self.result.get("resultType", "complete")} if not self.mode.startswith("legacy") else {})}
            if self.mode == "modern-sse":
                note = json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 1}})
                final = json.dumps({"jsonrpc": "2.0", "id": rid, "result": res})
                return 200, {"Content-Type": "text/event-stream"}, f": keep-alive\n\nevent: message\ndata: {note}\n\nevent: message\ndata: {final}\n\n".encode()
            return ok(res)
        return 404, {}, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}}


def mcp_dest(client, sink, **over):
    cfg = {"tool": "create_page", "bearer_token_env": "GROWTHOS_SECRET_MCP", "static_arguments": {"space": "NEWS"},
           "argument_map": {"title": "title", "body": "body", "link": "cta_url"}, **over}
    return feed(client, name="Wiki over MCP", slug="wiki-mcp", direction="outbound", protocol="mcp", url=sink.url + "/mcp", config=cfg)


def approved(client):
    c = make(client, classification="pr", title="Parinita launches GrowthOS", body="Parinita today announced GrowthOS.", cta_url="https://parinita.example/g")
    assert run_pipeline(client, c["id"])["state"] == "approved"
    return c["id"]


def publish(client, cid, ep):
    return client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)


@pytest.mark.parametrize("mode,era", [("modern-json", V), ("modern-sse", V), ("legacy", "initialize handshake"), ("legacy-says-so", "initialize handshake")])
def test_adapter_calls_the_tool_in_every_server_era(client, sink, lan, mode, era):
    sink.dynamic = mock = MockMcp(mode)
    r = publish(client, approved(client), mcp_dest(client, sink))
    assert r.status_code == 200, r.text
    assert r.json()["provider_id"] == "page-9" and era in r.json()["detail"]
    req = mock.calls[0]
    assert req["headers"]["authorization"] == "Bearer mcp-server-token" and "text/event-stream" in req["headers"]["accept"]
    args = req["json"]["params"]["arguments"]
    assert args == {"space": "NEWS", "title": "Parinita launches GrowthOS", "body": "Parinita today announced GrowthOS.",
                    "link": "https://parinita.example/g?utm_source=growthos&utm_medium=content&utm_campaign=always-on"}
    if mode.startswith("modern"):
        assert req["headers"]["mcp-name"] == "create_page" and req["headers"]["mcp-param-space"] == "NEWS"   # x-mcp-header mirrored
        assert "mcp-session-id" not in req["headers"]
    else:
        assert [q["method"] for q in sink.requests][-1] == "DELETE"            # the session we opened is closed


def test_adapter_failure_modes(client, sink, lan):
    cid = approved(client)
    sink.dynamic = MockMcp(result={"content": [{"type": "text", "text": "space NEWS is archived"}], "isError": True})
    ep = mcp_dest(client, sink)
    r = publish(client, cid, ep)
    assert r.status_code == 502 and "space NEWS is archived" in r.json()["detail"]
    sink.dynamic = MockMcp(result={"resultType": "input_required", "inputRequests": {"a": {}}})
    assert "interactive input" in publish(client, cid, ep).json()["detail"]
    sink.dynamic = mock = MockMcp(call_status=500)
    assert publish(client, cid, ep).status_code == 502 and len(mock.calls) == 1        # a tool call that may have run is never repeated
    client.patch(f"/v1/feeds/{ep['id']}", json={"config": {"tool": "delete_everything", "argument_map": {"t": "title"}}}, headers=BOOT)
    sink.dynamic = MockMcp()
    d = publish(client, cid, ep).json()["detail"]
    assert "no tool named 'delete_everything'" in d and "create_page" in d
    assert client.get(f"/v1/content/{cid}", headers=EDITOR).json()["state"] == "approved"   # never marked sent


def test_adapter_config_and_egress_rules(client, sink):
    base = {"name": "n", "slug": "m", "direction": "outbound", "protocol": "mcp", "url": "https://mcp.partner.example/mcp"}
    for cfg, needle in [({}, "config.tool"), ({"tool": "t"}, "argument_map"), ({"tool": "t", "argument_map": {"a": "password"}}, "unknown release field"),
                        ({"tool": "t", "argument_map": {"a": "title"}, "bearer_token_env": "API_KEY"}, "GROWTHOS_SECRET_")]:
        r = client.post("/v1/feeds", json={**base, "config": cfg}, headers=BOOT)
        assert r.status_code == 422 and needle in r.json()["detail"], r.text
    assert client.post("/v1/feeds", json={**base, "url": "", "config": {"tool": "t", "argument_map": {"a": "title"}}}, headers=BOOT).status_code == 422
    ep = mcp_dest(client, sink)                       # loopback URL, no `lan` fixture: the egress guard applies to MCP too
    r = publish(client, approved(client), ep)
    assert r.status_code == 400 and "non-public address" in r.json()["detail"] and sink.requests == []


def test_trusted_internal_hosts_are_an_explicit_operator_choice(monkeypatch):
    from app.netguard import DestinationBlocked, check_url
    with pytest.raises(DestinationBlocked):
        check_url("http://tapestry.fabric.internal/mcp")
    monkeypatch.setattr(settings, "trusted_internal_hosts", "fabric.internal, vaakd.pop.internal")
    assert check_url("http://tapestry.fabric.internal/mcp") and check_url("http://vaakd.pop.internal:8477")
    with pytest.raises(DestinationBlocked):
        check_url("http://169.254.169.254/latest/meta-data/")          # everything else still guarded


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return port


@needs_sdk
@pytest.mark.parametrize("mode", ["json", "sse"])
def test_interop_adapter_against_a_server_built_with_the_official_sdk(client, lan, tmp_path, mode):
    port, calls = _free_port(), tmp_path / "calls.jsonl"
    proc = subprocess.Popen([SDK_PY, str(INTEROP / "sdk_server.py"), str(port), mode, str(calls)], stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close(); break
            except OSError:
                time.sleep(0.1)
        cfg = {"tool": "post_message", "static_arguments": {"channel": "#news"}, "argument_map": {"text": "text"}}
        ep = feed(client, name="SDK server", slug="sdk", direction="outbound", protocol="mcp", url=f"http://127.0.0.1:{port}/mcp", config=cfg)
        cid = approved(client)
        r = publish(client, cid, ep)
        assert r.status_code == 200, r.text
        assert r.json()["provider_id"] == "msg-42" and V in r.json()["detail"]
        got = [json.loads(line) for line in calls.read_text().splitlines()]
        assert len(got) == 1 and got[0]["channel"] == "#news" and got[0]["text"].startswith("Parinita launches GrowthOS")
        client.patch(f"/v1/feeds/{ep['id']}", json={"config": {"tool": "always_fails", "argument_map": {"text": "title"}}}, headers=BOOT)
        r = publish(client, approved(client), ep)
        assert r.status_code == 502 and "tool 'always_fails' reported an error" in r.json()["detail"]   # the SDK masks the exception text
    finally:
        proc.terminate()
        proc.wait(timeout=10)
