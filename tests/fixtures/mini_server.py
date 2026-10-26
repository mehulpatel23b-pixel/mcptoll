"""Tiny stdio MCP fixture: 3 tools, small schemas (a lean server)."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from fixture_server import make_tools, serve

TOOLS = make_tools([
    {"name": "echo", "description": "Echo a message back.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
    {"name": "add", "description": "Add two integers.",
     "inputSchema": {"type": "object",
                     "properties": {"a": {"type": "integer"},
                                    "b": {"type": "integer"}}}},
    {"name": "ping", "description": "Return pong."},
])

if __name__ == "__main__":
    serve(TOOLS)
