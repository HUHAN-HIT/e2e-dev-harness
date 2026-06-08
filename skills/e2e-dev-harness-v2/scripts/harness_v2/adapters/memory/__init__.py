"""Narrow memory interface (ported from legacy memory_capture; logic unchanged).

The legacy module imports its sibling `common` by flat name, so we put the
vendored `_legacy/` dir on sys.path once, then re-export the public surface.
`memory_status` is the one legacy-CLI helper the memory flow couples to; it is
vendored as a minimal slice under `_legacy/e2e_dev_harness.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LEGACY = Path(__file__).resolve().parent / "_legacy"
if str(_LEGACY) not in sys.path:
    sys.path.insert(0, str(_LEGACY))

import memory_capture  # noqa: E402
import e2e_dev_harness as _legacy_cli  # noqa: E402

# Lifecycle / scan / validate verbs
init_memory = memory_capture.init_memory
scan_memory = memory_capture.scan_memory
validate_memory = memory_capture.validate_memory
select_memory = memory_capture.select_memory
append_memory = memory_capture.append_memory
promote_memory_updates = memory_capture.promote_memory_updates
validate_proposed_updates = memory_capture.validate_proposed_updates
index_memory = memory_capture.index_memory

# Parse / format / render helpers
parse_entries = memory_capture.parse_entries
render_entry = memory_capture.render_entry
parse_tags = memory_capture.parse_tags
parse_links = memory_capture.parse_links
format_tags = memory_capture.format_tags
format_links = memory_capture.format_links

# Narrow status verb (vendored slice of the legacy CLI)
memory_status = _legacy_cli.memory_status

__all__ = [
    "init_memory",
    "scan_memory",
    "validate_memory",
    "select_memory",
    "append_memory",
    "promote_memory_updates",
    "validate_proposed_updates",
    "index_memory",
    "parse_entries",
    "render_entry",
    "parse_tags",
    "parse_links",
    "format_tags",
    "format_links",
    "memory_status",
]
