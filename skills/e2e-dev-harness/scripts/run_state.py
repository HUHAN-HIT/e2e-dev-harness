#!/usr/bin/env python3
"""Create and validate e2e-dev-harness run state files."""

from __future__ import annotations

import argparse
import json
import sys
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
    "PLANNED",
    "RED_READY",
    "IMPLEMENTED",
    "REVIEWED",
    "REWORK_REQUIRED",
    "VERIFIED",
    "ARCHIVED",
}
ORDERED_LIFECYCLE = [
    "CREATED",
    "CLARIFIED",
    "PLANNED",
    "RED_READY",
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


def write_state(repo: Path, path: Path, state: dict) -> None:
    target = path if path.is_absolute() else repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_phase_lock(repo, target, state)


def phase_lock_payload(state: dict) -> dict:
    return {
        "schema": "e2e-dev-harness.phase-lock.v1",
        "run_id": state.get("run_id", ""),
        "lifecycle": state.get("lifecycle", ""),
        "state": "code-write-open" if state.get("lifecycle") == "IMPLEMENTED" else "code-write-locked",
        "allowed_code_write_lifecycles": ["IMPLEMENTED"],
        "updated_at": state.get("updated_at", now_iso()),
    }


def write_phase_lock(repo: Path, state_path: Path, state: dict) -> Path:
    target = state_path if state_path.is_absolute() else repo / state_path
    lock = target.parent / PHASE_LOCK
    lock.write_text(json.dumps(phase_lock_payload(state), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "run_state": str(path),
        "lifecycle": lifecycle,
        "artifact_registry": registry_result,
    }


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
    evidence_path = None
    if evidence:
        evidence_path = evidence if evidence.is_absolute() else repo / evidence
        if not evidence_path.exists():
            blocked.append(f"Transition evidence not found: {evidence_path}")
    if target_lifecycle == "VERIFIED" and not evidence_path:
        blocked.append("Transition to VERIFIED requires evidence.")
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
