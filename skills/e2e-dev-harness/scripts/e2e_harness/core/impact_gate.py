"""PLANNED supplemental impact gate (design: PLANNED Supplemental Gate).

Pure: reads the run-state binding and the submitted module_plan only — no
subprocess, no replay. Status ownership (design): `blocked` is owned by the
CLARIFIED edge and is NOT reported here; this gate owns `impact_refs`,
`impact_degradation_approval`, and the missing-binding backstop.
"""
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.adapters.evidence import impact as impact_ev
from e2e_harness.core import impact_trigger


def planned_missing(state: dict, repo_root, phase_record: dict) -> list[str]:
    binding = state.get("impact_assessment")
    if not binding:
        # Backstop: a caller reached the gate without the engine's just-ran helper.
        # Only a defect if impact is active AND the pure trigger says it was required.
        if str((state.get("impact") or {}).get("mode") or "off") == "off":
            return []
        return ["impact_assessment"] if impact_trigger.required_reasons(state, repo_root) else []

    if not binding.get("required"):
        return []
    status = binding.get("status")
    if status is None:
        return ["impact_assessment"]
    if status == "blocked":
        return []   # owned by CLARIFIED edge; never double-reported
    if status == "not_applicable":
        return []
    if status == "degraded":
        obj = _load_artifact(binding, repo_root)
        if obj is None or not impact_ev.approval_matches(obj, state):
            return ["impact_degradation_approval"]
        return []
    # verified: the module plan must reference every binding seed
    seeds = set(binding.get("seeds") or [])
    if not seeds:
        return []
    covered = _covered_seeds(phase_record, repo_root)
    return [] if seeds.issubset(covered) else ["impact_refs"]


def _load_artifact(binding: dict, repo_root):
    rel = binding.get("path")
    if not rel:
        return None
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel   # binding paths are repo-relative
    try:
        return json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _covered_seeds(phase_record: dict, repo_root) -> set[str]:
    entry = (phase_record or {}).get("evidence", {}).get("module_plan")
    if not entry:
        return set()
    rel = entry["path"] if isinstance(entry, dict) else entry
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel
    try:
        obj = json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    covered: set[str] = set()
    for mod in obj.get("modules", []) if isinstance(obj, dict) else []:
        for ref in (mod.get("impact_refs") or []) if isinstance(mod, dict) else []:
            if isinstance(ref, dict) and isinstance(ref.get("seed"), str):
                covered.add(ref["seed"])
    return covered
