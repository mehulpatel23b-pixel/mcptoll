# mcptoll ⚖️

**Measure the context-window toll of every MCP server in your agent config — one zero-dependency command, before your model pays for it.**

[![Python](https://img.shields.io/badge/Python-3.9%2B-000?style=flat-square&logo=python&logoColor=00FF41)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-000?style=flat-square&logo=opensourceinitiative&logoColor=00FF41)](LICENSE)
[![Dependencies](https://img.shields.io/badge/dependencies-0-000?style=flat-square&logo=cachet&logoColor=00FF41)](requirements.txt)
[![Tests](https://img.shields.io/badge/tests-24%2F24%20passing-000?style=flat-square&logo=checkmarx&logoColor=00FF41)](tests/test_mcptoll.py)

---

## The problem (2026's loudest agent pain point)

Every MCP server you connect to an AI agent gets **flattened into its system prompt**: every tool name, every description, every JSON Schema. The reports are brutal — [GitHub's own MCP server alone consumes ~17,600 tokens of tool definitions](https://www.stackone.com/blog/mcp-token-optimization/), and practitioners describe [wasting 31% of their context window](https://tylerfolkman.substack.com/p/i-was-wasting-31-of-my-context-window) on tool schemas they rarely call. The MCP spec team has open proposals ([SEP-1576](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1576), [discussions #2036](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/2036), [#2812](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/2812)) about exactly this problem, because >20 connected tools measurably degrades tool selection and answer quality.

But when your agent gets dumber, nothing tells you *which server is eating the budget*. You guess. `mcptoll` replaces the guess with a ranked, measured audit:

- 📡 **Live probes** — it spawns each stdio server from your config, does the real MCP JSON-RPC handshake (`initialize` → `notifications/initialized` → `tools/list`), and weighs every tool definition that comes back.
- ⚖️ **Token weights** — per-tool, per-server, and per-config schema cost (est. tokens + % of your model's context budget).
- 🚩 **Bloat forensics** — duplicate tool names across servers, tool overload (>20 tools), novel-length tool descriptions, heavyweight input schemas, remote servers you forgot about.
- ✂️ **Cut-list** — a drop order ranked by tokens saved, so the first line of the fix is already written for you.

> **Sibling tools:** [mcp-probe](https://github.com/mehulpatel23b-pixel/mcp-probe) asks *"does this MCP server work?"* (handshake, call every tool once). **mcptoll** asks *"what does it cost?"* (schema weight, budget share, cut-list). Different questions, same ecosystem.

---

## Installation

```bash
# from source
git clone https://github.com/mehulpatel23b-pixel/mcptoll.git
cd mcptoll
pip install .          # installs the `mcptoll` console entrypoint

# or run in place, no install required
python3 -m mcptoll.cli --help
```

Requirements: **Python 3.9+, zero external dependencies** — pure standard library, so it runs on a locked-down CI runner or a minimal container with nothing but `pip`.

---

## Quick start

```bash
# audit every MCP config it can find (cwd + Claude Desktop + Cursor global paths)
mcptoll

# audit one specific config
mcptoll ~/.cursor/mcp.json

# audit one ad-hoc server without a config file
mcptoll --cmd "npx -y @modelcontextprotocol/server-filesystem /tmp"

# compare against your actual model's budget
mcptoll --budget 1000000        # Gemini-class window

# machine-readable output for CI / scripts
mcptoll --json > audit.json
```

### Real sample output

Captured from a real run against the bundled fixture servers (`mini` = 3 small tools, `bloat` = 26 tools incl. a duplicate, a ~1,490-token description and a ~3,256-token schema):

```
==============================================================================
CONFIG  /tmp/sample_mcp.json   (client: generic)
==============================================================================
  SERVER                  TOOLS SCHEMA TOK  % BUDGET  HEAVIEST TOOL      STATUS
  --------------------------------------------------------------------------
  mini                        3         98      0.5%  add                ok (LEAN)
  bloat                      26      5,472     27.4%  everything         ok (FAT)
  fixture-remote              0          0      0.0%  -                  not-probed
  --------------------------------------------------------------------------
  TOTAL: 29 tools, 5,570 schema tokens = 27.9% of 20,000-token budget  ->  VERDICT: FAT
  flags:
    ! UNPROBED:fixture-remote:remote/http server, weight unknown (use --probe-http or audit locally)
    ! DUPLICATE_TOOL:ping:exposed by 2 servers (bloat, mini) - double context cost, agent confusion
    ! TOOL_OVERLOAD:bloat:26 tools (> 20) degrades tool selection
    ! FAT_DESCRIPTION:bloat:verbose_ping ~1490-token description
    ! HEAVY_SCHEMA:bloat:everything inputSchema ~3256 tokens
  cut-list (drop order, biggest win first):
    - bloat                       5,472 tokens (27.4% of budget)
    - mini                           98 tokens (0.5% of budget)

==============================================================================
mcptoll done. worst verdict across configs: FAT
```

---

## How it works

```
 mcp.json / .mcp.json / claude_desktop_config.json / --cmd
        │
        ▼
 ┌──────────────┐   stdio spawn      ┌───────────────────┐
 │ config layer │ ─────────────────► │  live MCP probe   │
 │  (parse +    │   JSON-RPC          │  initialize +     │
 │   env expand)│   handshake        │  tools/list       │
 └──────────────┘                    └─────────┬─────────┘
                                               │ tool definitions
                                               ▼
                                     ┌───────────────────┐
                                     │  weigh + flag     │
                                     │  tokenizer est.,  │
                                     │  duplicates,      │
                                     │  overload, fat    │
                                     │  desc/schema      │
                                     └─────────┬─────────┘
                                               │
                              ┌────────────────┴───────────────┐
                              ▼                                ▼
                        text report                        JSON (CI)
                        verdict + cut-list                 exit codes
```

1. **Config layer** — discovers `mcp.json`, `.mcp.json`, `claude_desktop_config.json` in the project tree plus Claude Desktop / Cursor global locations; expands `${VAR}` / `${VAR:-default}` env references; tolerates disabled and malformed entries (flags them instead of crashing).
2. **Live probe** — spawns each stdio server, performs the genuine MCP 2024-11-05 handshake, and captures `tools/list` exactly as a client would. Remote (http/sse) servers are **never dialed**: they come back `not-probed`, which is itself a finding.
3. **Weigh** — canonical-JSON each tool definition and estimate tokens with a documented chars/4 heuristic (consistent across all servers, which is what a *ranking* needs).
4. **Flag + cut-list** — cross-server duplicate tools, >20-tool overload, >800-token descriptions, >300-token schemas, budget-percent verdicts (`LEAN` <10%, `OK` <25%, `FAT` <50%, `BLOAT` ≥50%), and a ranked drop order.

### Exit codes (CI gate)

| Code | Meaning |
|------|---------|
| `0` | All configs `LEAN`/`OK`, no flags — your tool budget is fine |
| `1` | `FAT`/`BLOAT` verdict or any bloat flag — fix before merging |
| `2` | Probe/pipeline errors (a server failed to spawn/handshake, unreadable config, or no config found) |
| `64` | Usage error (bad arguments) |

```yaml
# GitHub Actions: fail when a PR grows the agent's context tax
- run: pip install .
- run: mcptoll .mcp.json --json && test "$(jq '.configs[0].summary.budget_pct' )" -lt 25
```

---

## Real-world use cases

1. **Agent repo CI gate** — every PR to any repo that ships an `.mcp.json` gets weighed; a new integration that adds 14k tokens of schema fails the build with `exit 1` and the cut-list names the offender.
2. **Agent quality triage** — your coding agent got noticeably dumber since onboarding three MCP servers? One command shows the exact per-server token toll and whether you crossed the 20-tool overload line.
3. **MCP server author debugging** — you wrote a server; see your own tool definitions the way the model pays for them, spot the 1,500-token description you accidentally shipped, and trim it before users file issues.
4. **Platform team audits** — audit the org's standard agent config file, produce `audit.json` per team, and rank teams by context-window waste to prioritize migrations to progressive disclosure.
5. **Pre-migration weigh-in** — before switching agents from 128k-class to 1M-class windows (or vice versa), measure the real schema load once instead of arguing about it in a design doc.
6. **Vendor evaluation** — comparing two third-party MCP servers for the same job? `mcptoll --cmd "..."` on each gives you their context price tag side by side.
7. **Incident forensics** — agent kept ignoring a tool? `DUPLICATE_TOOL:ping:exposed by 2 servers (bloat, mini)` explains it — and the cut-list shows which entry to delete.

---

## Project structure

```
mcptoll/
├── src/mcptoll/
│   ├── __init__.py      # public API re-exports
│   ├── cli.py           # argparse CLI, exit-code policy, ad-hoc --cmd mode
│   ├── config.py        # discovery, parsing, ${VAR} expansion, client detection
│   ├── probe.py         # stdio JSON-RPC handshake (initialize → tools/list)
│   ├── estimate.py      # token estimation, verdicts, bloat flags
│   └── report.py        # text table + cut-list, JSON serializer
├── tests/
│   ├── test_mcptoll.py  # 24 tests: real subprocess probes, CLI, exit codes
│   └── fixtures/        # speak real MCP stdio protocol over pipes
│       ├── fixture_server.py  # shared line-protocol test double
│       ├── mini_server.py     # 3 lean tools
│       └── bloat_server.py    # 26 tools: duplicates, fat desc, heavy schema
├── pyproject.toml       # console entrypoint: mcptoll
├── requirements.txt     # empty on purpose (stdlib only)
├── .gitignore
├── LICENSE              # MIT
└── README.md
```

Run the suite:

```bash
python3 -m unittest discover -s tests -v   # 24/24
# or
PYTHONPATH=src pytest
```

---

## Honesty section

- **Token counts are estimates.** mcptoll uses a chars-per-token heuristic on canonical JSON — deliberately, because bundling a BPE tokenizer would break the zero-dependency promise. All servers are measured by the same yardstick, so the *ranking* and *percent-of-budget* figures are robust even if absolute counts drift ±15% for tokenizer-specific cases.
- **It measures the declarative layer.** The MCP `tools/list` payload is what a flattening client injects into context; smarter clients use progressive disclosure or tool search and pay less. mcptoll reports your worst-case exposure — the number most agent setups still live at today.
- **Remote servers show as `not-probed`, not weightless.** Offline by design: mcptoll never dials remote URLs or sends your config anywhere. Audit remote servers by running them locally and pointing a config entry at the local instance.
- **A LEAN verdict is not a security attestation.** It says your schemas are cheap, not that your servers are safe.

---

## Contributing

Issues and PRs welcome. Bug reports that include a minimal MCP config (redact secrets) reproduce fastest. Tests must stay at 100% pass — run `python3 -m unittest discover -s tests` before submitting.

## License

[MIT](LICENSE) © 2026 Mehul Patel
