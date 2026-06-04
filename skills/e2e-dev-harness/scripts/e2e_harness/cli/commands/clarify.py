"""Clarification command facade."""

from __future__ import annotations

import json
from pathlib import Path

import clarification_gate
import preflight as preflight_checks
from e2e_harness.engine import state_store


def _as_repo(path: Path) -> Path:
    return Path(path).resolve()


def _resolve_repo_path(repo: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.is_absolute() else repo / path


def _write_status(path: Path | None, result: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(
    repo: Path,
    design_doc: Path,
    run_state: Path | None = None,
    require_intent: bool = True,
    require_user_confirmation: bool = True,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    repo = _as_repo(repo)
    design_path = _resolve_repo_path(repo, design_doc)
    if not design_path or not design_path.exists():
        return 2, {"ready_for_implementation": False, "error": f"Design doc not found: {design_path}"}
    if run_state:
        dispatch_blockers = preflight_checks.clarification_dispatch_blockers(repo, run_state)
        if dispatch_blockers:
            result = preflight_checks.clarification_dispatch_recovery(repo, run_state, dispatch_blockers)
            _write_status(status_file, result)
            return 2, result
    result = clarification_gate.validate(
        design_path,
        require_intent=require_intent,
        require_user_confirmation=require_user_confirmation,
    )
    if run_state and result.get("ready_for_implementation"):
        dispatch_blockers = preflight_checks.clarification_dispatch_blockers(repo, run_state)
        if dispatch_blockers:
            result["ready_for_implementation"] = False
            result.setdefault("blocked_reasons", []).extend(dispatch_blockers)
            result["clarification_dispatch"] = {"ready": False, "blocked_reasons": dispatch_blockers}
            result["interaction_required"] = True
            result["questions_to_ask_user"] = [
                "Run dispatch-beat --max-workers 1 for requirements-clarifier and relay its returned Restated Intent/Open Questions first."
            ]
            _write_status(status_file, result)
            return 2, result
    if run_state and result.get("ready_for_implementation"):
        result["run_state_transition"] = state_store.transition_lifecycle(
            repo,
            run_state,
            "CLARIFIED",
            gate="clarification",
            gate_status="passed",
            evidence=design_path,
        )
        result["blocked_next_without_plan"] = True
        result["next_required"] = {
            "phase": "plan",
            "command": "Run e2e_dev_harness.py next, then e2e_dev_harness.py plan --create-archive before any code write.",
            "code_writes_allowed": False,
        }
    _write_status(status_file, result)
    return (0 if result["ready_for_implementation"] else 2), result


def run_from_args(args) -> tuple[int, dict]:
    return run(
        getattr(args, "repo"),
        getattr(args, "design_doc"),
        run_state=getattr(args, "run_state", None),
        require_intent=getattr(args, "require_intent", True),
        require_user_confirmation=getattr(args, "require_user_confirmation", True),
        status_file=getattr(args, "status_file", None),
    )
