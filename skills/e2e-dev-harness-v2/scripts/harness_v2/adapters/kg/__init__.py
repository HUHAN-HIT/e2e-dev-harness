"""Narrow kg-evidence interface (ported from legacy kg_refresh; logic unchanged).

The legacy module imports its sibling `common` by flat name, so we put the
vendored `_legacy/` dir on sys.path once, then re-export the public surface.
GitNexus / git are invoked via subprocess inside `detect`/`run_command`; callers
without those tools get the same `availability`-gated behavior as legacy.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LEGACY = Path(__file__).resolve().parent / "_legacy"
if str(_LEGACY) not in sys.path:
    sys.path.insert(0, str(_LEGACY))

import kg_refresh  # noqa: E402

detect = kg_refresh.detect
detect_gitnexus_index = kg_refresh.detect_gitnexus_index
choose_tools = kg_refresh.choose_tools
suggested_commands = kg_refresh.suggested_commands
run_command = kg_refresh.run_command

__all__ = [
    "detect",
    "detect_gitnexus_index",
    "choose_tools",
    "suggested_commands",
    "run_command",
]
