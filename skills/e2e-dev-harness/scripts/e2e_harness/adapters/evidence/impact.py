"""Validate impact-assessment.json (design: GitNexus Impact Analysis).

Pure structural validator. Invoked IMPERATIVELY by impact_bridge and
impact_gate.planned_missing — deliberately NOT registered in
validate.STRUCTURED_KEYS, because impact_assessment is a run-level artifact, not a
phase exit_gate key (design F5). Degraded trust is split: `validate_impact_assessment`
checks structure only; `approval_matches` is the run-state cross-check.
"""
from __future__ import annotations

SCHEMA = "e2e-dev-harness.impact-assessment.v1"
VALID_STATUS = {"verified", "not_applicable", "blocked", "degraded"}
RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
_HIGH_RISKS = {"HIGH", "CRITICAL"}


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate_impact_assessment(obj) -> tuple[bool, str | None]:
    """(ok, reason); reason is a stable code naming the first defect."""
    if not isinstance(obj, dict):
        return False, "not-object"
    if obj.get("schema") != SCHEMA:
        return False, "bad-schema"
    status = obj.get("status")
    if status not in VALID_STATUS:
        return False, f"bad-status:{status!r}"

    seeds = obj.get("seeds", [])
    impact = obj.get("impact", [])
    if not isinstance(seeds, list) or not isinstance(impact, list):
        return False, "bad-shape"

    if status == "verified":
        if not impact:
            return False, "verified-without-impact"
        impacted: set[str] = set()
        for row in impact:
            if not isinstance(row, dict):
                return False, "bad-impact-row"
            seed = row.get("seed")
            if not _nonempty_str(seed):
                return False, "bad-impact-seed"
            impacted.add(seed)
            risk = str(row.get("risk") or "").upper()
            if risk not in RISK_ORDER:
                return False, f"bad-risk:{seed}:{risk}"
            if risk in _HIGH_RISKS and not row.get("affected_processes"):
                return False, f"high-risk-without-processes:{seed}"
        # every declared seed must have an impact result
        for s in seeds:
            name = s.get("name") if isinstance(s, dict) else None
            if _nonempty_str(name) and name not in impacted:
                return False, f"seed-without-impact:{name}"

    if status == "blocked":
        oqs = obj.get("open_questions")
        defect = _validate_open_questions(oqs)
        if defect is not None:
            return False, defect
        if not oqs:
            return False, "blocked-without-open-questions"

    if status == "degraded":
        approval = obj.get("approval")
        if not isinstance(approval, dict) or not _nonempty_str(approval.get("sha256")):
            return False, "degraded-without-approval"

    return True, None


def _validate_open_questions(items) -> str | None:
    if not isinstance(items, list):
        return "bad-open-questions"
    seen: set[str] = set()
    for q in items:
        if not isinstance(q, dict):
            return "bad-open-question"
        ident = q.get("id")
        if not _nonempty_str(ident) or not ident.startswith("IQ-"):
            return f"bad-iq-id:{ident!r}"
        if ident in seen:
            return f"duplicate-iq-id:{ident}"
        seen.add(ident)
        if not _nonempty_str(q.get("question")):
            return f"empty-iq-question:{ident}"
        if q.get("status") not in {"open", "resolved", "deferred"}:
            return f"bad-iq-status:{ident}"
    return None


def open_questions(obj) -> list[dict]:
    """[{id, question}] for still-open IQ-* questions (re-clarify merge helper)."""
    out: list[dict] = []
    for q in obj.get("open_questions", []) if isinstance(obj, dict) else []:
        if isinstance(q, dict) and q.get("status") == "open" and _nonempty_str(q.get("id")):
            out.append({"id": q["id"], "question": q.get("question", "")})
    return out


def max_seed_risk(obj) -> str | None:
    """Highest impact[].risk by RISK_ORDER, else None."""
    best = 0
    best_name = None
    for row in obj.get("impact", []) if isinstance(obj, dict) else []:
        risk = str(row.get("risk") or "").upper() if isinstance(row, dict) else ""
        if RISK_ORDER.get(risk, 0) > best:
            best = RISK_ORDER[risk]
            best_name = risk
    return best_name


def approval_matches(obj, state) -> bool:
    """Run-state cross-check: artifact.approval.sha256 == state approval sha256."""
    artifact_sha = ((obj.get("approval") or {}).get("sha256")
                    if isinstance(obj, dict) else None)
    state_sha = (((state or {}).get("approvals") or {})
                 .get("impact_degradation") or {}).get("sha256")
    return bool(artifact_sha) and artifact_sha == state_sha
