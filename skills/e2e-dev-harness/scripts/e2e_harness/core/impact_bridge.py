"""Impact assessment bridge (design: Trigger Policy, Evaluation Point).

The single source of truth for "is impact required and satisfied". Called by
engine._evaluate_singleton as the cursor reaches PLANNED. Idempotent on the
acceptance-contract hash: a binding whose contract_sha256 still matches is reused
without touching GitNexus; an amended contract invalidates a stale assessment.

Returns None when the engine may proceed (not_applicable / verified / approved
degraded, or impact.mode == off). Returns {"status": "blocked", ...} when the run
must go back to CLARIFIED (the CLARIFIED edge owns `blocked`, design Status
Ownership).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from e2e_harness.adapters.evidence import hashing, impact as impact_ev
from e2e_harness.core import impact_trigger

BINDING_SCHEMA = "e2e-dev-harness.impact-binding.v1"
_ARTIFACT_NAME = "impact-assessment.json"


def _mode(state: dict) -> str:
    return str((state.get("impact") or {}).get("mode") or "off")


def _contract_entry(state: dict):
    return (state.get("phases", {}).get("CLARIFIED", {})
            .get("evidence", {}).get("acceptance_contract"))


def _contract_path(state: dict, repo_root) -> Path | None:
    entry = _contract_entry(state)
    if not entry:
        return None
    rel = entry["path"] if isinstance(entry, dict) else entry
    full = Path(rel)
    if not full.is_absolute() and repo_root is not None:
        full = Path(repo_root) / rel
    return full if full.is_file() else None


def _contract_sha(state: dict, repo_root) -> str | None:
    p = _contract_path(state, repo_root)
    return hashing.sha256_file(p) if p else None


def _run_dir(state: dict, repo_root) -> Path:
    rsp = state.get("_run_state_path")
    if rsp:
        return Path(rsp).resolve().parent
    return Path(repo_root) / "docs" / "agent-runs" / str(state.get("run_id") or "run")


def _seed_candidates(state: dict, repo_root) -> list:
    p = _contract_path(state, repo_root)
    if not p:
        return []
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cands = obj.get("impact_seed_candidates")
    return [c for c in cands if isinstance(c, (str, dict))] if isinstance(cands, list) else []


def _write_artifact(state: dict, repo_root, artifact: dict) -> Path:
    run_dir = _run_dir(state, repo_root)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / _ARTIFACT_NAME
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _bind(state: dict, *, path: Path, repo_root, contract_sha: str | None,
          artifact: dict, required: bool) -> dict:
    # Store the artifact path REPO-relative (design binding example) so every reader —
    # the gate, dispatch, and the re-clarify merge — resolves it against repo_root,
    # independent of whether _run_state_path is in scope at read time.
    rel = str(path)
    if repo_root is not None:
        try:
            rel = str(path.relative_to(Path(repo_root).resolve()))
        except ValueError:
            rel = str(path)
    binding = {
        "schema": BINDING_SCHEMA,
        "path": rel,
        "sha256": hashing.sha256_file(path),
        "contract_sha256": contract_sha,
        "status": artifact["status"],
        "required": required,
        "risk": impact_ev.max_seed_risk(artifact),
        "seeds": [s["name"] for s in artifact.get("seeds", [])
                  if isinstance(s, dict) and s.get("name")]
        if artifact["status"] == "verified" else [],
    }
    state["impact_assessment"] = binding
    return binding


def _not_applicable_artifact() -> dict:
    return {"schema": impact_ev.SCHEMA, "status": "not_applicable", "tool": "gitnexus",
            "seeds": [], "impact": [], "planning_constraints": [], "open_questions": [],
            "degradation": None, "approval": None}


def _approval(state: dict) -> dict | None:
    appr = ((state.get("approvals") or {}).get("impact_degradation") or {})
    return appr if appr.get("sha256") else None


def _degrade(artifact: dict, approval: dict) -> dict:
    """Convert a blocked assessment into an auditable `degraded` one. The user has
    explicitly approved proceeding without verified impact; the approval hash is the
    trust anchor the gate validator cross-checks (design: Degraded Approval)."""
    art = dict(artifact)
    art["status"] = "degraded"
    art["degradation"] = {"from_status": "blocked",
                          "reason": approval.get("reason", ""),
                          "unverified_questions": artifact.get("open_questions", [])}
    art["approval"] = {"sha256": approval["sha256"],
                       "source": approval.get("source", "user-approved"),
                       "approval_path": approval.get("approval_path")}
    return art


def _approval_matches_binding(approval: dict | None, existing: dict) -> bool:
    return bool(approval and approval.get("sha256") == existing.get("approval_sha256"))


def ensure_assessment_for_planning(state, repo_root, *, provider=None) -> dict | None:
    mode = _mode(state)
    if mode == "off":
        return None

    contract_sha = _contract_sha(state, repo_root)
    existing = state.get("impact_assessment")
    approval = _approval(state)
    if (existing and contract_sha is not None
            and existing.get("contract_sha256") == contract_sha):
        # Idempotent reuse, with two trust-anchor exceptions:
        # - blocked + approval in auto mode must re-run to emit a degraded artifact;
        # - degraded bindings are reusable only while the same approval remains valid.
        if existing.get("status") == "blocked" and approval:
            if mode == "strict":
                return {"status": "blocked", "strict_mode_no_degrade": True}
        elif existing.get("status") == "degraded" and not _approval_matches_binding(approval, existing):
            pass
        else:
            return {"status": "blocked"} if existing.get("status") == "blocked" else None

    reasons = impact_trigger.required_reasons(state, repo_root)
    if not reasons:
        artifact = _not_applicable_artifact()
        path = _write_artifact(state, repo_root, artifact)
        _bind(state, path=path, repo_root=repo_root, contract_sha=contract_sha,
              artifact=artifact, required=False)
        return None

    if provider is None:
        from e2e_harness.adapters.impact.gitnexus import GitNexusImpactProvider
        provider = GitNexusImpactProvider()

    artifact = provider.assess(Path(repo_root) if repo_root else Path("."),
                               {"seed_candidates": _seed_candidates(state, repo_root),
                                "request": state.get("request", ""), "reasons": reasons})
    artifact.setdefault("trigger", {"required": True, "reason_codes": reasons,
                                    "evaluated_at_phase": "CLARIFIED"})
    # Degradation override: a recorded approval lets a blocked assessment proceed as
    # an auditable `degraded` one instead of pinning the run at CLARIFIED forever.
    strict_mode_no_degrade = False
    if artifact["status"] == "blocked" and approval:
        if mode == "strict":
            strict_mode_no_degrade = True
        else:
            artifact = _degrade(artifact, approval)
    path = _write_artifact(state, repo_root, artifact)
    _bind(state, path=path, repo_root=repo_root, contract_sha=contract_sha,
          artifact=artifact, required=True)
    if artifact["status"] == "blocked":
        # Single source of truth for "can a recorded approval degrade this?": the
        # binding self-describes it so `next` reads the policy instead of re-deriving
        # mode (the drift that let strict runs advertise a no-op approval).
        state["impact_assessment"]["degradation_available"] = (mode != "strict")
    if artifact["status"] == "degraded" and approval:
        state["impact_assessment"]["approval_sha256"] = approval["sha256"]
    if strict_mode_no_degrade:
        return {"status": "blocked", "strict_mode_no_degrade": True}
    if artifact["status"] == "blocked":
        return {"status": "blocked"}
    return None
