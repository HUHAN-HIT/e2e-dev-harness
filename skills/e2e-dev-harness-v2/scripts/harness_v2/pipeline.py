"""Pipeline config: tier -> active phase names (M1 built-in minimal)."""
from __future__ import annotations

_PIPELINES: dict[str, tuple[str, ...]] = {
    "minimal": ("CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"),
}


def active_phase_names(pipeline: str) -> list[str]:
    if pipeline not in _PIPELINES:
        raise KeyError(f"unknown pipeline: {pipeline}")
    return list(_PIPELINES[pipeline])
