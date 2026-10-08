"""Drive the GrowthOS MCP server with the official Python SDK client. Prints one JSON document.
usage: sdk_client.py <mcp-url> <api-key> <webhook-destination-slug>"""
import asyncio
import inspect
import json
import sys

from mcp import Client
from mcp.client import streamable_http as sh

url, key, dest = sys.argv[1], sys.argv[2], sys.argv[3]


def transport():
    headers = {"X-API-Key": key}
    if "headers" in inspect.signature(sh.streamable_http_client).parameters:
        return sh.streamable_http_client(url, headers=headers)
    return sh.streamable_http_client(url, http_client=sh.create_mcp_http_client(headers=headers))


def data(result):
    return result.structured_content if result.structured_content is not None else json.loads(result.content[0].text)


async def main():
    out = {}
    async with Client(transport()) as c:
        out["protocol_version"] = c.protocol_version
        out["server"] = c.server_info.name
        tools = await c.list_tools()
        out["tools"] = [t.name for t in tools.tools]
        draft = data(await c.call_tool("create_draft", {"title": "Agent drafted release", "classification": "pr",
                                                        "body": "GrowthOS now speaks MCP.\nCustomers love it."}))
        rid = draft["id"]
        out["blocked_first"] = data(await c.call_tool("run_checks", {"id": rid}))["clear_to_release"]
        ledger = data(await c.call_tool("get_sentence_ledger", {"id": rid}))
        for s in ledger["sentences"]:
            if s["status"] == "open":
                await c.call_tool("attach_evidence", {"id": rid, "text": s["text"], "source_uri": "internal://launch-brief", "sentence_hash": s["hash"]})
        checks = data(await c.call_tool("run_checks", {"id": rid}))
        out["clear_after_evidence"], out["state"] = checks["clear_to_release"], checks["state"]
        sent = await c.call_tool("send_release", {"id": rid, "destination": dest})
        out["send_is_error"], out["sent"] = sent.is_error, data(sent) if not sent.is_error else sent.content[0].text
        bad = await c.call_tool("verify_audit_chain", {})
        out["auditor_tool_refused"] = bad.is_error
        out["release_id"] = rid
    print(json.dumps(out))


asyncio.run(main())
