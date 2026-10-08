"""A real MCP server built with the official Python SDK. Used to prove the GrowthOS `mcp` adapter interoperates.
usage: sdk_server.py <port> <json|sse> <calls-file>"""
import json
import sys

import uvicorn
from mcp.server.mcpserver import MCPServer

port, mode, calls_file = int(sys.argv[1]), sys.argv[2], sys.argv[3]
server = MCPServer("interop-sink")


@server.tool()
def post_message(channel: str, text: str) -> dict:
    """Post a message to a channel."""
    with open(calls_file, "a") as f:
        f.write(json.dumps({"channel": channel, "text": text}) + "\n")
    return {"id": "msg-42", "channel": channel}


@server.tool()
def always_fails(text: str) -> str:
    """A tool that raises."""
    raise RuntimeError("downstream system is read-only today")


uvicorn.run(server.streamable_http_app(json_response=(mode == "json"), stateless_http=True), host="127.0.0.1", port=port, log_level="warning")
