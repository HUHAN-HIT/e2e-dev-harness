"""PLANNED supplemental impact gate (design: PLANNED Supplemental Gate).

Pure: reads the run-state binding and the submitted module_plan only — no
subprocess, no replay. Status ownership (design): `blocked` is owned by the
CLARIFIED edge and is NOT reported here; this gate owns `impact_refs`,
`impact_degradation_approval`, and the missing-binding backstop.
"""
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.adapters.evidence import hashing, impact as impact_ev


def planned_missing(state: dict, repo_root, phase_record: dict) -> list[str]:
    binding = state.get("impact_assessment")
    if not binding:
        # No binding => nothing for this gate to enforce. On the authoritative path the
        # engine bridge always writes the binding before the cursor clears the PLANNED
        # gate; the only way to arrive here binding-less is a custom spine WITHOUT
        # CLARIFIED, where the bridge never runs and impact cannot be assessed at all.
        # Demanding `impact_assessment` here would be unsatisfiable — no submit produces
        # it — and would wedge such a run forever. So this is a no-op, not a backstop.
        return []

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
        obj, integrity_ok = _load_artifact(binding, repo_root)
        if integrity_ok is False:
            return ["impact_assessment_integrity"]
        if obj is None or not impact_ev.approval_matches(obj, state):
            return ["impact_degradation_approval"]
        return []
    # verified: the module plan must reference every binding seed
    seeds = set(binding.get("seeds") or [])
    if not seeds:
        return ["impact_assessment_seeds_missing"]
    covered = _covered_seeds(phase_record, repo_root)
    return [] if seeds.issubset(covered) else ["impact_refs"]


def _load_artifact(binding: dict, repo_root):
    rel = binding.get("path")
    if not rel:
        return None, None
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel   # binding paths are repo-relative
    try:
        expected = binding.get("sha256")
        if expected and hashing.sha256_file(full) != expected:
            return None, False
        return json.loads(full.read_text(encoding="utf-8")), True
    except (OSError, ValueError):
        return None, None


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
