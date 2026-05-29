#!/usr/bin/env python3
"""Claim and complete machine-readable agent schedule tasks."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_state  # noqa: E402


CLAIMED_STATUSES = {"claimed", "in-progress", "in_progress", "completed"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def resolve(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    return path if path.is_absolute() else repo / path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find_task(schedule: dict, task_id: str) -> dict | None:
    for task in schedule.get("tasks", []) or []:
        if str(task.get("id", "")) == task_id:
            return task
    return None


def service_tasks(schedule: dict, services: list[str], phase: str = "implement") -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    for task in schedule.get("tasks", []) or []:
        service = str(task.get("service", ""))
        if str(task.get("phase", "")) == phase and service:
            tasks[service] = task
    return {service: tasks.get(service, {}) for service in services}


def posix_path(value: str) -> str:
    return value.replace("\\", "/").strip()


def evidence_paths(repo: Path, evidence: list[str] | None) -> tuple[list[str], list[str]]:
    blocked: list[str] = []
    resolved: list[str] = []
    for item in evidence or []:
        path = Path(str(item))
        full = path if path.is_absolute() else repo / path
        if not full.exists() or not full.is_file():
            blocked.append(f"Task completion evidence is missing: {full}")
            continue
        try:
            stored = full.resolve().relative_to(repo.resolve())
        except ValueError:
            stored = path if not path.is_absolute() else full
        resolved.append(posix_path(str(stored)))
    if not evidence:
        blocked.append("Task completion requires at least one evidence file.")
    return resolved, blocked


def evidence_matches_outputs(task: dict, evidence: list[str]) -> bool:
    outputs = {posix_path(str(output)) for output in task.get("outputs", []) or [] if isinstance(output, str)}
    if not outputs:
        return True
    normalized_evidence = {posix_path(item) for item in evidence}
    return bool(outputs & normalized_evidence)


def validate_schedule(schedule: dict, services: list[str], require_claims: bool = False, require_completed: bool = False) -> dict:
    blocked: list[str] = []
    warnings: list[str] = []
    if schedule.get("schema") != "e2e-dev-harness.agent-schedule.v1":
        blocked.append("Agent schedule schema must be e2e-dev-harness.agent-schedule.v1.")
    tasks = service_tasks(schedule, services)
    for service, task in tasks.items():
        if not task:
            blocked.append(f"Missing implement task for service/module: {service}")
            continue
        status = str(task.get("status", "planned")).lower()
        owner = str(task.get("owner", "")).strip()
        if require_claims and (not owner or status not in CLAIMED_STATUSES):
            blocked.append(f"Implement task for {service} must be claimed before code writes.")
        if require_completed and status != "completed":
            blocked.append(f"Implement task for {service} must be completed before completion.")
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "services": services,
        "require_claims": require_claims,
        "require_completed": require_completed,
    }


def update_state_owner(repo: Path, state_path: Path | None, task: dict, agent: str, status: str, evidence: list[str] | None = None) -> dict:
    if not state_path:
        return {"ready": True, "blocked_reasons": [], "warnings": ["No run-state supplied; schedule updated only."]}
    path = resolve(repo, state_path)
    if not path or not path.exists():
        return {"ready": False, "blocked_reasons": [f"Run state not found: {path}"], "warnings": []}
    state = load_json(path)
    service = str(task.get("service", ""))
    if service and str(task.get("phase", "")) == "implement":
        state.setdefault("owners", {})[service] = {
            "task_id": task.get("id", ""),
            "agent": agent,
            "status": status,
            "claimed_at": task.get("claimed_at", ""),
            "completed_at": task.get("completed_at", ""),
            "allowed_scope": [service + "/"],
            "evidence": evidence or [],
        }
    state["updated_at"] = now_iso()
    run_state.write_state(repo, path, state)
    return {"ready": True, "blocked_reasons": [], "warnings": [], "run_state": str(path)}


def claim(repo: Path, schedule_path: Path, task_id: str, agent: str, state_path: Path | None = None) -> dict:
    path = resolve(repo, schedule_path)
    if not path or not path.exists():
        return {"ready": False, "blocked_reasons": [f"Agent schedule not found: {path}"], "warnings": []}
    schedule = load_json(path)
    task = find_task(schedule, task_id)
    if not task:
        return {"ready": False, "blocked_reasons": [f"Task not found in agent schedule: {task_id}"], "warnings": []}
    status = str(task.get("status", "planned")).lower()
    if status == "completed":
        return {"ready": False, "blocked_reasons": [f"Task already completed: {task_id}"], "warnings": []}
    task["status"] = "claimed"
    task["owner"] = agent
    task["claimed_at"] = task.get("claimed_at") or now_iso()
    atomic_write_json(path, schedule)
    state_result = update_state_owner(repo, state_path, task, agent, "claimed")
    blocked = [] if state_result["ready"] else state_result["blocked_reasons"]
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": state_result["warnings"],
        "schedule": str(path),
        "task": task,
        "run_state_update": state_result,
    }


def complete(
    repo: Path,
    schedule_path: Path,
    task_id: str,
    agent: str,
    state_path: Path | None = None,
    evidence: list[str] | None = None,
) -> dict:
    path = resolve(repo, schedule_path)
    if not path or not path.exists():
        return {"ready": False, "blocked_reasons": [f"Agent schedule not found: {path}"], "warnings": []}
    schedule = load_json(path)
    task = find_task(schedule, task_id)
    if not task:
        return {"ready": False, "blocked_reasons": [f"Task not found in agent schedule: {task_id}"], "warnings": []}
    owner = str(task.get("owner", ""))
    if owner and owner != agent:
        return {"ready": False, "blocked_reasons": [f"Task {task_id} is owned by {owner}, not {agent}."], "warnings": []}
    resolved_evidence, evidence_blocked = evidence_paths(repo, evidence)
    if evidence_blocked:
        return {"ready": False, "blocked_reasons": evidence_blocked, "warnings": []}
    if not evidence_matches_outputs(task, resolved_evidence):
        return {
            "ready": False,
            "blocked_reasons": [f"Task {task_id} completion evidence must reference one of the task outputs."],
            "warnings": [],
        }
    if not owner:
        task["owner"] = agent
        task["claimed_at"] = task.get("claimed_at") or now_iso()
    task["status"] = "completed"
    task["completed_at"] = now_iso()
    task["evidence"] = resolved_evidence
    atomic_write_json(path, schedule)
    state_result = update_state_owner(repo, state_path, task, agent, "completed", resolved_evidence)
    blocked = [] if state_result["ready"] else state_result["blocked_reasons"]
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": state_result["warnings"],
        "schedule": str(path),
        "task": task,
        "run_state_update": state_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--schedule", required=True, type=Path)
    parser.add_argument("--task-id")
    parser.add_argument("--agent", default="")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--action", choices=["claim", "complete", "validate"], required=True)
    parser.add_argument("--service", action="append")
    parser.add_argument("--require-claims", action="store_true")
    parser.add_argument("--require-completed", action="store_true")
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if args.action == "claim":
        result = claim(repo, args.schedule, args.task_id or "", args.agent or "agent", args.state)
    elif args.action == "complete":
        result = complete(repo, args.schedule, args.task_id or "", args.agent or "agent", args.state, args.evidence)
    else:
        path = resolve(repo, args.schedule)
        schedule = load_json(path) if path and path.exists() else {}
        result = validate_schedule(schedule, args.service or [], args.require_claims, args.require_completed)
        if path:
            result["schedule"] = str(path)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Agent schedule: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
