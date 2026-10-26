"""Text and JSON renderers for mcptoll results."""

import json


def _fmt_int(value):
    return "{:,}".format(value if isinstance(value, int) else int(value))


def render_json(results):
    """Serialize full per-config results as JSON."""
    return json.dumps({"configs": results}, indent=2, sort_keys=True)


def render_text(results, executable="mcptoll"):
    """Render human-readable report; also returns the exit code hint."""
    lines = []
    flags_total = 0
    worst = "LEAN"
    order = {"LEAN": 0, "OK": 1, "FAT": 2, "BLOAT": 3}
    for cfg in results:
        lines.append("=" * 78)
        lines.append("CONFIG  %s   (client: %s)" % (cfg["path"], cfg["client"]))
        lines.append("=" * 78)
        if not cfg["servers"]:
            lines.append("  no MCP servers declared.")
            continue
        header = (
            "  %-22s %6s %10s %9s  %-18s %s"
            % ("SERVER", "TOOLS", "SCHEMA TOK", "% BUDGET", "HEAVIEST TOOL", "STATUS")
        )
        lines.append(header)
        lines.append("  " + "-" * 74)
        for srv in cfg["servers"]:
            recs = srv.get("tool_records", [])
            heaviest = max(recs, key=lambda r: r["tokens"]) if recs else {}
            pct = srv.get("budget_pct", 0.0)
            status = srv["status"]
            if recs and status == "ok":
                status += " (%s)" % srv["verdict"]
            lines.append(
                "  %-22s %6s %10s %8s%%  %-18s %s"
                % (
                    (srv["server"][:22] if srv["server"] else "<unnamed>"),
                    _fmt_int(len(recs)),
                    _fmt_int(srv.get("total_tokens", 0)),
                    "%.1f" % pct,
                    (heaviest.get("name", "-")[:18]),
                    status
                    + (" ERR: %s" % srv["error"] if srv["status"] == "error" and srv.get("error") else ""),
                )
            )
        lines.append("  " + "-" * 74)
        lines.append(
            "  TOTAL: %s tools, %s schema tokens = %.1f%% of %s-token budget  ->  VERDICT: %s"
            % (
                _fmt_int(cfg["summary"]["total_tools"]),
                _fmt_int(cfg["summary"]["total_tokens"]),
                cfg["summary"]["budget_pct"],
                _fmt_int(cfg["summary"]["budget"]),
                cfg["summary"]["verdict"],
            )
        )
        if cfg["summary"]["flags"]:
            flags_total += len(cfg["summary"]["flags"])
            worst = max(worst, cfg["summary"]["verdict"], key=lambda v: order[v])
            lines.append("  flags:")
            for flag in cfg["summary"]["flags"]:
                lines.append("    ! %s" % flag)
            cutlist = cfg["cutlist"]
            if cutlist:
                lines.append("  cut-list (drop order, biggest win first):")
                saved = 0
                for item in cutlist[:3]:
                    saved += item["tokens"]
                    lines.append(
                        "    - %-22s %10s tokens (%.1f%% of budget)"
                        % (item["server"], _fmt_int(item["tokens"]), item["pct"])
                    )
        worst = max(worst, cfg["summary"]["verdict"], key=lambda v: order[v])
        lines.append("")
    lines.append("=" * 78)
    lines.append("mcptoll done. worst verdict across configs: %s" % worst)
    return "\n".join(lines), worst, flags_total
