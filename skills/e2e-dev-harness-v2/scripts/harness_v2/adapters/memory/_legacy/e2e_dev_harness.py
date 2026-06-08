"""Minimal vendored slice of the legacy CLI for the memory leaf (U1).

`test_memory_capture.py` couples to exactly one legacy-CLI helper —
`e2e_dev_harness.memory_status` — so only that function is vendored here
(design §5/§15: no legacy edits, keep the ported test verbatim). The body is a
byte-for-byte copy of `e2e_dev_harness.memory_status` from the legacy CLI; the
full CLI remains M5-owned and is intentionally not vendored.
"""
from __future__ import annotations

from pathlib import Path

import memory_capture


def memory_status(repo: Path, mode: str) -> dict:
    if mode == "off":
        return {"mode": mode, "enabled": False, "blocked": False, "message": "Memory adapter disabled by policy."}
    if mode == "strict":
        result = memory_capture.validate_memory(repo)
        result.update({
            "mode": mode,
            "enabled": True,
            "blocked": not result["ready"],
        })
        return result
    result = memory_capture.scan_memory(repo)
    result.update({
        "mode": mode,
        "enabled": True,
        "blocked": False,
    })
    return result
