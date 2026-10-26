"""Shared JSON-RPC line protocol for test fixture MCP servers.

This is NOT a general server - just enough protocol for mcptoll's
handshake in tests: initialize, notifications/initialized, tools/list.
"""

import json
import sys


def make_tools(tool_specs):
    return [
        {
            "name": spec["name"],
            "description": spec.get("description", "test tool %s" % spec["name"]),
            "inputSchema": spec.get("inputSchema", {"type": "object", "properties": {}}),
        }
        for spec in tool_specs
    ]


def serve(tools):
    """Blocking stdin/stdout loop speaking MCP stdio JSON-RPC."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method", "")
        if method == "initialize":
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0",
                "id": msg["id"],
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fixture", "version": "0.1.0"},
                },
            }) + "\n")
            sys.stdout.flush()
        elif method == "tools/list":
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0",
                "id": msg["id"],
                "result": {"tools": tools},
            }) + "\n")
            sys.stdout.flush()
        # notifications (e.g. notifications/initialized) need no reply
