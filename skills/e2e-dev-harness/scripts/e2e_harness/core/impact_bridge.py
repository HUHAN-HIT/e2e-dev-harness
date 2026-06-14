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


def _seed_candidates(state: dict, repo_root) -> list[str]:
    p = _contract_path(state, repo_root)
    if not p:
        return []
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cands = obj.get("impact_seed_candidates")
    return [c for c in cands if isinstance(c, str)] if isinstance(cands, list) else []


def _write_artifact(state: dict, repo_root, artifact: dict) -> Path:
    run_dir = _run_dir(state, repo_root)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / _ARTIFACT_NAME
    path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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


def ensure_assessment_for_planning(state, repo_root, *, provider=None) -> dict | None:
    if _mode(state) == "off":
        return None

    contract_sha = _contract_sha(state, repo_root)
    existing = state.get("impact_assessment")
    if (existing and contract_sha is not None
            and existing.get("contract_sha256") == contract_sha):
        # idempotent: fresh binding for this contract -> reuse decision
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
    path = _write_artifact(state, repo_root, artifact)
    _bind(state, path=path, repo_root=repo_root, contract_sha=contract_sha,
          artifact=artifact, required=True)
    if artifact["status"] == "blocked":
        return {"status": "blocked"}
    return None
