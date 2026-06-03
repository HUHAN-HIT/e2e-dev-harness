#!/usr/bin/env python3
"""Create and validate run-state checkpoints for resumed agent sessions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_state  # noqa: E402
import coordinator_summary  # noqa: E402
from common import atomic_write_json, now_iso  # noqa: E402

SCHEMA = "e2e-dev-harness.session-checkpoint.v1"
FILENAME = "session-checkpoint.json"
DEFAULT_MAX_EVIDENCE_BYTES = 240_000
DEFAULT_MAX_PHASE_EVENTS = 8
DEFAULT_MAX_TOOL_CALLS = 40
# Maximum dispatch waves a single coordinator session may run before it must
# checkpoint and resume. Unlike phase_events/tool_calls this ceiling is NOT
# scaled by expected_handoffs: it is a direct, per-session chat-context signal
# (each dispatched wave grows coordinator context), so it must stay a hard
# bound. The counter resets to zero whenever `next` writes a fresh checkpoint.
DEFAULT_MAX_DISPATCH_WAVES = 4
WAVE_FIELD = "dispatch_waves_since_checkpoint"


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def state_fingerprint(state: dict) -> str:
    payload = {
        "run_id": state.get("run_id", ""),
        "lifecycle": state.get("lifecycle", ""),
        "selected_mode": state.get("selected_mode", ""),
        "services": state.get("services", []),
        "gates": state.get("gates", {}),
        "owners": state.get("owners", {}),
        "updated_at": state.get("updated_at", ""),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def checkpoint_path(state_path: Path) -> Path:
    return state_path.parent / FILENAME


def file_count_and_bytes(root: Path) -> tuple[int, int]:
    if not root.exists():
        return 0, 0
    count = 0
    total = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        count += 1
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return count, total


def open_task_count(run_dir: Path) -> int:
    schedule = load_json(run_dir / "agent-schedule.json")
    tasks = schedule.get("tasks") if isinstance(schedule.get("tasks"), list) else []
    return sum(
        1
        for task in tasks
        if isinstance(task, dict)
        and str(task.get("status", "planned")).lower() not in {"completed", "cancelled"}
    )


def estimate_expected_handoffs(planned_tasks: int, max_tool_calls: int) -> int:
    # Each scheduled task costs the coordinator roughly three tool calls across
    # its dispatch lifecycle (beat -> ack -> complete). When the per-session
    # tool-call budget is bounded, a multi-service run is expected to span
    # several coordinator sessions; surfacing the estimate keeps checkpoint and
    # resume a planned cadence rather than a perceived failure.
    if planned_tasks <= 0 or max_tool_calls <= 0:
        return 0
    estimated_tool_calls = planned_tasks * 3
    return (estimated_tool_calls + max_tool_calls - 1) // max_tool_calls


def dispatch_waves_since_checkpoint(state: dict) -> int:
    try:
        return max(0, int(state.get(WAVE_FIELD, 0) or 0))
    except (TypeError, ValueError):
        return 0


def context_budget(
    state_path: Path,
    state: dict,
    max_evidence_bytes: int = DEFAULT_MAX_EVIDENCE_BYTES,
    max_phase_events: int = DEFAULT_MAX_PHASE_EVENTS,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    max_dispatch_waves: int = DEFAULT_MAX_DISPATCH_WAVES,
) -> dict:
    run_dir = state_path.parent
    evidence_count, evidence_bytes = file_count_and_bytes(run_dir / "evidence")
    cli_response_count, _cli_response_bytes = file_count_and_bytes(run_dir / "evidence" / "cli-responses")
    dispatch_event_count, _dispatch_event_bytes = file_count_and_bytes(run_dir / "dispatch-events")
    history = state.get("history") if isinstance(state.get("history"), list) else []
    phase_events = len(history) + dispatch_event_count
    waves_since_checkpoint = dispatch_waves_since_checkpoint(state)
    metrics = {
        "evidence_files": evidence_count,
        "evidence_bytes": evidence_bytes,
        "phase_events": phase_events,
        "tool_calls": cli_response_count,
        "dispatch_events": dispatch_event_count,
        WAVE_FIELD: waves_since_checkpoint,
    }
    planned_tasks = open_task_count(run_dir)
    expected_handoffs = estimate_expected_handoffs(planned_tasks, max_tool_calls)
    # The phase-event and tool-call metrics are cumulative across the whole run,
    # but a large multi-service run legitimately spans several coordinator
    # sessions (see expected_handoffs). With fixed base ceilings the budget flags
    # a handoff after the first few dispatch events and the coordinator perceives
    # the harness as failing and abandons it for manual coding. Scale these chatty
    # ceilings by the number of expected handoffs so the per-session signal stays
    # proportional to planned work. evidence_bytes is left unscaled because it
    # approximates real memory pressure rather than dispatch chatter.
    handoff_scale = max(1, expected_handoffs)
    effective_max_phase_events = max_phase_events * handoff_scale if max_phase_events >= 0 else max_phase_events
    effective_max_tool_calls = max_tool_calls * handoff_scale if max_tool_calls >= 0 else max_tool_calls
    limits = {
        "max_evidence_bytes": max_evidence_bytes,
        "max_phase_events": effective_max_phase_events,
        "max_tool_calls": effective_max_tool_calls,
        "max_dispatch_waves_since_checkpoint": max_dispatch_waves,
    }
    exceeded: list[str] = []
    if max_evidence_bytes >= 0 and evidence_bytes > max_evidence_bytes:
        exceeded.append("evidence_bytes")
    if effective_max_phase_events >= 0 and phase_events > effective_max_phase_events:
        exceeded.append("phase_events")
    if effective_max_tool_calls >= 0 and cli_response_count > effective_max_tool_calls:
        exceeded.append("tool_calls")
    # Unscaled: N dispatch waves in one session force a checkpoint+resume.
    if max_dispatch_waves >= 0 and waves_since_checkpoint >= max_dispatch_waves:
        exceeded.append(WAVE_FIELD)
    return {
        "schema": "e2e-dev-harness.coordinator-context-budget.v1",
        "metrics": metrics,
        "limits": limits,
        "planned_tasks": planned_tasks,
        "expected_handoffs": expected_handoffs,
        "exceeded_limits": exceeded,
        "handoff_recommended": bool(exceeded),
        "resume_instruction": (
            "Start a fresh coordinator session from run-state.json and session-checkpoint.json; keep only task ids, paths, worker handles, and evidence paths in chat."
            if exceeded
            else ""
        ),
    }


def budget_warnings(budget: dict) -> list[str]:
    if not budget.get("handoff_recommended"):
        return []
    exceeded = ", ".join(budget.get("exceeded_limits", []))
    return [f"Coordinator context budget exceeded ({exceeded}); checkpoint/resume is recommended before continuing the run."]


def create(
    repo: Path,
    state_path: Path,
    next_action: dict | None = None,
    agent: str = "",
    role: str = "",
    max_evidence_bytes: int = DEFAULT_MAX_EVIDENCE_BYTES,
    max_phase_events: int = DEFAULT_MAX_PHASE_EVENTS,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    max_dispatch_waves: int = DEFAULT_MAX_DISPATCH_WAVES,
) -> dict:
    repo = repo.resolve()
    resolved_state = resolve(repo, state_path)
    state = load_json(resolved_state)
    if not state:
        return {
            "ready": False,
            "blocked_reasons": [f"Run state not found or invalid: {resolved_state}"],
            "warnings": [],
            "checkpoint": str(checkpoint_path(resolved_state)),
        }
    # A fresh checkpoint is the resume boundary: clear the per-session
    # dispatch-wave counter so the next session starts the cadence over. Only
    # rewrite run-state when the counter is non-zero to avoid touching state on
    # the common path. updated_at is preserved so the checkpoint fingerprint
    # stays consistent with the run-state it was created from.
    if dispatch_waves_since_checkpoint(state) != 0:
        state[WAVE_FIELD] = 0
        run_state.write_state(repo, resolved_state, state)
    budget = context_budget(resolved_state, state, max_evidence_bytes, max_phase_events, max_tool_calls, max_dispatch_waves)
    data = {
        "schema": SCHEMA,
        "run_id": state.get("run_id", ""),
        "lifecycle": state.get("lifecycle", ""),
        "state_updated_at": state.get("updated_at", ""),
        "state_fingerprint": state_fingerprint(state),
        "next": next_action or {},
        "agent": agent,
        "role": role,
        "context_budget": budget,
        "created_at": now_iso(),
        "instruction": "Resume from this checkpoint and perform only the next phase allowed by run-state.",
    }
    target = checkpoint_path(resolved_state)
    atomic_write_json(target, data)
    return {
        "ready": True,
        "blocked_reasons": [],
        "warnings": budget_warnings(budget),
        "checkpoint": str(target),
        "lifecycle": data["lifecycle"],
        "next": data["next"],
        "context_budget": budget,
    }


def create_coordinator_summary(
    repo: Path,
    state_path: Path,
    result: dict,
    full_result_path: str = "",
) -> dict:
    repo = repo.resolve()
    resolved_state = resolve(repo, state_path)
    state = load_json(resolved_state)
    return coordinator_summary.write(repo, resolved_state, state, result, full_result_path)


def parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate(repo: Path, state_path: Path, max_age_minutes: int = 30) -> dict:
    repo = repo.resolve()
    resolved_state = resolve(repo, state_path)
    state = load_json(resolved_state)
    target = checkpoint_path(resolved_state)
    data = load_json(target)
    blocked: list[str] = []
    warnings: list[str] = []
    if not state:
        blocked.append(f"Run state not found or invalid: {resolved_state}")
    if not data:
        blocked.append(f"Session checkpoint missing or invalid: {target}")
    elif data.get("schema") != SCHEMA:
        blocked.append(f"Session checkpoint schema must be {SCHEMA}.")
    if state and data:
        if data.get("run_id") != state.get("run_id"):
            blocked.append("Session checkpoint run_id does not match run-state.")
        if data.get("lifecycle") != state.get("lifecycle"):
            blocked.append("Session checkpoint lifecycle is stale; run e2e_dev_harness.py next or resume.")
        if data.get("state_fingerprint") != state_fingerprint(state):
            blocked.append("Session checkpoint fingerprint is stale; run e2e_dev_harness.py next or resume.")
        created = parse_time(str(data.get("created_at", "")))
        if not created:
            blocked.append("Session checkpoint created_at is missing or invalid.")
        elif max_age_minutes > 0 and (now_dt() - created).total_seconds() > max_age_minutes * 60:
            blocked.append(
                f"Session checkpoint is older than {max_age_minutes} minutes; rerun e2e_dev_harness.py next or resume."
            )
        budget = data.get("context_budget") if isinstance(data.get("context_budget"), dict) else {}
        warnings.extend(budget_warnings(budget))
    else:
        budget = {}
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "run_state": str(resolved_state),
        "checkpoint": str(target),
        "context_budget": budget,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--agent", default="")
    parser.add_argument("--role", default="")
    parser.add_argument("--max-age-minutes", type=int, default=30)
    parser.add_argument("--max-evidence-bytes", type=int, default=DEFAULT_MAX_EVIDENCE_BYTES)
    parser.add_argument("--max-phase-events", type=int, default=DEFAULT_MAX_PHASE_EVENTS)
    parser.add_argument("--max-tool-calls", type=int, default=DEFAULT_MAX_TOOL_CALLS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = create(
        args.repo,
        args.state,
        agent=args.agent,
        role=args.role,
        max_evidence_bytes=args.max_evidence_bytes,
        max_phase_events=args.max_phase_events,
        max_tool_calls=args.max_tool_calls,
    ) if args.create else validate(
        args.repo,
        args.state,
        args.max_age_minutes,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Session checkpoint: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
