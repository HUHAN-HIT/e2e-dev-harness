#!/usr/bin/env python3
"""Portable L0 serial isolated dispatch for scheduled harness agents."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import agent_scheduler  # noqa: E402
import context_pack  # noqa: E402
import reviewer_gate  # noqa: E402
import run_state  # noqa: E402
from common import configure_utf8_stdio, posix  # noqa: E402


CLAUDE_CAPABILITIES = {
    "runtime": "claude-code",
    "supports_subagent": True,
    "supports_task_hook": True,
    "supports_isolated_review": True,
    "supports_blocking_stop": True,
    "dispatch_mode": "native-subagent",
    "spawn_tool": "Task",
    "spawn_requires_tool_call": True,
    "spawn_acknowledgement": "phase_guard_task_hook_or_dispatch_ack",
}

CODEX_CAPABILITIES = {
    "runtime": "codex",
    "supports_subagent": True,
    "supports_task_hook": False,
    "supports_isolated_review": True,
    "supports_blocking_stop": False,
    "dispatch_mode": "codex-multi-agent-v1",
    "spawn_tool": "multi_agent_v1.spawn_agent",
    "spawn_requires_tool_call": True,
}

MANUAL_CAPABILITIES = {
    "runtime": "manual",
    "supports_subagent": False,
    "supports_task_hook": False,
    "supports_isolated_review": False,
    "supports_blocking_stop": False,
    "dispatch_mode": "manual-dispatch",
}


def normalize_runtime(runtime: str | None) -> str:
    text = (runtime or "claude-code").strip().lower().replace("_", "-")
    aliases = {
        "claude": "claude-code",
        "claude-code": "claude-code",
        "manual": "manual",
        "codex": "codex",
        "codex-app": "codex",
        "gemini": "gemini",
        "opencode": "opencode",
    }
    return aliases.get(text, text)


def runtime_capabilities(runtime: str | None = "claude-code") -> dict:
    normalized = normalize_runtime(runtime)
    if normalized == "claude-code":
        return dict(CLAUDE_CAPABILITIES)
    if normalized == "codex":
        return dict(CODEX_CAPABILITIES)
    if normalized == "manual":
        return dict(MANUAL_CAPABILITIES)
    data = dict(MANUAL_CAPABILITIES)
    data["runtime"] = normalized
    return data


def resolve(repo: Path, path: Path | str | None) -> Path | None:
    if not path:
        return None
    value = path if isinstance(path, Path) else Path(str(path))
    return value if value.is_absolute() else repo / value


def read_json(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(tmp_name).unlink(missing_ok=True)
        raise


def rel(repo: Path, path: Path) -> str:
    try:
        return posix(path.resolve().relative_to(repo.resolve()))
    except (OSError, ValueError):
        return posix(str(path))


def load_state(repo: Path, state_path: Path | None) -> tuple[Path | None, dict]:
    path = resolve(repo, state_path)
    return path, read_json(path)


def update_dispatch_state(
    repo: Path,
    state_path: Path | None,
    dispatch: dict,
    lifecycle: str | None = None,
) -> dict:
    path, state = load_state(repo, state_path)
    if not path or not state:
        return {"ready": True, "blocked_reasons": [], "warnings": ["No run-state supplied; dispatch state not recorded."]}
    if lifecycle:
        state["lifecycle"] = lifecycle
    state["dispatch"] = dispatch
    state["updated_at"] = run_state.now_iso()
    run_state.write_state(repo, path, state)
    return {"ready": True, "blocked_reasons": [], "warnings": [], "run_state": str(path)}


def task_done(task: dict) -> bool:
    return str(task.get("status", "planned")).lower() == "completed"


def next_open_task(schedule: dict) -> dict | None:
    for task in schedule.get("tasks", []) or []:
        if isinstance(task, dict) and not task_done(task):
            return task
    return None


def task_ready_blockers(repo: Path, schedule: dict, task: dict, agent: str) -> list[str]:
    blocked: list[str] = []
    blocked.extend(agent_scheduler.role_conflict_blockers(schedule, task, agent))
    blocked.extend(agent_scheduler.role_template_blockers(repo, schedule, task))
    deps_ready, missing_deps = agent_scheduler.phases_completed(
        schedule,
        [str(phase) for phase in task.get("depends_on_phases", []) or []],
    )
    if not deps_ready:
        blocked.append("Dependency phases are incomplete: " + ", ".join(missing_deps))
    blocked.extend(agent_scheduler.task_input_handoff_blockers(repo, task))
    status = str(task.get("status", "planned")).lower()
    owner = str(task.get("owner", "")).strip()
    if owner and owner != agent and status in agent_scheduler.CLAIMED_STATUSES and not agent_scheduler.is_stale(task):
        blocked.append(f"Task has an active claim by {owner}.")
    return blocked


def next_ready_task(repo: Path, schedule: dict) -> tuple[dict | None, list[dict]]:
    skipped: list[dict] = []
    for task in schedule.get("tasks", []) or []:
        if not isinstance(task, dict) or task_done(task):
            continue
        agent = str(task.get("agent", "")) or "agent"
        blockers = task_ready_blockers(repo, schedule, task, agent)
        if not blockers:
            return task, skipped
        skipped.append(
            {
                "task_id": task.get("id", ""),
                "agent": task.get("agent", ""),
                "phase": task.get("phase", ""),
                "blocked_reasons": blockers,
            }
        )
    return None, skipped


def invocation_dir_for_task(run_dir: Path, task: dict) -> Path:
    phase = str(task.get("phase", "")).lower()
    if phase in {"r1-review", "r2-review", "r3-review"} or "review" in phase:
        return run_dir / "review-invocations"
    return run_dir / "dispatch-invocations"


def declared_reviewer_invocation(repo: Path, task: dict) -> Path | None:
    review_request = first_matching(task.get("inputs", []), "/review-requests/")
    if not review_request:
        return None
    request_path = resolve(repo, review_request)
    if not request_path or not request_path.exists():
        return None
    fields = reviewer_gate.parse_item(request_path)
    invocation = str(fields.get("reviewer_invocation", "")).strip()
    if not invocation:
        return None
    invocation_path = resolve(repo, invocation)
    if not invocation_path:
        return None
    try:
        invocation_path.resolve().relative_to(repo.resolve())
    except ValueError:
        return None
    return invocation_path


def write_invocation(
    repo: Path,
    run_dir: Path,
    task: dict,
    runtime: str,
    context_pack_path: Path,
    coordinator_agent: str,
    developer_session: str,
) -> Path:
    task_id = str(task.get("id", "task"))
    worker_agent = str(task.get("agent") or f"agent-{task_id}")
    path = declared_reviewer_invocation(repo, task) or invocation_dir_for_task(run_dir, task) / f"{task_id}-{worker_agent}.json"
    data = {
        "runtime": runtime,
        "invocation_type": "subagent",
        "developer_agent": coordinator_agent,
        "reviewer_agent": worker_agent if "review" in str(task.get("phase", "")).lower() else "",
        "worker_agent": worker_agent,
        "developer_session": developer_session,
        "reviewer_session": f"{worker_agent}-session",
        "worker_session": f"{worker_agent}-session",
        "context_pack": rel(repo, context_pack_path),
        "task_id": task_id,
        "schedule": rel(repo, run_dir / "agent-schedule.json"),
        "review_request": first_matching(task.get("inputs", []), "/review-requests/"),
        "output": first_matching(task.get("outputs", []), "/reviews/"),
        "allowed_inputs": task.get("inputs", []),
        "allowed_outputs": task.get("outputs", []),
        "fork_context": False,
        "context_policy": "request-only; no-inherited developer chat context",
        "status": "dispatched",
    }
    atomic_write_json(path, data)
    return path


def first_matching(values: list | None, needle: str) -> str:
    for value in values or []:
        text = str(value).replace("\\", "/")
        if needle in text:
            return text
    return ""


def task_prompt(task: dict, pack: dict, invocation_path: Path, repo: Path) -> str:
    task_id = str(task.get("id", ""))
    agent = str(task.get("agent", ""))
    lines = [
        "Task prompt: e2e-dev-harness isolated worker task",
        "Coordinator must not execute this task in the current context; send this prompt to a fresh isolated worker.",
        "",
        f"Task ID: {task_id}",
        f"Agent: {agent}",
        f"Phase: {task.get('phase', '')}",
        f"Service: {task.get('service', '')}",
        f"Invocation: {rel(repo, invocation_path)}",
        f"Context Pack: {pack.get('context_pack_path', pack.get('path', ''))}",
        "",
        "Rules:",
        "- Use only the context pack and allowed inputs below.",
        "- Use only the allowed inputs from the context pack.",
        "- Do not inherit or rely on coordinator chat context.",
        "- Write only scheduled outputs.",
        "- Return the evidence paths that should be passed to dispatch-complete.",
        "- Do not perform R1/R2/R3 self-review from the same developer session.",
        "",
        "Allowed inputs:",
    ]
    lines.extend(f"- {item}" for item in pack.get("allowed_inputs", []) or [])
    lines.append("")
    lines.append("Required outputs:")
    lines.extend(f"- {item}" for item in pack.get("allowed_outputs", []) or [])
    return "\n".join(lines)


def worker_agent_type(task: dict) -> str:
    return "worker"


def spawn_request_for_runtime(
    capabilities: dict,
    task: dict,
    prompt: str,
    schedule_path: Path,
    state_path: Path | None,
    repo: Path,
) -> dict | None:
    task_id = str(task.get("id", ""))
    agent = str(task.get("agent", "")) or "agent"
    evidence_args = " ".join(f"--evidence {item}" for item in task.get("outputs", []) or ["<evidence-path>"])
    state_arg = f" --state {rel(repo, resolve(repo, state_path) or state_path)}" if state_path else ""
    completion_command = (
        "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-complete . "
        f"--schedule {rel(repo, resolve(repo, schedule_path) or schedule_path)}"
        f"{state_arg} --task-id {task_id} --agent {agent} {evidence_args}"
    )
    ack_command = (
        "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-ack ."
        f"{state_arg} --task-id {task_id} --agent {agent}"
        " --worker-handle <runtime-worker-id> --worker-session <runtime-worker-session>"
    )
    if capabilities.get("spawn_tool") == "Task":
        return {
            "schema": "e2e-dev-harness.runtime-spawn-request.v1",
            "runtime": capabilities.get("runtime", ""),
            "tool": "Task",
            "arguments": {
                "description": f"{task_id} {agent}",
                "prompt": prompt,
                "subagent_type": "general-purpose",
            },
            "task_id": task_id,
            "agent": agent,
            "ack_command": ack_command,
            "completion_command": completion_command,
            "context_policy": "fresh Claude Code Task only; no inherited coordinator chat beyond this prompt and context pack.",
        }
    if capabilities.get("spawn_tool") != "multi_agent_v1.spawn_agent":
        return None
    return {
        "schema": "e2e-dev-harness.runtime-spawn-request.v1",
        "runtime": capabilities.get("runtime", ""),
        "tool": "multi_agent_v1.spawn_agent",
        "arguments": {
            "agent_type": worker_agent_type(task),
            "fork_context": False,
            "message": prompt,
        },
        "task_id": task_id,
        "agent": agent,
        "ack_command": ack_command,
        "completion_command": completion_command,
        "context_policy": "fresh worker only; fork_context=false; use context pack instead of coordinator chat.",
    }


def sync_invocation_for_ack(repo: Path, dispatch: dict, worker_handle: str, worker_session: str) -> None:
    invocation_path = resolve(repo, dispatch.get("invocation_path", ""))
    if not invocation_path or not invocation_path.exists():
        return
    data = read_json(invocation_path)
    if not data:
        return
    session = worker_session.strip() or worker_handle.strip()
    data["worker_handle"] = worker_handle.strip()
    data["worker_session"] = session
    if str(data.get("reviewer_agent", "")).strip():
        data["reviewer_session"] = session
    data["status"] = "running"
    data["spawn_acknowledged_at"] = run_state.now_iso()
    atomic_write_json(invocation_path, data)


def mark_invocation_completed(repo: Path, dispatch: dict, evidence: list[str] | None) -> None:
    invocation_path = resolve(repo, dispatch.get("invocation_path", ""))
    if not invocation_path or not invocation_path.exists():
        return
    data = read_json(invocation_path)
    if not data:
        return
    data["status"] = "completed"
    data["completed_at"] = run_state.now_iso()
    if evidence:
        data["evidence"] = evidence
        if not str(data.get("output", "")).strip():
            data["output"] = evidence[0]
    atomic_write_json(invocation_path, data)


def dispatch_completion_blockers(repo: Path, state_path: Path | None, task_id: str, agent: str) -> tuple[list[str], dict]:
    _state_path, state = load_state(repo, state_path)
    dispatch = state.get("dispatch") if isinstance(state.get("dispatch"), dict) else {}
    if not dispatch or str(dispatch.get("current_task_id", "")).strip() != task_id:
        return [], dispatch
    blocked: list[str] = []
    if str(dispatch.get("current_agent", "")).strip() != agent:
        blocked.append(f"Dispatch agent mismatch: expected {dispatch.get('current_agent', '')}, got {agent}.")
    status = str(dispatch.get("status", "")).strip()
    if status in {"awaiting_runtime_spawn", "waiting_dispatch", "worker_dispatched", "dispatched"}:
        blocked.append(
            "Dispatched task has not been confirmed by a fresh worker; call the runtime spawn tool and let the Task hook confirm, "
            "or run dispatch-ack with the worker handle before dispatch-complete."
        )
    elif status != "worker_running":
        blocked.append(f"Dispatch status must be worker_running before dispatch-complete; got {status or '<missing>'}.")
    elif not (
        str(dispatch.get("worker_handle", "")).strip()
        or str(dispatch.get("spawn_confirmed_by", "")).strip()
        or str(dispatch.get("spawn_acknowledged_at", "")).strip()
    ):
        blocked.append("Dispatch has no worker confirmation proof; record dispatch-ack or runtime hook confirmation before dispatch-complete.")
    return blocked, dispatch


def waiting_dispatch_result(
    repo: Path,
    schedule_path: Path,
    state_path: Path | None,
    task: dict | None,
    capabilities: dict,
) -> dict:
    task = task or {}
    run_dir = (resolve(repo, state_path).parent if state_path else resolve(repo, schedule_path).parent)  # type: ignore[union-attr]
    _state_path, state = load_state(repo, state_path)
    dispatch = {
        "status": "waiting_dispatch",
        "runtime": capabilities["runtime"],
        "previous_lifecycle": str(state.get("lifecycle", "")),
        "current_task_id": task.get("id", ""),
        "current_agent": task.get("agent", ""),
        "invocation_path": "",
        "context_pack": "",
    }
    state_update = update_dispatch_state(repo, state_path, dispatch, lifecycle="WAITING_DISPATCH")
    packet = {
        "task_id": task.get("id", ""),
        "agent": task.get("agent", ""),
        "schedule": rel(repo, resolve(repo, schedule_path) or schedule_path),
        "run_dir": rel(repo, run_dir) if run_dir else "",
        "reason": "Runtime cannot spawn an independent subagent/session; use a fresh manual reviewer/worker session.",
    }
    return {
        "ready": False,
        "blocked_reasons": [packet["reason"]],
        "warnings": state_update.get("warnings", []),
        "capabilities": capabilities,
        "requires_fresh_worker": True,
        "coordinator_action": "pause_for_manual_worker",
        "worker_context_policy": "Use a fresh manual worker session with only the context pack and allowed inputs; do not continue in coordinator context.",
        "dispatch": dispatch,
        "manual_dispatch_packet": packet,
        "run_state_update": state_update,
    }


def dispatch_next(
    repo: Path,
    schedule_path: Path,
    state_path: Path | None,
    runtime: str = "claude-code",
    coordinator_agent: str = "coordinator-agent",
    developer_session: str = "coordinator-session",
    max_files: int = 12,
    max_chars: int = 120_000,
) -> dict:
    repo = repo.resolve()
    schedule_file = resolve(repo, schedule_path)
    schedule = read_json(schedule_file)
    if not schedule:
        return {"ready": False, "blocked_reasons": [f"Agent schedule not found or unreadable: {schedule_file}"], "warnings": []}
    task, skipped = next_ready_task(repo, schedule)
    if not task:
        open_task = next_open_task(schedule)
        if open_task:
            return {
                "ready": False,
                "blocked_reasons": ["No scheduled task is ready to dispatch."],
                "warnings": [],
                "skipped_tasks": skipped,
            }
        return {"ready": True, "blocked_reasons": [], "warnings": [], "message": "No open scheduled tasks.", "skipped_tasks": skipped}
    capabilities = runtime_capabilities(runtime)
    if not capabilities["supports_subagent"]:
        return waiting_dispatch_result(repo, schedule_path, state_path, task, capabilities)

    task_id = str(task.get("id", ""))
    agent = str(task.get("agent", "")) or "agent"
    run_dir = (resolve(repo, state_path).parent if state_path else schedule_file.parent)  # type: ignore[union-attr]
    context_path = run_dir / "context-packs" / f"{task_id}.json"
    pack = context_pack.build_pack(repo, schedule_path, task_id=task_id, max_files=max_files, max_chars=max_chars)
    pack["path"] = rel(repo, context_path)
    pack["context_pack_path"] = rel(repo, context_path)
    atomic_write_json(context_path, pack)
    if not pack["ready"]:
        return {
            "ready": False,
            "blocked_reasons": ["Context pack: " + reason for reason in pack["blocked_reasons"]],
            "warnings": pack["warnings"],
            "capabilities": capabilities,
            "task": {"id": task_id, "agent": agent},
            "context_pack": rel(repo, context_path),
        }

    claim = agent_scheduler.claim(repo, schedule_path, task_id, agent, state_path)
    if not claim["ready"]:
        return {
            "ready": False,
            "blocked_reasons": claim["blocked_reasons"],
            "warnings": claim["warnings"],
            "capabilities": capabilities,
            "task": {"id": task_id, "agent": agent},
            "context_pack": rel(repo, context_path),
            "skipped_tasks": skipped,
        }

    claimed_schedule = read_json(schedule_file)
    claimed_task = agent_scheduler.find_task(claimed_schedule, task_id) or task
    invocation = write_invocation(repo, run_dir, claimed_task, capabilities["runtime"], context_path, coordinator_agent, developer_session)
    dispatch_status = "awaiting_runtime_spawn" if capabilities.get("spawn_requires_tool_call") else "worker_running"
    dispatch = {
        "status": dispatch_status,
        "runtime": capabilities["runtime"],
        "current_task_id": task_id,
        "current_agent": agent,
        "invocation_path": rel(repo, invocation),
        "context_pack": rel(repo, context_path),
    }
    state_update = update_dispatch_state(repo, state_path, dispatch)
    prompt = task_prompt(claimed_task, pack, invocation, repo)
    spawn_request = spawn_request_for_runtime(capabilities, claimed_task, prompt, schedule_path, state_path, repo)
    return {
        "ready": state_update["ready"],
        "blocked_reasons": state_update["blocked_reasons"],
        "warnings": claim["warnings"] + pack["warnings"] + state_update["warnings"],
        "capabilities": capabilities,
        "requires_fresh_worker": True,
        "coordinator_action": "spawn_fresh_worker",
        "worker_context_policy": "Use only the context pack and allowed inputs; do not continue in coordinator context.",
        "dispatch": dispatch,
        "task": {"id": task_id, "agent": agent, "phase": claimed_task.get("phase", ""), "service": claimed_task.get("service", "")},
        "claim": claim,
        "skipped_tasks": skipped,
        "context_pack": rel(repo, context_path),
        "invocation_path": rel(repo, invocation),
        "task_prompt": prompt,
        **({"runtime_spawn_request": spawn_request} if spawn_request else {}),
    }


def dispatch_complete(
    repo: Path,
    schedule_path: Path,
    state_path: Path | None,
    task_id: str,
    agent: str,
    evidence: list[str] | None = None,
) -> dict:
    repo = repo.resolve()
    schedule_file = resolve(repo, schedule_path)
    schedule = read_json(schedule_file)
    task = agent_scheduler.find_task(schedule, task_id) if schedule else {}
    dispatch_blockers, active_dispatch = dispatch_completion_blockers(repo, state_path, task_id, agent)
    if dispatch_blockers:
        return {"ready": False, "blocked_reasons": dispatch_blockers, "warnings": [], "dispatch": active_dispatch}
    mark_invocation_completed(repo, active_dispatch, evidence or [])
    reviewer_result = None
    if task and str(task.get("phase", "")).lower() in {"r1-review", "r2-review", "r3-review"}:
        phase_map = {"r1-review": "design", "r2-review": "test", "r3-review": "implementation"}
        review_dirs = sorted({Path(item).parent for item in evidence or [] if str(item).endswith(".md")})
        reviewer_result = reviewer_gate.validate(repo, review_dirs, [Path(item) for item in evidence or []], [phase_map[str(task.get("phase", "")).lower()]])
        if not reviewer_result["ready"]:
            return {
                "ready": False,
                "blocked_reasons": ["Reviewer gate: " + reason for reason in reviewer_result["blocked_reasons"]],
                "warnings": ["Reviewer gate: " + warning for warning in reviewer_result["warnings"]],
                "reviewer_gate": reviewer_result,
            }
    complete = agent_scheduler.complete(repo, schedule_path, task_id, agent, state_path, evidence or [])
    if reviewer_result is not None:
        complete["reviewer_gate"] = reviewer_result
    if complete["ready"]:
        _state_path, state = load_state(repo, state_path)
        previous_lifecycle = ""
        prior_dispatch = state.get("dispatch") if isinstance(state.get("dispatch"), dict) else {}
        if str(state.get("lifecycle", "")) == "WAITING_DISPATCH":
            previous_lifecycle = str(prior_dispatch.get("previous_lifecycle", ""))
        dispatch = {
            "status": "worker_completed",
            "runtime": "",
            "previous_lifecycle": previous_lifecycle,
            "current_task_id": task_id,
            "current_agent": agent,
            "invocation_path": "",
            "context_pack": "",
        }
        update = update_dispatch_state(repo, state_path, dispatch, lifecycle=previous_lifecycle or None)
        complete["run_state_update"] = update
    return complete


def dispatch_ack(
    repo: Path,
    state_path: Path | None,
    task_id: str,
    agent: str,
    worker_handle: str,
    worker_session: str = "",
) -> dict:
    repo = repo.resolve()
    state_file, state = load_state(repo, state_path)
    if not state_file or not state:
        return {"ready": False, "blocked_reasons": ["Run state is required to acknowledge a spawned worker."], "warnings": []}
    dispatch = state.get("dispatch") if isinstance(state.get("dispatch"), dict) else {}
    blocked: list[str] = []
    if str(dispatch.get("status", "")) not in {"awaiting_runtime_spawn", "waiting_dispatch"}:
        blocked.append("Dispatch is not awaiting runtime spawn acknowledgement.")
    if str(dispatch.get("current_task_id", "")) != task_id:
        blocked.append(f"Dispatch task mismatch: expected {dispatch.get('current_task_id', '')}, got {task_id}.")
    if str(dispatch.get("current_agent", "")) != agent:
        blocked.append(f"Dispatch agent mismatch: expected {dispatch.get('current_agent', '')}, got {agent}.")
    if not worker_handle.strip():
        blocked.append("Worker handle is required.")
    if blocked:
        return {"ready": False, "blocked_reasons": blocked, "warnings": [], "dispatch": dispatch}
    acknowledged = dict(dispatch)
    acknowledged.update(
        {
            "status": "worker_running",
            "worker_handle": worker_handle.strip(),
            "worker_session": worker_session.strip() or worker_handle.strip(),
            "spawn_acknowledged_at": run_state.now_iso(),
            "spawn_confirmed_by": "dispatch_ack",
        }
    )
    sync_invocation_for_ack(repo, dispatch, worker_handle, worker_session)
    update = update_dispatch_state(repo, state_path, acknowledged)
    return {
        "ready": update["ready"],
        "blocked_reasons": update["blocked_reasons"],
        "warnings": update["warnings"],
        "dispatch": acknowledged,
        "run_state_update": update,
    }


def dispatch_status(repo: Path, schedule_path: Path, state_path: Path | None = None) -> dict:
    repo = repo.resolve()
    schedule_file = resolve(repo, schedule_path)
    schedule = read_json(schedule_file)
    state_file, state = load_state(repo, state_path)
    tasks = [task for task in schedule.get("tasks", []) or [] if isinstance(task, dict)]
    open_tasks = [task for task in tasks if not task_done(task)]
    return {
        "ready": True,
        "blocked_reasons": [],
        "warnings": [],
        "schedule": str(schedule_file),
        "run_state": str(state_file) if state_file else None,
        "dispatch": state.get("dispatch", {}),
        "open_tasks": [
            {
                "id": task.get("id", ""),
                "agent": task.get("agent", ""),
                "phase": task.get("phase", ""),
                "service": task.get("service", ""),
                "status": task.get("status", "planned"),
                "owner": task.get("owner", ""),
            }
            for task in open_tasks
        ],
        "next_task": (open_tasks[0].get("id", "") if open_tasks else ""),
    }


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--schedule", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--runtime", default="claude-code")
    parser.add_argument("--coordinator-agent", default="coordinator-agent")
    parser.add_argument("--developer-session", default="coordinator-session")
    parser.add_argument("--task-id")
    parser.add_argument("--agent")
    parser.add_argument("--evidence", action="append")
    parser.add_argument("--action", choices=["capabilities", "next", "complete", "status"], default="status")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if args.action == "capabilities":
        result = runtime_capabilities(args.runtime)
        result.update({"ready": True, "blocked_reasons": [], "warnings": []})
    elif args.action == "next":
        if not args.schedule:
            parser.error("--schedule is required for --action next")
        result = dispatch_next(repo, args.schedule, args.state, args.runtime, args.coordinator_agent, args.developer_session)
    elif args.action == "complete":
        if not args.schedule or not args.task_id:
            parser.error("--schedule and --task-id are required for --action complete")
        result = dispatch_complete(repo, args.schedule, args.state, args.task_id, args.agent or "agent", args.evidence or [])
    else:
        if not args.schedule:
            parser.error("--schedule is required for --action status")
        result = dispatch_status(repo, args.schedule, args.state)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Dispatcher: " + ("READY" if result.get("ready") else "BLOCKED"))
        for reason in result.get("blocked_reasons", []):
            print(f"- {reason}")
        for warning in result.get("warnings", []):
            print(f"warning: {warning}")
        prompt = result.get("task_prompt")
        if prompt:
            print(prompt)
    return 0 if result.get("ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())
