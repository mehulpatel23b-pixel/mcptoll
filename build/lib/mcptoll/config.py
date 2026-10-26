"""Discovery and parsing of MCP client config files.

Supports the three dominant on-disk shapes (they all use the same
{"mcpServers": {...}} envelope, with minor client variations):

* Claude Desktop  - ~/Library/Application Support/Claude/claude_desktop_config.json
                    (macOS) or ~/.config/Claude/claude_desktop_config.json
* Claude Code     - .mcp.json in a project directory
* Cursor / generic - mcp.json, ~/.cursor/mcp.json

Env substitution: MCP configs may reference ${VAR} or ${VAR:-default}
inside `env`, `args` and `url`. Values are expanded from the current
environment; unset vars without a default expand to empty (the child
process fails loudly, which probe reports as `error`).
"""

import json
import os
import re

CONFIG_BASENAMES = ("mcp.json", ".mcp.json", "claude_desktop_config.json")
SERVERS_KEYS = ("mcpServers", "servers")


def _expand(value, environ):
    """Expand ${VAR} and ${VAR:-default} references in a string."""

    def sub(match):
        name, default = match.group(1), match.group(3) or ""
        return environ.get(name, default)

    if isinstance(value, str):
        return re.sub(r"\$\{([A-Z0-9_]+)(:-([^}]*))?\}", sub, value)
    if isinstance(value, list):
        return [_expand(item, environ) for item in value]
    if isinstance(value, dict):
        return {k: _expand(v, environ) for k, v in value.items()}
    return value


def standard_locations():
    """Global config paths used by desktop clients, if they exist."""
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "Library", "Application Support", "Claude",
                     "claude_desktop_config.json"),
        os.path.join(home, ".config", "Claude", "claude_desktop_config.json"),
        os.path.join(home, ".cursor", "mcp.json"),
    ]
    return [p for p in candidates if os.path.isfile(p)]


def discover_configs(root="."):
    """Find MCP config files under `root` plus standard global locations."""
    found = []
    for dirpath, dirnames, filenames in os.walk(os.path.abspath(root)):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "node_modules", ".venv", "venv", "__pycache__")]
        for base in CONFIG_BASENAMES:
            if base in filenames:
                found.append(os.path.join(dirpath, base))
    for path in standard_locations():
        if path not in found:
            found.append(path)
    return sorted(set(found))


def load_config(path, environ=None):
    """Parse one MCP client config into a normalized server list.

    Returns
    -------
    dict with:
      path    - config file path
      client  - guessed client name
      servers - list of {name, transport, command, args, env, url}

    Raises
    ------
    ValueError on unreadable JSON or a shape it cannot make sense of.
    """
    environ = environ if environ is not None else os.environ
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    base = os.path.basename(path)
    if base == "claude_desktop_config.json":
        client = "Claude Desktop"
    elif base == ".mcp.json":
        client = "Claude Code"
    elif "cursor" in path.lower():
        client = "Cursor"
    else:
        client = "generic"

    raw = None
    for key in SERVERS_KEYS:
        if isinstance(data, dict) and isinstance(data.get(key), dict):
            raw = data[key]
            break
    if raw is None and isinstance(data, dict) and not data:
        raw = {}
    if raw is None:
        raise ValueError(
            "no %s section found in %s"
            % ("/".join(SERVERS_KEYS), path)
        )

    servers = []
    for name, spec in raw.items():
        spec = _expand(spec or {}, environ)
        if "url" in spec and "command" not in spec:
            transport = "http"
        elif "command" in spec:
            transport = "stdio"
        else:
            # Unusable entry: keep it so the report can flag it.
            transport = "invalid"
        servers.append(
            {
                "name": str(name),
                "transport": transport,
                "command": spec.get("command"),
                "args": spec.get("args") or [],
                "env": spec.get("env") or {},
                "url": spec.get("url"),
                "disabled": bool(spec.get("disabled")),
            }
        )
    return {"path": path, "client": client, "servers": servers}
