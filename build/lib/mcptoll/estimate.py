"""Token estimation and bloat flags for MCP tool schemas.

The estimator is deliberately simple: JSON content is ASCII-split and
divided by ~4 characters per token (the classic heuristic that works
well for JSON Schema text). It is an approximation - documented as such
in the README - because pulling a real BPE tokenizer in would betray the
zero-dependency promise. It is consistently wrong in the same direction
for every server, which is exactly what a *ranking* tool needs.
"""

import json
import math

# Chars per token. Conservative for machine-generated JSON Schema text.
CHARS_PER_TOKEN = 4.0

# Flag thresholds (tunable via CLI in report paths).
TOO_MANY_TOOLS = 20          # articles/spec discussions: >20 tools degrades selection
FAT_DESC_CHARS = 3200        # ~800 tokens of prose for ONE tool description
HEAVY_SCHEMA_TOKENS = 300    # a single inputSchema costing more than this is heavy
BUDGET_PCT_LEAN = 10         # <10% of budget
BUDGET_PCT_OK = 25           # <25% of budget
BUDGET_PCT_FAT = 50          # <50% of budget, else BLOAT

VERDICTS = ("LEAN", "OK", "FAT", "BLOAT")


def estimate_tokens(text):
    """Approximate token count for a chunk of text (>= 1 for non-empty)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def _tool_definition_text(tool):
    """Canonical JSON text of what the model would actually see per tool."""
    return json.dumps(tool, sort_keys=True, ensure_ascii=False)


def estimate_tools(tools):
    """Return per-tool token estimates for a tools/list result.

    Parameters
    ----------
    tools : list[dict]
        MCP tool definitions as returned by tools/list.

    Returns
    -------
    list[dict]
        One record per tool: name, tokens, description_tokens,
        schema_tokens, descriptor_chars.
    """
    records = []
    for tool in tools or []:
        name = (tool or {}).get("name", "<unnamed>")
        desc = (tool or {}).get("description") or ""
        schema = (tool or {}).get("inputSchema") or {}
        records.append(
            {
                "name": name,
                "tokens": estimate_tokens(_tool_definition_text(tool)),
                "description_tokens": estimate_tokens(desc),
                "schema_tokens": estimate_tokens(json.dumps(schema)),
                "description_chars": len(desc),
            }
        )
    return records


def evaluate_flags(server_reports, budget):
    """Fold per-server reports into config-level flags + a verdict.

    server_reports : list[dict]
        Records produced by probe_stdio + estimate_tools, each with keys
        server, tools_records, status.
    budget : int
        Context budget in tokens for percentage math.

    Returns
    -------
    dict with flags (list[str]), totals, verdict.
    """
    total_tokens = 0
    total_tools = 0
    tool_owners = {}
    flags = []

    for report in server_reports:
        for rec in report.get("tool_records", []):
            total_tokens += rec["tokens"]
            tool_owners.setdefault(rec["name"], []).append(report["server"])
        total_tools += len(report.get("tool_records", []))
        if report["status"] == "not-probed":
            flags.append(
                "UNPROBED:%s:remote/http server, weight unknown (use --probe-http or audit locally)"
                % report["server"]
            )

    for tool_name, owners in sorted(tool_owners.items()):
        if len(owners) > 1:
            flags.append(
                "DUPLICATE_TOOL:%s:exposed by %d servers (%s) - double context cost, agent confusion"
                % (tool_name, len(owners), ", ".join(sorted(set(owners))))
            )

    for report in server_reports:
        recs = report.get("tool_records", [])
        server = report["server"]
        if report["status"] == "ok":
            if len(recs) > TOO_MANY_TOOLS:
                flags.append(
                    f"TOOL_OVERLOAD:{server}:{len(recs)} tools (> {TOO_MANY_TOOLS}) degrades tool selection"
                )
            for rec in recs:
                if rec["description_chars"] > FAT_DESC_CHARS:
                    flags.append(
                        "FAT_DESCRIPTION:%s:%s ~%d-token description"
                        % (server, rec["name"], rec["description_tokens"])
                    )
                if rec["schema_tokens"] > HEAVY_SCHEMA_TOKENS:
                    flags.append(
                        "HEAVY_SCHEMA:%s:%s inputSchema ~%d tokens"
                        % (server, rec["name"], rec["schema_tokens"])
                    )

    pct = (total_tokens / budget * 100) if budget else 0.0
    verdict = verdict_for(pct)
    return {
        "flags": flags,
        "total_tools": total_tools,
        "total_tokens": total_tokens,
        "budget": budget,
        "budget_pct": round(pct, 2),
        "verdict": verdict,
    }


def verdict_for(pct):
    """Map a percentage-of-budget to LEAN/OK/FAT/BLOAT."""
    if pct < BUDGET_PCT_LEAN:
        return "LEAN"
    if pct < BUDGET_PCT_OK:
        return "OK"
    if pct < BUDGET_PCT_FAT:
        return "FAT"
    return "BLOAT"
