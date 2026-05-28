#!/usr/bin/env python3
"""Replay harness validation from run-state and registered artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import artifact_registry  # noqa: E402
import harness_policy  # noqa: E402
import implementation_gate  # noqa: E402
import run_summary  # noqa: E402
import run_state  # noqa: E402


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def resolve(repo: Path, path: str | None) -> Path | None:
    if not path:
        return None
    value = Path(path)
    repo_root = repo.resolve()
    resolved = (value if value.is_absolute() else repo_root / value).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as error:
        raise ValueError(f"Harness path resolves outside repository: {path}") from error
    return resolved


def registry_entry(registry: dict, artifact_type: str, owner: str = "global") -> Path | None:
    for item in registry.get("artifacts", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == artifact_type and item.get("owner") == owner:
            path = item.get("path")
            if path:
                return Path(str(path))
    return None


def validate(
    repo: Path,
    state_path: Path,
    policy_path: Path | None = None,
    strict_artifacts: bool = False,
    run_completion_gate: bool = False,
) -> dict:
    repo = repo.resolve()
    blocked: list[str] = []
    warnings: list[str] = []
    state_result = run_state.validate_state(repo, state_path, strict_artifacts)
    if not state_result["ready"]:
        blocked.extend("Run state: " + reason for reason in state_result["blocked_reasons"])
    warnings.extend("Run state: " + warning for warning in state_result["warnings"])

    state_data = load_json(state_path if state_path.is_absolute() else repo / state_path)
    if not state_data:
        return {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": blocked or ["Run state could not be loaded."],
            "warnings": warnings,
            "run_state": state_result,
            "artifact_registry": None,
            "policy": None,
            "completion_gate": None,
        }
    try:
        registry_path = resolve(repo, state_data.get("artifact_registry"))
    except ValueError as error:
        registry_path = None
        blocked.append(str(error))
    registry_data = load_json(registry_path) if registry_path else {}
    registry_result = None
    if registry_path:
        registry_result = artifact_registry.validate_registry(repo, registry_path, strict_artifacts)
        if not registry_result["ready"]:
            blocked.extend("Artifact registry: " + reason for reason in registry_result["blocked_reasons"])
        warnings.extend("Artifact registry: " + warning for warning in registry_result["warnings"])

    policy_result = harness_policy.validate_policy(
        repo,
        policy_path,
        state_data,
        registry_data,
        str(state_data.get("lifecycle", "")),
    )
    if not policy_result["ready"]:
        blocked.extend("Policy: " + reason for reason in policy_result["blocked_reasons"])
    warnings.extend("Policy: " + warning for warning in policy_result["warnings"])

    gate_result = None
    if run_completion_gate:
        gate_result = implementation_gate.validate_gate_request(
            implementation_gate.GateRequest(
                repo=repo,
                design_doc=registry_entry(registry_data, "design_doc") or registry_entry(registry_data, "design"),
                kg_status_file=registry_entry(registry_data, "knowledge_graph_status"),
                phase="completion",
                red_test_evidence=registry_entry(registry_data, "red_test_evidence"),
                coverage_matrix=registry_entry(registry_data, "coverage_matrix"),
                unit_test_evidence=registry_entry(registry_data, "green_test_evidence"),
                business_review=registry_entry(registry_data, "business_review"),
                dependency_report=registry_entry(registry_data, "dependency_report"),
                implementation_manifest=registry_entry(registry_data, "implementation_manifest"),
                requirements_archive=registry_entry(registry_data, "requirements_archive"),
                require_requirements_archive=True,
                handoff_dirs=[registry_entry(registry_data, "agent_run_dir") / "handoffs"] if registry_entry(registry_data, "agent_run_dir") else None,
                contract_dirs=[registry_entry(registry_data, "contracts_dir")] if registry_entry(registry_data, "contracts_dir") else None,
                require_contracts=len(state_data.get("services", [])) > 1,
                require_handoffs=state_data.get("selected_mode") == "multi",
            )
        )
        if not gate_result["ready"]:
            blocked.extend("Completion gate: " + reason for reason in gate_result["blocked_reasons"])

    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "run_state": state_result,
        "artifact_registry": registry_result,
        "policy": policy_result,
        "completion_gate": gate_result,
    }


def write_summary_outputs(
    repo: Path,
    state_path: Path,
    result: dict,
    summary_json: Path | None = None,
    summary_md: Path | None = None,
) -> dict:
    if not summary_json and not summary_md:
        return {}
    repo = repo.resolve()
    json_path = summary_json if not summary_json or summary_json.is_absolute() else repo / summary_json
    md_path = summary_md if not summary_md or summary_md.is_absolute() else repo / summary_md
    summary = run_summary.build_summary(repo, state_path, result)
    run_summary.write_outputs(summary, json_path, md_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--strict-artifacts", action="store_true")
    parser.add_argument("--run-completion-gate", action="store_true")
    parser.add_argument("--summary-json", type=Path)
    parser.add_argument("--summary-md", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(args.repo, args.state, args.policy, args.strict_artifacts, args.run_completion_gate)
    summary = write_summary_outputs(args.repo, args.state, result, args.summary_json, args.summary_md)
    if summary:
        result["run_summary"] = summary
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Harness verify: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
