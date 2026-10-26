"""mcptoll - measure the context-window toll of your MCP servers.

Public API re-exports the pieces the CLI and tests use:

    from mcptoll import estimate_tools, estimate_tokens, load_config, probe_stdio
"""

__version__ = "1.0.0"

from .estimate import estimate_tokens, estimate_tools, evaluate_flags, verdict_for
from .config import load_config, discover_configs
from .probe import probe_stdio
from .report import render_text, render_json

__all__ = [
    "estimate_tokens",
    "estimate_tools",
    "evaluate_flags",
    "verdict_for",
    "load_config",
    "discover_configs",
    "probe_stdio",
    "render_text",
    "render_json",
    "__version__",
]
