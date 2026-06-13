"""dispatch: emit worker packets/descriptors for the current phase."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from e2e_harness.core import run_state, dispatch, multitrack
from e2e_harness import pipeline
from e2e_harness.adapters.agent_team.builtin import BuiltinAgentTeamProvider
from e2e_harness.adapters import runtime


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _default_profile(state: dict) -> str:
    # A built-in pipeline auto-pairs its `default-<name>` team profile so its
    # phase fan-out (e.g. critical's r1/r2/r3, adversarial's code/design/tests)
    # happens without an explicit --team-profile. `adversarial` is opt-in via
    # --pipeline (not a --tier choice), so it pairs by pipeline name only.
    pipeline_name = str(state.get("pipeline", "") or "")
    if pipeline_name in {"minimal", "standard", "critical", "audited", "adversarial"}:
        return f"default-{pipeline_name}"
    tier = str(state.get("tier", "") or "")
    if tier in {"minimal", "standard", "critical", "audited"}:
        return f"default-{tier}"
    return "default-standard"


def _phase_request(state: dict, phase, args, extra: list[str]) -> dict:
    runtime_name = getattr(args, "runtime", None) or "codex"
    profile = getattr(args, "team_profile", None) or _default_profile(state)
    max_workers = getattr(args, "max_workers", None)
    return {
        "schema": "e2e-dev-harness.agent-team-request.v1",
        "run_state_path": str(args.state),
        "repo_root": str(getattr(args, "repo", ".") or "."),
        "runtime": runtime_name,
        "pipeline": state.get("pipeline", "standard"),
        "phase": {
            "name": phase.name,
            "worker_role": phase.worker_role,
            "worker_skill": phase.worker_skill,
            "produces": list(phase.produces),
            "exit_gate": list(phase.exit_gate),
            "allows_code_write": phase.allows_code_write,
        },
        "context_paths": [str(args.state), *extra],
        "team_profile": profile,
        "constraints": {
            "max_workers": max_workers,
            "fresh_context": True,
            "allow_code_write": bool(phase.allows_code_write),
        },
    }


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    repo_root = Path(getattr(args, "repo", ".") or ".").resolve()
    spine = pipeline.spine_for_state(state, repo_root)
    name = state.get("current_phase")
    phase = next((p for p in spine if p.name == name), None)
    if phase is None or not phase.worker_skill:
        return 2, {"error": f"no dispatchable worker at phase {name}"}

    # P1: single default (codex), consistent with the seam/argparse default.
    runtime_name = getattr(args, "runtime", None) or "codex"
    adapter = runtime.get_adapter(runtime_name)
    caps = adapter.capabilities()

    # Surface the self-describing domain block (if any) to the worker. Backend
    # runs carry no domain block ⇒ extra=[] ⇒ packet is unchanged (parity).
    extra: list[str] = []
    dom = state.get("domain")
    if dom:
        extra = [f"domain:{dom['name']} test_runner:{dom['test_runner']} "
                 f"review_profile:{dom['review_profile']}"]
    # B3: at a module-scoped phase of a multi-module run, fan out one worker per
    # ready module (independent modules in parallel); depends_on keeps a gated
    # module out of the frontier so it stays single-worker until unblocked.
    provider = BuiltinAgentTeamProvider()
    request = _phase_request(state, phase, args, extra)
    frontier = []
    if multitrack.module_of(name) is not None:
        mplan = pipeline._module_plan_from_state(state, repo_root)
        if mplan is not None:
            frontier = multitrack.ready_frontier(spine, state, mplan)
    if len(frontier) >= 2:
        team_plan = provider.plan_module_fanout(request, frontier)
    else:
        team_plan = provider.plan_phase(request)
    descriptors = []
    for worker in team_plan["workers"]:
        descriptors.append({
            "worker_id": worker["id"],
            "runtime": caps.name,
            "descriptor": adapter.spawn(worker),
            "expected_outputs": list(worker.get("expected_outputs", []) or []),
        })
    run_dir = Path(args.state).resolve().parent
    plan_path = run_dir / "agent-team-plan.json"
    _write_json(plan_path, team_plan)
    invocation = {
        "schema": "e2e-dev-harness.dispatch-invocation.v1",
        "phase": phase.name,
        "runtime": caps.name,
        "team_plan_path": str(plan_path),
        "descriptors": descriptors,
        "blocked": [],
    }
    invocation_path = run_dir / "dispatch-invocations" / f"{phase.name}-{_now_stamp()}.json"
    _write_json(invocation_path, invocation)

    packet = dict(team_plan["workers"][0])
    packet["agent_team_plan"] = team_plan
    packet["agent_team_plan_path"] = str(plan_path)
    packet["dispatch_invocation_path"] = str(invocation_path)
    packet["worker_descriptors"] = descriptors
    packet["worker_descriptor"] = descriptors[0]["descriptor"] if descriptors else None

    # (c): a runtime that cannot auto-spawn must NOT be marked DISPATCHED — that
    # would let the coordinator self-deal. Surface an explicit block and leave
    # the phase in its implicit PENDING state (no WAITING_DISPATCH enum member;
    # that overlapping state was deliberately removed in the 2026-06-07 redesign).
    if not caps.can_auto_spawn:
        packet["dispatch_blocked"] = {
            "reason": "manual_runtime_requires_human_dispatch",
            "runtime": caps.name,
            "next_action": "human dispatches the worker, then `submit` its evidence",
        }
        invocation["blocked"].append(packet["dispatch_blocked"])
        _write_json(invocation_path, invocation)
        return 3, packet

    dispatched = dispatch.DispatchStatus.DISPATCHED.value
    frontier_phase_names = [w["id"] for w in team_plan["workers"]]

    def _mark_dispatched(s):
        tracks = s.get("tracks")
        if tracks and s.get("region") == "module_band":
            # Per-track bookkeeping: every frontier worker maps to one track via
            # its module-namespaced phase id. Mark each track AND its phase record.
            for phase_name in frontier_phase_names:
                mid = multitrack.module_of(phase_name)
                if mid in tracks:
                    tracks[mid]["dispatch"] = dispatched
                s.setdefault("phases", {}).setdefault(phase_name, {})["dispatch"] = dispatched
        else:
            rec = s.setdefault("phases", {}).setdefault(s.get("current_phase"), {})
            rec["dispatch"] = dispatched

    run_state.mutate(args.state, _mark_dispatched)
    return 0, packet
