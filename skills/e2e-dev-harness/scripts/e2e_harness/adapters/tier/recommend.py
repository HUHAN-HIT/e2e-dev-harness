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


def _is_confirmed(confirmation: dict | None) -> bool:
    """A1/F2: the reason IS the audit anchor, so a confirmation token only counts when
    it carries a non-empty reason. Enforced here in the pure function — not just the CLI
    layer — so no future caller or verb can unblock a downgrade with a reasonless or
    empty token."""
    if not confirmation:
        return False
    reason = confirmation.get("reason")
    return isinstance(reason, str) and bool(reason.strip())


def _option(tier: str, recommended: str, reasons: list[str]) -> dict:
    return {
        "tier": tier,
        "recommended": tier == recommended,
        "reasons": reasons if tier == recommended else [],
        "costs": list(_COSTS[tier]),
    }


def recommend_tier(request_text: str, scope: dict | None = None, selected_tier: str = "auto",
                   *, confirmation: dict | None = None) -> dict:
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
    # A1: a tier below the recommendation is a downgrade that needs an explicit human
    # confirmation. `confirmed` is the single settled fact (carried by a confirmation
    # token whose non-empty reason is the audit anchor — validated by `_is_confirmed`,
    # not re-derived by the coordinator); `blocked` is the machine invariant `start`
    # enforces — no longer a constant. auto never downgrades (requested ==
    # recommended), so it never blocks.
    confirmed = requested_below and _is_confirmed(confirmation)
    blocked = requested_below and not confirmed
    selected = recommended if auto else requested

    # Slice 3: advisory only. Adversarial review is an opt-in *pipeline*, not a
    # tier, so it never changes selected_tier or the tier options — it surfaces a
    # user-confirmed `--pipeline adversarial` suggestion for high-risk requests.
    adversarial_reasons = classify.adversarial_triggers(request_text, scope)

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
            "confirmed": confirmed,
            "blocked": blocked,
        },
        "adversarial_review": {
            "suggested": bool(adversarial_reasons),
            "pipeline": "adversarial",
            "select_with": "start --pipeline adversarial",
            "reasons": adversarial_reasons,
        },
    }
