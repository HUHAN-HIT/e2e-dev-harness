"""gate: run a phase's declarative exit_gate."""
from __future__ import annotations

from pathlib import Path

from harness_v2.core import run_state, gates
from harness_v2 import pipeline


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    spine = pipeline.spine_for_state(state)
    name = args.phase or state.get("current_phase")
    phase = next((p for p in spine if p.name == name), None)
    if phase is None:
        return 2, {"error": f"unknown phase {name}"}
    rec = state.get("phases", {}).get(name, {})
    ok, missing = gates.gate_passes(phase, rec, Path(args.repo).resolve())
    return (0 if ok else 1), {"phase": name, "passed": ok, "missing_evidence": missing}
