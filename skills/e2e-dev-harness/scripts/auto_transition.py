#!/usr/bin/env python3
"""Advance run-state from a passed gate status artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_state  # noqa: E402


PHASE_TRANSITIONS = {
    "implementation": "IMPLEMENTED",
    "completion": "VERIFIED",
}


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def repo_path(repo: Path, path: Path) -> Path:
    root = repo.resolve()
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"Transition path resolves outside repository: {path}") from error
    return resolved


def parse_hook_input(text: str) -> list[Path]:
    if not text.strip():
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else data
    paths: list[Path] = []
    if isinstance(tool_input, dict):
        for key in ("file_path", "path", "target"):
            value = tool_input.get(key)
            if value:
                paths.append(Path(str(value)))
    return paths


def find_run_state(status_path: Path) -> Path | None:
    for parent in [status_path.parent, *status_path.parents]:
        candidate = parent / "run-state.json"
        if candidate.exists():
            return candidate
    return None


def evidence_for_phase(status: dict, status_file: Path) -> Path | None:
    phase = str(status.get("phase") or "")
    if phase == "implementation":
        return status_file
    if phase == "completion":
        for key in ("unit_test_evidence", "implementation_manifest", "red_test_evidence"):
            if status.get(key):
                return Path(str(status[key]))
    return None


def transition_from_status(repo: Path, status_path: Path, state_path: Path | None = None) -> dict:
    repo = repo.resolve()
    try:
        status_file = repo_path(repo, status_path)
        state_file = repo_path(repo, state_path) if state_path else find_run_state(status_file)
    except ValueError as error:
        return {"ready": False, "blocked_reasons": [str(error)], "warnings": [], "action": "blocked"}
    status = load_json(status_file)
    if not status:
        return {
            "ready": False,
            "blocked_reasons": [f"Gate status not found or unreadable: {status_file}"],
            "warnings": [],
            "action": "blocked",
        }
    if status.get("run_state_transition", {}).get("ready") is True:
        return {
            "ready": True,
            "blocked_reasons": [],
            "warnings": ["Gate status already contains a successful run-state transition."],
            "action": "skipped",
            "status_file": str(status_file),
        }
    if status.get("ready") is not True:
        return {
            "ready": True,
            "blocked_reasons": [],
            "warnings": ["Gate status is not ready; lifecycle transition skipped."],
            "action": "skipped",
            "status_file": str(status_file),
        }
    phase = str(status.get("phase") or "")
    target = PHASE_TRANSITIONS.get(phase)
    if not target:
        return {
            "ready": True,
            "blocked_reasons": [],
            "warnings": [f"No lifecycle transition is defined for phase: {phase or '<missing>'}"],
            "action": "skipped",
            "status_file": str(status_file),
        }
    if not state_file:
        return {
            "ready": False,
            "blocked_reasons": ["run-state.json was not supplied and could not be found from the gate status path."],
            "warnings": [],
            "action": "blocked",
            "status_file": str(status_file),
        }
    evidence = evidence_for_phase(status, status_file)
    transition = run_state.transition_state(
        repo,
        state_file,
        target,
        gate=phase,
        gate_status="passed",
        evidence=evidence,
    )
    return {
        "ready": transition["ready"],
        "blocked_reasons": transition["blocked_reasons"],
        "warnings": transition["warnings"],
        "action": "transitioned" if transition["ready"] else "blocked",
        "status_file": str(status_file),
        "run_state": str(state_file),
        "transition": transition,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--hook-input", help="JSON hook input, or '-' for stdin.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    status_files = [args.status_file] if args.status_file else []
    if args.hook_input:
        hook_text = sys.stdin.read() if args.hook_input == "-" else args.hook_input
        status_files.extend(parse_hook_input(hook_text))
    if not status_files:
        result = {"ready": False, "blocked_reasons": ["--status-file or --hook-input is required."], "warnings": []}
    else:
        result = transition_from_status(args.repo, status_files[0], args.state)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Auto transition: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
