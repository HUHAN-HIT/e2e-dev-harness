#!/usr/bin/env python3
"""Create and validate e2e-dev-workflow run state files."""

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
        "schema": "e2e-dev-workflow.run-state.v1",
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
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def write_state(repo: Path, path: Path, state: dict) -> None:
    target = path if path.is_absolute() else repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
    if data.get("schema") != "e2e-dev-workflow.run-state.v1":
        blocked.append("Run state schema must be e2e-dev-workflow.run-state.v1.")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--strict-artifacts", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

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
