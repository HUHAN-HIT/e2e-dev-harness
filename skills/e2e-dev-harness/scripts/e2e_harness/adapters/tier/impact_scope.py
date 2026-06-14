"""Pure reduction from an impact-assessment artifact to the scope.gitnexus shape
recommend_tier consumes (design F6). The artifact is the source of truth; the
control plane derives scope.gitnexus from it instead of workers maintaining a
second value. recommend.py stays pure and unchanged.

    impact_summary.risk = max seed risk (unset when there are no seeds)
    verified            = (artifact status == "verified")
"""
from __future__ import annotations

from e2e_harness.adapters.evidence import impact as impact_ev


def scope_gitnexus_from_artifact(obj: dict) -> dict:
    """{"impact_summary": {...}, "verified": bool}."""
    summary: dict = {}
    risk = impact_ev.max_seed_risk(obj)
    if risk is not None:
        summary["risk"] = risk
    return {"impact_summary": summary,
            "verified": (obj.get("status") == "verified")}
