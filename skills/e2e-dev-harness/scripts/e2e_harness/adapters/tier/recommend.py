"""Tier option and recommendation builder.

This module is intentionally pure: it consumes already-collected evidence and
does not invoke scanners, GitNexus, or subprocesses.
"""
from __future__ import annotations

from . import classify

ORDER = ["minimal", "standard", "critical", "audited"]

_COSTS = {
    "minimal": ["clarification", "red", "implementation", "verification"],
    "standard": ["planning", "single review", "verification"],
    "critical": ["planning", "R1/R2/R3 review fan-out", "verification"],
    "audited": ["planning", "R1/R2/R3 review fan-out", "audit replay"],
}


def _rank(tier: str) -> int:
    return ORDER.index(tier)


def _max_tier(*tiers: str) -> str:
    return max(tiers, key=_rank)


def _gitnexus_floor(scope: dict | None) -> tuple[str, list[str]]:
    if not scope:
        return "minimal", []
    gitnexus = scope.get("gitnexus") or {}
    summary = gitnexus.get("impact_summary") or {}
    risk = str(summary.get("risk") or "").upper()
    floor = "minimal"
    reasons: list[str] = []
    if risk in {"HIGH", "CRITICAL"}:
        floor = "critical"
        reasons.append(f"GitNexus impact risk: {risk}")
    elif risk == "MEDIUM":
        floor = "standard"
        reasons.append("GitNexus impact risk: MEDIUM")
    if (scope.get("dependencies") or []) and not gitnexus.get("verified", False):
        floor = _max_tier(floor, "critical")
        reasons.append(
            "cross-service dependencies found but GitNexus impact evidence is not verified"
        )
    return floor, reasons


def _option(tier: str, recommended: str, reasons: list[str]) -> dict:
    return {
        "tier": tier,
        "recommended": tier == recommended,
        "reasons": reasons if tier == recommended else [],
        "costs": list(_COSTS[tier]),
    }


def recommend_tier(request_text: str, scope: dict | None = None, selected_tier: str = "auto") -> dict:
    auto = selected_tier == "auto"
    classified_tier, classify_reasons = classify.classify_tier(
        request_text,
        scope,
        auto=auto,
    )
    gitnexus_tier, gitnexus_reasons = _gitnexus_floor(scope)
    recommended = _max_tier(classified_tier, gitnexus_tier)
    reasons = classify_reasons + gitnexus_reasons

    requested = recommended if auto else selected_tier
    requested_below = _rank(requested) < _rank(recommended)
    blocked = False
    selected = recommended if auto else requested

    return {
        "schema": "e2e-dev-harness.tier-recommendation.v1",
        "recommended_tier": recommended,
        "selected_tier": selected,
        "selection_source": "auto" if auto else "explicit",
        "reasons": reasons,
        "options": [_option(tier, recommended, reasons) for tier in ORDER],
        "downgrade": {
            "requested_below_recommended": requested_below,
            "requires_provenance": requested_below,
            "blocked": blocked,
        },
    }
