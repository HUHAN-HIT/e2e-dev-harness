#!/usr/bin/env python3
"""Create and validate e2e-dev-harness run state files."""

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

import artifact_registry  # noqa: E402
from common import posix  # noqa: E402


PHASE_LOCK = ".phase-lock"
LIFECYCLE = {
    "CREATED",
    "CLARIFIED",
    "SERVICE_DESIGN_REQUIRED",
    "PLANNED",
    "RED_READY",
    "WAITING_DISPATCH",
    "IMPLEMENTED",
    "REVIEWED",
    "REWORK_REQUIRED",
    "VERIFIED",
    "ARCHIVED",
}
ORDERED_LIFECYCLE = [
    "CREATED",
    "CLARIFIED",
    "SERVICE_DESIGN_REQUIRED",
    "PLANNED",
    "RED_READY",
    "WAITING_DISPATCH",
    "IMPLEMENTED",
    "REVIEWED",
    "VERIFIED",
    "ARCHIVED",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_state(
    run_id: str,
    selected_mode: str,
    services: list[str],
    artifact_registry_path: str,
    lifecycle: str = "PLANNED",
) -> dict:
    return {
        "schema": "e2e-dev-harness.run-state.v1",
        "run_id": run_id,
        "lifecycle": lifecycle,
        "selected_mode": selected_mode,
        "services": services,
        "artifact_registry": posix(artifact_registry_path),
        "gates": {
            "clarification": "planned",
            "service_design": "planned",
            "planning": "planned",
            "implementation": "planned",
            "completion": "planned",
            "guard": "planned",
        },
        "owners": {},
        "history": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def atomic_write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(tmp_name).unlink(missing_ok=True)
        raise


def write_state(repo: Path, path: Path, state: dict) -> None:
    target = path if path.is_absolute() else repo / path
    atomic_write_text(target, json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    write_phase_lock(repo, target, state)


def phase_lock_payload(state: dict) -> dict:
    lifecycle = state.get("lifecycle", "")
    return {
        "schema": "e2e-dev-harness.phase-lock.v1",
        "run_id": state.get("run_id", ""),
        "lifecycle": lifecycle,
        "state": (
            "code-write-open"
            if lifecycle == "IMPLEMENTED"
            else ("test-write-open" if lifecycle in {"PLANNED", "RED_READY"} else "code-write-locked")
        ),
        "allowed_code_write_lifecycles": ["IMPLEMENTED"],
        "allowed_test_write_lifecycles": ["PLANNED", "RED_READY", "IMPLEMENTED"],
        "selected_mode": state.get("selected_mode", ""),
        "services": state.get("services", []),
        "owners": state.get("owners", {}),
        "shared_edit_scopes": state.get("shared_edit_scopes", []),
        "updated_at": state.get("updated_at", now_iso()),
    }


def write_phase_lock(repo: Path, state_path: Path, state: dict) -> Path:
    target = state_path if state_path.is_absolute() else repo / state_path
    lock = target.parent / PHASE_LOCK
    atomic_write_text(lock, json.dumps(phase_lock_payload(state), indent=2, ensure_ascii=False) + "\n")
    return lock


def validate_state(repo: Path, state_path: Path, strict_artifacts: bool = False) -> dict:
    repo = repo.resolve()
    path = state_path if state_path.is_absolute() else repo / state_path
    blocked: list[str] = []
    warnings: list[str] = []
    registry_result = None
    if not path.exists():
        return {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": [f"Run state not found: {path}"],
            "warnings": warnings,
            "run_state": str(path),
            "artifact_registry": None,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": [f"Run state is invalid JSON: {error}"],
            "warnings": warnings,
            "run_state": str(path),
            "artifact_registry": None,
        }
    if data.get("schema") != "e2e-dev-harness.run-state.v1":
        blocked.append("Run state schema must be e2e-dev-harness.run-state.v1.")
    lifecycle = str(data.get("lifecycle", ""))
    if lifecycle not in LIFECYCLE:
        blocked.append("Run state lifecycle is invalid: " + lifecycle)
    if not data.get("run_id"):
        blocked.append("Run state must include run_id.")
    if not data.get("selected_mode"):
        blocked.append("Run state must include selected_mode.")
    registry_path = data.get("artifact_registry")
    if not registry_path:
        blocked.append("Run state must include artifact_registry.")
    else:
        registry_result = artifact_registry.validate_registry(repo, Path(str(registry_path)), strict_artifacts)
        if not registry_result["ready"]:
            blocked.extend("Artifact registry: " + reason for reason in registry_result["blocked_reasons"])
        warnings.extend("Artifact registry: " + warning for warning in registry_result["warnings"])
    gates = data.get("gates", {})
    if not isinstance(gates, dict):
        blocked.append("Run state gates must be an object.")
    blocked.extend(validate_lifecycle_provenance(repo, path, data))
    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "run_state": str(path),
        "lifecycle": lifecycle,
        "artifact_registry": registry_result,
    }


def resolve_evidence_path(repo: Path, state_path: Path, evidence: str) -> Path | None:
    if not evidence:
        return None
    value = Path(str(evidence))
    if value.is_absolute():
        return value
    run_dir = state_path.parent
    candidate = (run_dir / value).resolve()
    if candidate.exists():
        return candidate
    return (repo / value).resolve()


def validate_transition_event(
    repo: Path,
    state_path: Path,
    event: dict,
    target: str,
    gate: str,
    statuses: set[str],
    require_ready_evidence: bool = False,
) -> list[str]:
    blocked: list[str] = []
    if str(event.get("to", "")) != target:
        return [f"Run state lifecycle {target} is missing a transition history event."]
    if str(event.get("gate", "")) != gate:
        blocked.append(f"Run state transition to {target} must come from gate={gate}.")
    if str(event.get("gate_status", "")) not in statuses:
        blocked.append(f"Run state transition to {target} must have a passing gate_status.")
    evidence_path = resolve_evidence_path(repo, state_path, str(event.get("evidence", "")))
    if not evidence_path or not evidence_path.exists():
        blocked.append(f"Run state transition to {target} references missing evidence: {event.get('evidence') or '<missing>'}")
    elif require_ready_evidence:
        try:
            evidence_data = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
            blocked.append(f"Run state transition to {target} evidence is not valid JSON: {error}")
        else:
            if not isinstance(evidence_data, dict) or evidence_data.get("ready") is not True:
                blocked.append(f"Run state transition to {target} requires ready=true evidence.")
            elif target == "IMPLEMENTED":
                blocked.extend(validate_implementation_gate_evidence(repo, state_path, evidence_data))
            elif target == "VERIFIED":
                blocked.extend(validate_completion_gate_evidence(evidence_data))
    return blocked


def evidence_path_exists(repo: Path, state_path: Path, value: str) -> bool:
    path = resolve_evidence_path(repo, state_path, value)
    return bool(path and path.exists())


def validate_implementation_gate_evidence(repo: Path, state_path: Path, evidence: dict) -> list[str]:
    blocked: list[str] = []
    if str(evidence.get("phase", "")) != "implementation":
        blocked.append("Implementation transition evidence must be a phase=implementation gate result.")
    if evidence.get("knowledge_graph_status_loaded") is not True:
        blocked.append("Implementation transition evidence must include loaded knowledge graph status.")
    tdd = evidence.get("tdd") if isinstance(evidence.get("tdd"), dict) else {}
    if tdd.get("ready") is not True:
        blocked.append("Implementation transition evidence must include passing TDD red evidence validation.")
    red_path = str(tdd.get("red_evidence") or "")
    if not red_path:
        blocked.append("Implementation transition evidence must reference the red test evidence path.")
    elif not evidence_path_exists(repo, state_path, red_path):
        blocked.append(f"Implementation transition red test evidence is missing: {red_path}")
    semantic_reviews = evidence.get("semantic_reviews") if isinstance(evidence.get("semantic_reviews"), dict) else {}
    if semantic_reviews.get("ready") is not True:
        blocked.append("Implementation transition evidence must include passing independent design/test semantic reviews.")
    covered = {
        str(phase)
        for phase in semantic_reviews.get("covered_phases", []) or []
    }
    missing = {"design", "test"} - covered
    if missing:
        blocked.append("Implementation transition semantic reviews must cover: " + ", ".join(sorted(missing)))
    return blocked


def validate_completion_gate_evidence(evidence: dict) -> list[str]:
    blocked: list[str] = []
    if str(evidence.get("phase", "")) != "completion":
        blocked.append("Verified transition evidence must be a phase=completion gate result.")
    if evidence.get("ready") is not True:
        blocked.append("Verified transition evidence must have ready=true.")
    return blocked


def validate_lifecycle_provenance(repo: Path, state_path: Path, state: dict) -> list[str]:
    lifecycle = str(state.get("lifecycle", ""))
    if lifecycle not in {"IMPLEMENTED", "REVIEWED", "VERIFIED", "ARCHIVED"}:
        return []
    history = state.get("history")
    if not isinstance(history, list) or not history:
        return [f"Run state lifecycle {lifecycle} requires transition history; do not edit run-state.json directly."]
    blocked: list[str] = []
    implemented_events = [event for event in history if isinstance(event, dict) and event.get("to") == "IMPLEMENTED"]
    if not implemented_events:
        blocked.append("Run state lifecycle requires a prior IMPLEMENTED transition history event.")
    else:
        blocked.extend(
            validate_transition_event(
                repo,
                state_path,
                implemented_events[-1],
                "IMPLEMENTED",
                "implementation",
                {"passed", "ready", "approved"},
                require_ready_evidence=True,
            )
        )
    if lifecycle in {"VERIFIED", "ARCHIVED"}:
        verified_events = [event for event in history if isinstance(event, dict) and event.get("to") == "VERIFIED"]
        if not verified_events:
            blocked.append("Run state lifecycle VERIFIED requires a completion transition history event.")
        else:
            blocked.extend(
                validate_transition_event(
                    repo,
                    state_path,
                    verified_events[-1],
                    "VERIFIED",
                    "completion",
                    {"passed", "ready", "approved"},
                    require_ready_evidence=True,
                )
            )
    return blocked


def load_state(repo: Path, state_path: Path) -> tuple[Path, dict | None, list[str]]:
    path = state_path if state_path.is_absolute() else repo / state_path
    if not path.exists():
        return path, None, [f"Run state not found: {path}"]
    try:
        return path, json.loads(path.read_text(encoding="utf-8")), []
    except json.JSONDecodeError as error:
        return path, None, [f"Run state is invalid JSON: {error}"]


def transition_allowed(current: str, target: str, allow_regression: bool) -> tuple[bool, str]:
    if target == "REWORK_REQUIRED":
        return True, ""
    if current == target:
        return True, ""
    if current not in ORDERED_LIFECYCLE or target not in ORDERED_LIFECYCLE:
        return False, f"Run state transition uses invalid lifecycle: {current} -> {target}"
    if ORDERED_LIFECYCLE.index(target) < ORDERED_LIFECYCLE.index(current) and not allow_regression:
        return False, f"Run state transition regression is not allowed without --allow-regression: {current} -> {target}"
    return True, ""


def transition_state(
    repo: Path,
    state_path: Path,
    target_lifecycle: str,
    gate: str | None = None,
    gate_status: str | None = None,
    evidence: Path | None = None,
    allow_regression: bool = False,
) -> dict:
    repo = repo.resolve()
    path, data, errors = load_state(repo, state_path)
    if errors or data is None:
        return {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": errors,
            "warnings": [],
            "run_state": str(path),
        }
    current = str(data.get("lifecycle", ""))
    allowed, reason = transition_allowed(current, target_lifecycle, allow_regression)
    blocked = [] if allowed else [reason]
    if current in {"IMPLEMENTED", "REVIEWED", "VERIFIED", "ARCHIVED"}:
        blocked.extend(validate_lifecycle_provenance(repo, path, data))
    evidence_path = None
    if evidence:
        evidence_path = evidence if evidence.is_absolute() else repo / evidence
        if not evidence_path.exists():
            blocked.append(f"Transition evidence not found: {evidence_path}")
    if target_lifecycle == "IMPLEMENTED":
        if gate != "implementation":
            blocked.append("Transition to IMPLEMENTED requires gate=implementation.")
        if gate_status not in {"passed", "ready", "approved"}:
            blocked.append("Transition to IMPLEMENTED requires gate_status=passed.")
        if not evidence_path:
            blocked.append("Transition to IMPLEMENTED requires implementation gate evidence.")
        elif evidence_path.exists():
            try:
                gate_data = json.loads(evidence_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
                blocked.append(f"Transition to IMPLEMENTED requires valid JSON implementation gate evidence: {error}")
            else:
                if not isinstance(gate_data, dict):
                    blocked.append("Transition to IMPLEMENTED requires implementation gate evidence to be a JSON object.")
                elif str(gate_data.get("phase", "")) != "implementation" or gate_data.get("ready") is not True:
                    blocked.append("Transition to IMPLEMENTED requires passed implementation gate evidence.")
                else:
                    blocked.extend(validate_implementation_gate_evidence(repo, path, gate_data))
    if target_lifecycle == "VERIFIED":
        if gate != "completion":
            blocked.append("Transition to VERIFIED requires gate=completion.")
        if gate_status not in {"passed", "ready", "approved"}:
            blocked.append("Transition to VERIFIED requires gate_status=passed.")
        if not evidence_path:
            blocked.append("Transition to VERIFIED requires completion gate evidence.")
        elif evidence_path.exists():
            try:
                gate_data = json.loads(evidence_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
                blocked.append(f"Transition to VERIFIED requires valid JSON completion gate evidence: {error}")
            else:
                if not isinstance(gate_data, dict):
                    blocked.append("Transition to VERIFIED requires completion gate evidence to be a JSON object.")
                elif str(gate_data.get("phase", "")) != "completion" or gate_data.get("ready") is not True:
                    blocked.append("Transition to VERIFIED requires passed completion gate evidence.")
                else:
                    blocked.extend(validate_completion_gate_evidence(gate_data))
    if target_lifecycle == "ARCHIVED" and current != "VERIFIED":
        blocked.append("Transition to ARCHIVED requires current lifecycle VERIFIED.")
    if blocked:
        return {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": blocked,
            "warnings": [],
            "run_state": str(path),
            "lifecycle": current,
        }
    gates = data.setdefault("gates", {})
    if gate:
        gates[gate] = gate_status or "passed"
    event = {
        "from": current,
        "to": target_lifecycle,
        "gate": gate or "",
        "gate_status": gate_status or "",
        "evidence": posix(str(evidence if evidence else "")),
        "updated_at": now_iso(),
    }
    data.setdefault("history", []).append(event)
    data["lifecycle"] = target_lifecycle
    data["updated_at"] = event["updated_at"]
    write_state(repo, path, data)
    return {
        "repo": str(repo),
        "ready": True,
        "blocked_reasons": [],
        "warnings": [],
        "run_state": str(path),
        "lifecycle": target_lifecycle,
        "history_event": event,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--strict-artifacts", action="store_true")
    parser.add_argument("--transition", choices=sorted(LIFECYCLE))
    parser.add_argument("--gate")
    parser.add_argument("--gate-status")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--allow-regression", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.transition:
        result = transition_state(
            args.repo,
            args.state,
            args.transition,
            args.gate,
            args.gate_status,
            args.evidence,
            args.allow_regression,
        )
    else:
        result = validate_state(args.repo, args.state, args.strict_artifacts)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Run state: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
