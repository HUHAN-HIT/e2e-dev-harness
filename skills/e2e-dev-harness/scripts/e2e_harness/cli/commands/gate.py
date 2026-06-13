"""gate: run a phase's declarative exit_gate."""
from __future__ import annotations

from pathlib import Path

from e2e_harness.core import run_state, gates
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    spine = pipeline.spine_for_state(state, Path(args.repo).resolve())
    name = args.phase or state.get("current_phase")
    phase = next((p for p in spine if p.name == name), None)
    if phase is None:
        return 2, {"error": f"unknown phase {name}"}
    rec = state.get("phases", {}).get(name, {})
    # F-4: thread the trusted run-state so the scope_manifest validator grounds
    # phases/services at gate time here too — Hard Boundary #4 ("No ungrounded
    # COMPLETE") must hold on the operator `gate` verb, not just through `next`.
    ok, missing = gates.gate_passes(phase, rec, Path(args.repo).resolve(), state=state)
    return (0 if ok else 1), {"phase": name, "passed": ok, "missing_evidence": missing}
