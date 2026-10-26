"""Bloated stdio MCP fixture: duplicate tools + overload + fat schemas."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from fixture_server import make_tools, serve

# 25 tools (> 20 threshold -> TOOL_OVERLOAD), with one duplicate of
# `ping` (shared with mini_server to trigger DUPLICATE_TOOL), one
# novel-length description (-> FAT_DESCRIPTION) and one giant schema
# (-> HEAVY_SCHEMA).

_big_props = {("prop_%02d" % i): {"type": "string", "description": "field %d" % i}
              for i in range(220)}

TOOLS = make_tools(
    [{"name": "tool_%02d" % i, "description": "Filler tool number %d." % i} for i in range(23)]
    + [
        {"name": "ping", "description": "Return pong."},  # duplicate name
        {
            "name": "verbose_ping",
            "description": "Ping the server. " + ("This description goes on and on. " * 180),
        },
        {"name": "everything", "inputSchema": {"type": "object", "properties": _big_props}},
    ]
)

if __name__ == "__main__":
    serve(TOOLS)
