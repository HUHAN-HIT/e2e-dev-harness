#!/usr/bin/env python3
"""Block agent stop/finalization while a harness run still needs closure."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_state  # noqa: E402
from common import configure_utf8_stdio, posix  # noqa: E402


TERMINAL_LIFECYCLES = {"VERIFIED", "ARCHIVED"}
DEFAULT_BLOCK_LIFECYCLES = {"IMPLEMENTED", "REVIEWED", "REWORK_REQUIRED"}

NEXT_ACTIONS = {
    "CREATED": "Dispatch requirements-clarifier; relay returned Restated Intent/Open Questions before planning or coding.",
    "CLARIFIED": "Create the archive only if missing, then dispatch independent R1 review.",
    "SERVICE_DESIGN_REQUIRED": "Dispatch service-design workers and validate returned slices before TDD red.",
    "PLANNED": "Dispatch implementation-planner, TDD red, and R2 review, then open implementation through the implementation gate.",
    "RED_READY": "Complete R2 test review if missing, then run gate --phase implementation with red evidence and run-state.",
    "WAITING_DISPATCH": "Start the required independent subagent/session with dispatch-next or complete the manual dispatch packet.",
    "IMPLEMENTED": "Dispatch code-developer work for all assigned ACs, run ac-progress, dispatch R3 review, completion gate, strict guard, and archive.",
    "REVIEWED": "Run completion gate, strict guard, run summary, and requirements archive validation.",
    "REWORK_REQUIRED": "Follow the rework return phase and verify the rework item before finalizing.",
    "VERIFIED": "Archive the requirement summary and report evidence.",
    "ARCHIVED": "Run is terminal.",
}

REMAINING_PHASES = {
    "CREATED": [
        "clarify",
        "R1 design review",
        "plan/archive",
        "TDD red",
        "R2 test review",
        "implementation gate",
        "TDD green",
        "AC progress",
        "R3 implementation review",
        "completion gate",
        "strict guard",
        "archive",
    ],
    "CLARIFIED": [
        "R1 design review",
        "plan/archive",
        "service design split if multi-service",
        "TDD red",
        "R2 test review",
        "implementation gate",
        "TDD green",
        "AC progress",
        "R3 implementation review",
        "completion gate",
        "strict guard",
        "archive",
    ],
    "SERVICE_DESIGN_REQUIRED": [
        "service design validation",
        "TDD red",
        "R2 test review",
        "implementation gate",
        "TDD green",
        "AC progress",
        "R3 implementation review",
        "completion gate",
        "strict guard",
        "archive",
    ],
    "PLANNED": [
        "TDD red",
        "R2 test review",
        "implementation gate",
        "TDD green",
        "AC progress",
        "R3 implementation review",
        "completion gate",
        "strict guard",
        "archive",
    ],
    "RED_READY": [
        "R2 test review",
        "implementation gate",
        "TDD green",
        "AC progress",
        "R3 implementation review",
        "completion gate",
        "strict guard",
        "archive",
    ],
    "WAITING_DISPATCH": [
        "independent subagent/session dispatch",
        "agent-task completion evidence",
        "resume harness state machine",
    ],
    "IMPLEMENTED": [
        "continue remaining AC red/green",
        "AC progress",
        "R3 implementation review",
        "completion gate",
        "strict guard",
        "archive",
    ],
    "REVIEWED": ["completion gate", "strict guard", "archive"],
    "REWORK_REQUIRED": ["rework return phase", "re-verify", "completion gate", "strict guard", "archive"],
    "VERIFIED": ["archive"],
    "ARCHIVED": [],
}

COMMAND_HINTS = {
    "CREATED": [
        "e2e_dev_harness.py dispatch-next . --schedule <agent-schedule> --state <run-state> --runtime claude-code",
    ],
    "CLARIFIED": [
        "e2e_dev_harness.py plan . --design-doc docs/design/<feature>.md --agent-run-dir docs/agent-runs/<run> --create-archive",
        "e2e_dev_harness.py dispatch-next . --schedule <agent-schedule> --state <run-state> --runtime claude-code",
    ],
    "SERVICE_DESIGN_REQUIRED": [
        "e2e_dev_harness.py service-design . --global-design docs/design/<feature>.md --service-design-dir docs/agent-runs/<run>/service-designs --run-state <run-state>",
    ],
    "PLANNED": [
        "e2e_dev_harness.py dispatch-beat . --schedule <agent-schedule> --state <run-state> --runtime claude-code",
    ],
    "RED_READY": [
        "e2e_dev_harness.py gate . --phase implementation --run-state <run-state> --red-test-evidence <red-evidence> --review-dir <reviews>",
    ],
    "WAITING_DISPATCH": [
        "e2e_dev_harness.py dispatch-next . --schedule <agent-schedule> --state <run-state> --runtime claude-code",
    ],
    "IMPLEMENTED": [
        "e2e_dev_harness.py dispatch-beat . --schedule <agent-schedule> --state <run-state> --runtime claude-code",
        "e2e_dev_harness.py ac-progress . --design-doc <design> --coverage-matrix <coverage> --implementation-manifest <manifest> --unit-test-evidence <green-evidence>",
        "dispatch independent R3 implementation review, then run gate --phase completion",
    ],
    "REVIEWED": [
        "e2e_dev_harness.py gate . --phase completion --run-state <run-state> --design-doc <design> --unit-test-evidence <green-evidence>",
        "e2e_dev_harness.py verify . --strict-workflow --run-state <run-state>",
    ],
    "REWORK_REQUIRED": [
        "follow the rework item return phase before finalizing",
    ],
    "VERIFIED": [
        "archive the requirement summary and report evidence",
    ],
}


def load_json(path: Path) -> tuple[dict | None, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, str(error)
    return data if isinstance(data, dict) else None, "JSON root is not an object."


def resolve_path(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    return path if path.is_absolute() else repo / path


def latest_run_state(repo: Path) -> Path | None:
    run_root = repo / "docs" / "agent-runs"
    if not run_root.exists():
        return None
    candidates = [path for path in run_root.glob("*/run-state.json") if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def run_dir_has_files(path: Path) -> bool:
    try:
        return any(child.is_file() for child in path.rglob("*"))
    except OSError:
        return False


def stale_empty_run_dirs(repo: Path) -> list[Path]:
    run_root = repo / "docs" / "agent-runs"
    if not run_root.exists():
        return []
    return [
        path
        for path in run_root.iterdir()
        if path.is_dir() and not (path / "run-state.json").exists() and not run_dir_has_files(path)
    ]


def latest_run_dir_without_state_with_files(repo: Path) -> Path | None:
    run_root = repo / "docs" / "agent-runs"
    if not run_root.exists():
        return None
    candidates = [
        path
        for path in run_root.iterdir()
        if path.is_dir() and not (path / "run-state.json").exists() and run_dir_has_files(path)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def schedule_path_for_state(state_path: Path, explicit_schedule: Path | None = None, repo: Path | None = None) -> Path | None:
    if explicit_schedule:
        return explicit_schedule if explicit_schedule.is_absolute() or repo is None else repo / explicit_schedule
    candidate = state_path.parent / "agent-schedule.json"
    return candidate if candidate.exists() else None


def open_schedule_tasks(schedule_path: Path | None) -> list[dict]:
    if not schedule_path or not schedule_path.exists():
        return []
    data, _error = load_json(schedule_path)
    if not data:
        return []
    open_tasks: list[dict] = []
    for task in data.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        if str(task.get("status", "planned")).lower() != "completed":
            open_tasks.append(
                {
                    "id": task.get("id", ""),
                    "phase": task.get("phase", ""),
                    "service": task.get("service", ""),
                    "status": task.get("status", "planned"),
                    "owner": task.get("owner", ""),
                }
            )
    return open_tasks


def rel(repo: Path, path: Path | None) -> str | None:
    if not path:
        return None
    try:
        return posix(path.resolve().relative_to(repo.resolve()))
    except (OSError, ValueError):
        return str(path)


def stop_guidance(lifecycle: str, state_path: Path | None, repo: Path) -> dict:
    hints = list(COMMAND_HINTS.get(lifecycle, []))
    if state_path:
        state_value = rel(repo, state_path) or str(state_path)
        hints = [hint.replace("<run-state>", state_value) for hint in hints]
    if lifecycle == "CREATED":
        return {
            "must_continue": False,
            "next_action": "Ask the user to confirm Restated Intent and answer or defer Open Questions before running clarify.",
            "remaining_phases": REMAINING_PHASES.get(lifecycle, []),
            "recommended_commands": hints,
            "agent_instruction": (
                "Ask the user for product decisions and record confirmation provenance such as "
                "'confirmed-by: user @<date/session>'; do not self-answer open questions to advance the harness."
            ),
            "forbidden_response": (
                "Do not summarize as finished, do not mark clarification complete from self-authored answers, "
                "and do not plan/TDD/code before user-confirmed clarification evidence exists."
            ),
        }
    return {
        "must_continue": lifecycle not in TERMINAL_LIFECYCLES,
        "next_action": NEXT_ACTIONS.get(lifecycle, "Inspect run-state.json and repair lifecycle before finalizing."),
        "remaining_phases": REMAINING_PHASES.get(lifecycle, []),
        "recommended_commands": hints,
        "agent_instruction": (
            "Do not ask the user to choose between normal harness phases. "
            "Continue with the next required phase unless a real product decision or missing external approval blocks progress."
        ),
        "forbidden_response": (
            "Do not summarize as finished, do not say the system is normal after a stop-hook block, "
            "and do not offer R3/completion while earlier required phases remain."
        ),
    }


def is_waiting_dispatch(lifecycle: str, data: dict) -> bool:
    dispatch = data.get("dispatch") if isinstance(data.get("dispatch"), dict) else {}
    dispatches = data.get("dispatches") if isinstance(data.get("dispatches"), dict) else {}
    waiting_statuses = {
        "waiting_dispatch",
        "awaiting_runtime_spawn",
        "worker_running",
        "worker_running_unverified",
    }
    if any(str(item.get("status", "")).lower() in waiting_statuses for item in dispatches.values() if isinstance(item, dict)):
        return True
    return lifecycle == "WAITING_DISPATCH" or str(dispatch.get("status", "")).lower() in {
        *waiting_statuses,
    }


def write_blocked_stderr(result: dict) -> None:
    if result.get("ready"):
        return
    print("HARNESS STOP BLOCKED", file=sys.stderr)
    lifecycle = result.get("lifecycle")
    if lifecycle:
        print(f"Lifecycle: {lifecycle}", file=sys.stderr)
    for reason in result.get("blocked_reasons", [])[:6]:
        print(f"- {reason}", file=sys.stderr)
    guidance = result.get("guidance") if isinstance(result.get("guidance"), dict) else {}
    next_action = guidance.get("next_action") or result.get("next_action")
    if next_action:
        print(f"Next required action: {next_action}", file=sys.stderr)
    remaining = guidance.get("remaining_phases") or []
    if remaining:
        print("Remaining phases: " + " -> ".join(str(item) for item in remaining[:10]), file=sys.stderr)
    commands = guidance.get("recommended_commands") or []
    if commands:
        print("Recommended command/action:", file=sys.stderr)
        print(f"  {commands[0]}", file=sys.stderr)
    agent_instruction = guidance.get("agent_instruction")
    if agent_instruction:
        print(agent_instruction, file=sys.stderr)


def evaluate(
    repo: Path,
    run_state_path: Path | None = None,
    run_dir: Path | None = None,
    schedule: Path | None = None,
    strict: bool = False,
    block_lifecycle: set[str] | None = None,
    block_open_tasks: bool = True,
) -> dict:
    repo = repo.resolve()
    state_path = resolve_path(repo, run_state_path)
    if not state_path and run_dir:
        state_path = resolve_path(repo, run_dir) / "run-state.json"  # type: ignore[operator]
    if not state_path:
        state_path = latest_run_state(repo)
    if not state_path:
        run_dir_candidate = latest_run_dir_without_state_with_files(repo)
        if run_dir_candidate:
            return {
                "ready": False,
                "blocked_reasons": [
                    f"Stop blocked: harness run directory exists without run-state.json: {run_dir_candidate}"
                ],
                "warnings": [],
                "repo": str(repo),
                "run_state": str(run_dir_candidate / "run-state.json"),
            }
        empty_dirs = stale_empty_run_dirs(repo)
        warnings = ["No active harness run-state found; stop guard allowed finalization."]
        if empty_dirs:
            names = ", ".join(rel(repo, path) or str(path) for path in empty_dirs[:5])
            suffix = "" if len(empty_dirs) <= 5 else f" (+{len(empty_dirs) - 5} more)"
            warnings.append(f"Ignored empty harness run directories without run-state.json: {names}{suffix}.")
        return {
            "ready": True,
            "blocked_reasons": [],
            "warnings": warnings,
            "repo": str(repo),
            "run_state": None,
        }

    data, error = load_json(state_path)
    if not data:
        return {
            "ready": False,
            "blocked_reasons": [f"Stop blocked: run-state is unreadable or invalid: {state_path}: {error}"],
            "warnings": [],
            "repo": str(repo),
            "run_state": str(state_path),
        }

    lifecycle = str(data.get("lifecycle", ""))
    dispatch_waiting = is_waiting_dispatch(lifecycle, data)
    blocked: list[str] = []
    warnings: list[str] = []
    block_set = block_lifecycle or DEFAULT_BLOCK_LIFECYCLES
    if lifecycle not in run_state.LIFECYCLE:
        blocked.append(f"Stop blocked: run-state lifecycle is invalid: {lifecycle}")
    elif dispatch_waiting:
        warnings.append(
            "Run is waiting for an independent subagent/session dispatch; stop is allowed so a fresh worker can be started, but completion is not ready."
        )
    elif strict and lifecycle not in TERMINAL_LIFECYCLES:
        blocked.append(f"Stop blocked: lifecycle {lifecycle} is not terminal. {NEXT_ACTIONS.get(lifecycle, '')}")
    elif lifecycle in block_set:
        blocked.append(f"Stop blocked: lifecycle {lifecycle} still requires harness closure. {NEXT_ACTIONS.get(lifecycle, '')}")

    schedule_path = schedule_path_for_state(state_path, resolve_path(repo, schedule), repo)
    open_tasks = open_schedule_tasks(schedule_path)
    if open_tasks and lifecycle in {"IMPLEMENTED", "REVIEWED", "REWORK_REQUIRED"} and block_open_tasks:
        ids = ", ".join(str(task.get("id") or "<unnamed>") for task in open_tasks[:8])
        suffix = "" if len(open_tasks) <= 8 else f" (+{len(open_tasks) - 8} more)"
        blocked.append(f"Stop blocked: agent schedule still has open tasks: {ids}{suffix}.")
    elif open_tasks:
        warnings.append(f"Agent schedule has {len(open_tasks)} open task(s).")

    provenance = run_state.validate_lifecycle_provenance(repo, state_path, data)
    if provenance and lifecycle in {"IMPLEMENTED", "REVIEWED", "VERIFIED", "ARCHIVED"} and not dispatch_waiting:
        blocked.extend("Stop blocked: " + reason for reason in provenance)

    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "repo": str(repo),
        "run_state": str(state_path),
        "lifecycle": lifecycle,
        "dispatch": data.get("dispatch", {}),
        "dispatches": data.get("dispatches", {}),
        "dispatch_waiting": dispatch_waiting,
        "completion_ready": lifecycle in TERMINAL_LIFECYCLES and not blocked,
        "next_action": NEXT_ACTIONS.get(lifecycle, "Inspect run-state.json and repair lifecycle before finalizing."),
        "guidance": stop_guidance(lifecycle, state_path, repo),
        "schedule": str(schedule_path) if schedule_path else None,
        "open_tasks": open_tasks,
    }


def parse_hook_input(source: str | None) -> None:
    if source == "-":
        try:
            sys.stdin.read()
        except OSError:
            pass


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--run-state", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--schedule", type=Path)
    parser.add_argument("--hook-input")
    parser.add_argument("--strict", action="store_true", help="Block every non-terminal lifecycle, not only post-code phases.")
    parser.add_argument(
        "--block-lifecycle",
        action="append",
        choices=sorted(run_state.LIFECYCLE),
        help="Lifecycle to block. Repeatable. Defaults to IMPLEMENTED/REVIEWED/REWORK_REQUIRED.",
    )
    parser.add_argument("--allow-open-tasks", action="store_true", help="Do not block on open agent-schedule tasks.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    parse_hook_input(args.hook_input)
    result = evaluate(
        args.repo,
        run_state_path=args.run_state,
        run_dir=args.run_dir,
        schedule=args.schedule,
        strict=args.strict,
        block_lifecycle=set(args.block_lifecycle or []) or None,
        block_open_tasks=not args.allow_open_tasks,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Harness stop guard: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    write_blocked_stderr(result)
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
