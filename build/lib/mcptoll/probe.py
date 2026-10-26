"""Live stdio probe for MCP servers.

Spawns each stdio server declared in a config, performs the real MCP
JSON-RPC handshake (initialize -> notifications/initialized ->
tools/list), and returns the tool definitions whose JSON weight is
measured downstream. Remote (http/sse) servers are never dialed
offline; they come back as `not-probed` so the report can say so.

This mirrors the proven handshake pattern of mcp-probe (a sibling repo
that asks "does it work?"); here we only need the shape of the payload
to answer "what does it cost?".
"""

import json
import os
import subprocess
import time

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 10.0


class _Protocol:
    """Line-oriented JSON-RPC conversation over a child's stdio."""

    def __init__(self, proc, timeout):
        self.proc = proc
        self.deadline = time.monotonic() + timeout

    def _read_line(self):
        if time.monotonic() > self.deadline:
            raise TimeoutError("probe timed out")
        line = self.proc.stdout.readline()
        if not line:
            raise EOFError("server closed stdout")
        return line

    def request(self, method, params, req_id):
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        )
        self.proc.stdin.write(payload + "\n")
        self.proc.stdin.flush()
        while True:
            line = self._read_line()
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # banner noise, stderr kept separate
            if message.get("id") != req_id:
                continue  # notification or someone else's response
            if "error" in message:
                raise RuntimeError(
                    "rpc error %s: %s"
                    % (message["error"].get("code"), message["error"].get("message"))
                )
            return message.get("result")

    def notify(self, method):
        payload = json.dumps({"jsonrpc": "2.0", "method": method})
        self.proc.stdin.write(payload + "\n")
        self.proc.stdin.flush()


def probe_stdio(server, timeout=DEFAULT_TIMEOUT):
    """Handshake one stdio MCP server and return a probe report dict.

    Parameters
    ----------
    server : dict
        Normalized server record from config.load_config.

    Returns
    -------
    dict: {server, status, transport, tools, error}
        status is one of: ok, not-probed, error.
    """
    report = {
        "server": server["name"],
        "transport": server["transport"],
        "status": "not-probed",
        "tools": [],
        "error": None,
    }
    if server["transport"] != "stdio" or not server.get("command"):
        if server["transport"] == "invalid":
            report["status"] = "error"
            report["error"] = "no command or url - unusable entry"
        else:
            report["error"] = "http/remote server (offline probe only)"
        return report

    env = dict(os.environ)
    env.update(server.get("env") or {})
    try:
        proc = subprocess.Popen(
            [server["command"]] + list(server["args"]),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            text=True,
            bufsize=1,
        )
    except (OSError, ValueError) as exc:
        report["status"] = "error"
        report["error"] = "failed to spawn %s: %s" % (server["command"], exc)
        return report

    try:
        proto = _Protocol(proc, timeout)
        proto.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcptoll", "version": "1.0.0"},
            },
            req_id=1,
        )
        proto.notify("notifications/initialized")
        result = proto.request("tools/list", {}, req_id=2)
        tools = (result or {}).get("tools", [])
        report["status"] = "ok"
        report["tools"] = tools
    except (TimeoutError, EOFError, RuntimeError, json.JSONDecodeError) as exc:
        report["status"] = "error"
        report["error"] = str(exc)
    finally:
        for stream in (getattr(proc, "stdin", None), getattr(proc, "stdout", None)):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
            proc.wait()
    return report
