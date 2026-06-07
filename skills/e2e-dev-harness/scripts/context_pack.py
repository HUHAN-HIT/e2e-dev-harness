#!/usr/bin/env python3
"""Create and validate bounded context packs for scheduled agents."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import posix  # noqa: E402
import dir_graph  # noqa: E402
import memory_capture  # noqa: E402


SCHEMA = "e2e-dev-harness.context-pack.v1"


def resolve_repo_path(repo: Path, value: str | Path) -> Path:
    path = value if isinstance(value, Path) else Path(value)
    resolved = (path if path.is_absolute() else repo / path).resolve()
    resolved.relative_to(repo.resolve())
    return resolved


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def select_task(schedule: dict, agent: str | None = None, service: str | None = None, task_id: str | None = None) -> dict | None:
    for task in schedule.get("tasks", []):
        if not isinstance(task, dict):
            continue
        if task_id and task.get("id") == task_id:
            return task
        if agent and task.get("agent") == agent:
            return task
        if service and task.get("service") == service and task.get("phase") == "implement":
            return task
    return None


def looks_like_file_input(value: str) -> bool:
    text = value.replace("\\", "/").strip()
    if not text or text in {"user request", "knowledge graph summary"}:
        return False
    return "/" in text or bool(Path(text).suffix)


def estimate_inputs(repo: Path, inputs: list) -> tuple[int, list[dict], list[dict], list[str]]:
    total_chars = 0
    files: list[dict] = []
    missing_files: list[dict] = []
    warnings: list[str] = []
    for value in inputs:
        if not isinstance(value, str):
            continue
        try:
            path = resolve_repo_path(repo, value)
        except (ValueError, RuntimeError):
            continue
        if not path.exists() or not path.is_file():
            if looks_like_file_input(value):
                try:
                    missing_files.append({"path": posix(path.relative_to(repo.resolve())), "reason": "missing"})
                except ValueError:
                    pass
            continue
        size = path.stat().st_size
        total_chars += size
        files.append({"path": posix(path.relative_to(repo.resolve())), "bytes": size})
        if size > 200_000:
            warnings.append(f"Large context input should be summarized before dispatch: {posix(path.relative_to(repo.resolve()))}")
    return total_chars, files, missing_files, warnings


def primary_inputs_for_task(task: dict, inputs: list[str]) -> list[str]:
    phase = str(task.get("phase", ""))
    if phase not in {"tdd-red", "implement"}:
        return []
    return [
        value
        for value in inputs
        if isinstance(value, str) and "/service-designs/" in value.replace("\\", "/") and value.endswith(".md")
    ]


def memory_phase_for_task(task: dict) -> str:
    phase = str(task.get("phase", "")).strip()
    if phase in {"clarify", "requirements"}:
        return "requirements"
    if phase in {"design", "use-case", "plan"}:
        return "use-case"
    if phase in {"tdd-red", "test", "r2-review"}:
        return "test" if phase != "r2-review" else "review"
    if phase in {"implement", "code"}:
        return "code"
    if phase in {"r1-review", "r3-review", "review"}:
        return "review"
    if phase == "completion":
        return "completion"
    return "requirements"


def task_changed_files(task: dict) -> list[str]:
    values = task.get("changed_files", [])
    if isinstance(values, str):
        return [values]
    if isinstance(values, list):
        return [str(value) for value in values if str(value).strip()]
    return []


def build_pack(
    repo: Path,
    schedule_path: Path,
    agent: str | None = None,
    service: str | None = None,
    task_id: str | None = None,
    max_files: int = 12,
    max_chars: int = 120_000,
    max_memory_chars: int = 8_000,
) -> dict:
    repo = repo.resolve()
    schedule_file = resolve_repo_path(repo, schedule_path)
    schedule = read_json(schedule_file)
    task = select_task(schedule, agent, service, task_id)
    blocked: list[str] = []
    warnings: list[str] = []
    if not task:
        blocked.append("No matching scheduled task found for the requested agent/service/task id.")
        task = {}
    inputs = task.get("inputs", []) if isinstance(task.get("inputs"), list) else []
    outputs = task.get("outputs", []) if isinstance(task.get("outputs"), list) else []
    blocked.extend(dir_graph.context_pack_role_blockers(repo, task, outputs))
    primary_inputs = primary_inputs_for_task(task, inputs)
    input_chars, input_files, missing_input_files, input_warnings = estimate_inputs(repo, inputs)
    warnings.extend(input_warnings)
    memory_phase = memory_phase_for_task(task)
    memory_context = memory_capture.select_memory(
        repo,
        memory_phase,
        service=str(task.get("service", service or "")).strip() or None,
        max_chars=max_memory_chars,
        changed_files=task_changed_files(task),
        output_format="context-pack",
    )
    memory_budget = memory_context.get("memory_budget", {"max_chars": max_memory_chars, "actual_chars": 0, "truncated": False})
    memory_chars = int(memory_budget.get("actual_chars", 0) or 0)
    input_chars += memory_chars
    if len(input_files) > max_files:
        blocked.append(f"Context pack has {len(input_files)} file inputs, above max_files={max_files}.")
    if input_chars > max_chars:
        blocked.append(f"Context pack has {input_chars} input bytes, above max_chars={max_chars}.")
    return {
        "schema": SCHEMA,
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "schedule": posix(schedule_file.relative_to(repo)),
        "task": {
            "id": task.get("id", ""),
            "agent": task.get("agent", agent or ""),
            "phase": task.get("phase", ""),
            "service": task.get("service", service or ""),
            "depends_on_phases": task.get("depends_on_phases", []),
            "status": task.get("status", ""),
        },
        "context_policy": "request-scoped; no inherited developer chat context",
        "memory_policy": "optional-context-not-authority",
        "memory_context": {
            "phase": memory_phase,
            "snippets": memory_context.get("snippets", []),
            "files": memory_context.get("files", []),
            "tags": memory_context.get("tags", []),
            "links": memory_context.get("links", []),
            "selection_reason": memory_context.get("selection_reason", ""),
        },
        "memory_budget": memory_budget,
        "input_contract": "service-design-primary" if primary_inputs else "request-scoped",
        "primary_inputs": primary_inputs,
        "budget": {"max_files": max_files, "max_chars": max_chars, "input_files": len(input_files), "input_bytes": input_chars},
        "allowed_inputs": inputs,
        "allowed_outputs": outputs,
        "required_skill": task.get("required_skill", ""),
        "required_skill_path": task.get("required_skill_path", ""),
        "skill_reference_set": task.get("skill_reference_set", []) if isinstance(task.get("skill_reference_set"), list) else [],
        "resolved_input_files": input_files,
        "missing_input_files": missing_input_files,
    }


def validate(repo: Path, context_pack: Path, max_files: int = 12, max_chars: int = 120_000) -> dict:
    repo = repo.resolve()
    try:
        path = resolve_repo_path(repo, context_pack)
    except (ValueError, RuntimeError) as error:
        return {"ready": False, "blocked_reasons": [str(error)], "warnings": []}
    if not path.exists():
        return {"ready": False, "blocked_reasons": [f"Context pack not found: {path}"], "warnings": []}
    data = read_json(path)
    blocked: list[str] = []
    warnings: list[str] = []
    if data.get("schema") != SCHEMA:
        blocked.append(f"Context pack schema must be {SCHEMA}.")
    allowed_inputs = data.get("allowed_inputs", [])
    allowed_outputs = data.get("allowed_outputs", [])
    if not isinstance(allowed_inputs, list) or not isinstance(allowed_outputs, list):
        blocked.append("Context pack must include allowed_inputs and allowed_outputs lists.")
    for key in ("allowed_inputs", "allowed_outputs"):
        for value in data.get(key, []):
            if not isinstance(value, str):
                continue
            try:
                resolve_repo_path(repo, value)
            except (ValueError, RuntimeError):
                blocked.append(f"Context pack {key} path resolves outside repo: {value}")
    budget = data.get("budget", {}) if isinstance(data.get("budget"), dict) else {}
    if int(budget.get("input_files", 0) or 0) > max_files:
        blocked.append(f"Context pack input_files exceeds max_files={max_files}.")
    if int(budget.get("input_bytes", 0) or 0) > max_chars:
        blocked.append(f"Context pack input_bytes exceeds max_chars={max_chars}.")
    if data.get("context_policy") != "request-scoped; no inherited developer chat context":
        warnings.append("Context pack should declare request-scoped no-inherited context policy.")
    if data.get("memory_policy") and data.get("memory_policy") != "optional-context-not-authority":
        warnings.append("Context pack memory_policy should declare memory as optional context, not authority.")
    required_skill_path = data.get("required_skill_path", "")
    if isinstance(required_skill_path, str) and required_skill_path:
        try:
            if not resolve_repo_path(repo, required_skill_path).exists():
                warnings.append(f"required_skill_path missing from repo: {required_skill_path}")
        except (ValueError, RuntimeError):
            blocked.append(f"required_skill_path resolves outside repo: {required_skill_path}")
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "budget": budget,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--agent-schedule", type=Path)
    parser.add_argument("--agent")
    parser.add_argument("--service")
    parser.add_argument("--task-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate", dest="validate_pack", type=Path)
    parser.add_argument("--max-files", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=120_000)
    parser.add_argument("--max-memory-chars", type=int, default=8_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if args.validate_pack:
        result = validate(repo, args.validate_pack, args.max_files, args.max_chars)
    else:
        if not args.agent_schedule:
            parser.error("--agent-schedule is required unless --validate is used")
        result = build_pack(
            repo,
            args.agent_schedule,
            args.agent,
            args.service,
            args.task_id,
            args.max_files,
            args.max_chars,
            args.max_memory_chars,
        )
        if args.output:
            output = resolve_repo_path(repo, args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Context pack: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
