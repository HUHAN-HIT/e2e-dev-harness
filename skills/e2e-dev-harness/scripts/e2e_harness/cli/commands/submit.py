"""submit: record worker evidence (or mark failed) and update dispatch."""
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.core import run_state, engine, multitrack
from e2e_harness import pipeline


def _dispatched_producers_for_base(run_dir: Path, base: str) -> list[str]:
    """Worker ids the HARNESS dispatched for the band whose base phase is `base`,
    read from the trusted dispatch artifacts (`agent-team-plan.json` workers /
    producer_ids and `dispatch-invocations/*.json` descriptors). This is the
    harness-written binding F-5 cross-checks against — unlike the self-supplied
    `--worker-id`. Empty when the band was never dispatched (manual / identity-less
    runtime), in which case submit degrades to the OWN1 self-check only."""
    ids: set[str] = set()
    plan = run_dir / "agent-team-plan.json"
    if plan.exists():
        try:
            obj = json.loads(plan.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            obj = None
        if isinstance(obj, dict) and multitrack.base_phase_name(str(obj.get("phase") or "")) == base:
            for w in obj.get("workers") or []:
                if isinstance(w, dict) and isinstance(w.get("id"), str):
                    ids.add(w["id"])
            contract = obj.get("evidence_contract")
            if isinstance(contract, dict):
                for pid in contract.get("producer_ids") or []:
                    if isinstance(pid, str):
                        ids.add(pid)
    inv_dir = run_dir / "dispatch-invocations"
    if inv_dir.is_dir():
        for f in inv_dir.glob("*.json"):
            try:
                inv = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(inv, dict) or multitrack.base_phase_name(str(inv.get("phase") or "")) != base:
                continue
            for d in inv.get("descriptors") or []:
                if isinstance(d, dict) and isinstance(d.get("worker_id"), str):
                    ids.add(d["worker_id"])
    return sorted(ids)


def run(args) -> tuple[int, dict]:
    repo_root = Path(args.repo).resolve()
    # F2 (Hybrid): resolve the phase's live exit_gate so a gate-completing submit
    # stamps the contract-in-force at pass time. An unknown phase yields no gate ->
    # no stamp (safe; legacy behavior).
    spine = pipeline.spine_for_state(run_state.load(args.state), repo_root)
    phase = next((p for p in spine if p.name == args.phase), None)
    exit_gate = phase.exit_gate if phase is not None else None
    # F-5: resolve the trusted, harness-dispatched producer set for this phase's
    # band and pass it so submit_evidence can reject a never-dispatched module
    # namespace (empty -> degrade to OWN1 only).
    producers = _dispatched_producers_for_base(
        Path(args.state).resolve().parent, multitrack.base_phase_name(args.phase or ""))
    run_state.mutate(
        args.state,
        lambda state: engine.submit_evidence(
            state, args.phase, args.key, args.path,
            repo_root=repo_root,
            status=getattr(args, "status", "done"),
            reason=getattr(args, "reason", None),
            exit_gate=exit_gate,
            worker_id=getattr(args, "worker_id", None),
            authorized_producers=producers or None,
        ),
        # Slice 1: extend the chain iff this run has one (started with emission on).
        events_path=run_state.events_path_if_active(args.state),
    )
    return 0, {"schema": "e2e-dev-harness.submit.v1", "phase": args.phase,
               "key": args.key, "recorded": args.path,
               "status": getattr(args, "status", "done")}
