"""mcptoll CLI.

Usage:
    mcptoll                     # auto-discover configs in cwd + global locations
    mcptoll path/to/mcp.json    # audit specific config file(s)
    mcptoll --cmd "npx -y some-mcp-server --flag"   # audit one ad-hoc server
    mcptoll --json              # machine-readable output for CI
"""

import argparse
import shlex
import sys

from . import __version__
from .config import discover_configs, load_config
from .estimate import estimate_tools, evaluate_flags, verdict_for
from .probe import DEFAULT_TIMEOUT, probe_stdio
from .report import render_json, render_text

_ORDER = {"LEAN": 0, "OK": 1, "FAT": 2, "BLOAT": 3}


def _audit_server(server, budget, timeout):
    """Probe one server and attach token weights + per-server budget data."""
    probe = probe_stdio(server, timeout=timeout)
    tool_records = estimate_tools(probe["tools"]) if probe["status"] == "ok" else []
    total = sum(rec["tokens"] for rec in tool_records)
    pct = (total / budget * 100) if budget else 0.0
    server_result = dict(probe)
    server_result["tool_records"] = tool_records
    server_result["total_tokens"] = total
    server_result["budget_pct"] = round(pct, 2)
    server_result["verdict"] = verdict_for(pct)
    return server_result


def _audit_config(path, budget, timeout):
    """Full audit of one config file: probe servers, weigh, flag, cut-list."""
    cfg = load_config(path)
    results = [_audit_server(s, budget, timeout)
               for s in cfg["servers"] if not s.get("disabled")]
    disabled = [s["name"] for s in cfg["servers"] if s.get("disabled")]
    if disabled:
        results.append(
            {
                "server": "(%d disabled)" % len(disabled),
                "transport": "disabled",
                "status": "not-probed",
                "tools": [],
                "tool_records": [],
                "total_tokens": 0,
                "budget_pct": 0.0,
                "verdict": None,
                "error": "disabled in config: %s" % ", ".join(disabled),
            }
        )
    summary = evaluate_flags(results, budget)
    cutlist = [
        {
            "server": r["server"],
            "tokens": r["total_tokens"],
            "pct": r["budget_pct"],
        }
        for r in sorted(results, key=lambda r: r.get("total_tokens", 0), reverse=True)
        if r.get("total_tokens", 0) > 0
    ]
    return {
        "path": cfg["path"],
        "client": cfg["client"],
        "servers": results,
        "summary": summary,
        "cutlist": cutlist,
    }


def _split_cmd(raw):
    parts = shlex.split(raw)
    if not parts:
        raise ValueError("empty --cmd")
    return {"name": parts[0], "transport": "stdio", "command": parts[0],
            "args": parts[1:], "env": {}, "url": None, "disabled": False}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("mcptoll: error: %s\n" % message)
        sys.exit(64)


def build_parser():
    parser = _Parser(
        prog="mcptoll",
        description="Measure the context-window toll of every MCP server in your config.",
    )
    parser.add_argument("paths", nargs="*",
                        help="MCP config file(s); default: auto-discover")
    parser.add_argument("--cmd",
                        help="audit one ad-hoc stdio server, e.g. --cmd 'npx -y foo'")
    parser.add_argument("--budget", type=int, default=200000,
                        help="model context budget in tokens (default 200000)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="per-server probe timeout seconds (default %.0f)" % DEFAULT_TIMEOUT)
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="emit JSON instead of text")
    parser.add_argument("--version", action="version",
                        version="mcptoll %s" % __version__)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    budget = args.budget if args.budget > 0 else 1
    results = []
    had_parse_error = False

    if args.cmd:
        try:
            server = _split_cmd(args.cmd)
        except ValueError as exc:
            print("mcptoll: %s" % exc, file=sys.stderr)
            return 64
        probed = _audit_server(server, budget, args.timeout)
        tool_records = probed.pop("tool_records")
        summary = evaluate_flags([dict(probed, tool_records=tool_records)], budget)
        results.append(
            {
                "path": "cmd: %s" % args.cmd,
                "client": "ad-hoc",
                "servers": [dict(probed, tool_records=tool_records)],
                "summary": summary,
                "cutlist": [],
            }
        )
    else:
        paths = args.paths or discover_configs()
        if not paths:
            print("mcptoll: no MCP config files found (pass a path or use --cmd)",
                  file=sys.stderr)
            return 2
        for path in paths:
            try:
                results.append(_audit_config(path, budget, args.timeout))
            except (ValueError, OSError) as exc:
                print("mcptoll: %s: %s" % (path, exc), file=sys.stderr)
                had_parse_error = True

    probe_errors = any(srv["status"] == "error" for cfg in results
                      for srv in cfg["servers"])

    if args.as_json:
        print(render_json(results))
        worst = max((cfg["summary"]["verdict"] for cfg in results if cfg["servers"]),
                    key=lambda v: _ORDER[v], default="LEAN")
        flags_total = sum(len(cfg["summary"]["flags"]) for cfg in results)
    else:
        text, worst, flags_total = render_text(results)
        print(text)

    if had_parse_error or probe_errors:
        return 2
    if worst in ("FAT", "BLOAT") or flags_total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
