"""Pipeline config: tier -> (active phases + per-phase gate overrides)."""
from __future__ import annotations

from harness_v2.core import lifecycle

_FULL = ("CREATED", "CLARIFIED", "PLANNED", "RED", "IMPLEMENTED", "REVIEWED", "VERIFIED")
_REVIEW_FANOUT = ("r1_review", "r2_review", "r3_review")

# Each pipeline: ordered phase names + overrides applied when building the spine.
PIPELINES: dict[str, dict] = {
    "minimal": {
        "phases": ("CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"),
        "overrides": {},
    },
    "standard": {
        "phases": _FULL,
        "overrides": {},
    },
    "critical": {
        "phases": _FULL,
        "overrides": {
            "REVIEWED": {"produces": _REVIEW_FANOUT, "exit_gate": _REVIEW_FANOUT},
        },
    },
    "audited": {
        "phases": _FULL,
        "overrides": {
            "REVIEWED": {"produces": _REVIEW_FANOUT, "exit_gate": _REVIEW_FANOUT},
            "VERIFIED": {"produces": ("verification", "audit_replay"),
                          "exit_gate": ("verification", "audit_replay")},
        },
    },
}


def active_phase_names(pipeline: str) -> list[str]:
    if pipeline not in PIPELINES:
        raise KeyError(f"unknown pipeline: {pipeline}")
    return list(PIPELINES[pipeline]["phases"])


def build_spine(pipeline: str) -> list[lifecycle.Phase]:
    if pipeline not in PIPELINES:
        raise KeyError(f"unknown pipeline: {pipeline}")
    cfg = PIPELINES[pipeline]
    return lifecycle.build_spine(list(cfg["phases"]), cfg.get("overrides"))
