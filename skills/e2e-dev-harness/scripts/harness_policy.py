#!/usr/bin/env python3
"""Validate harness policy for an e2e-dev-harness run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_POLICY = {
    "schema": "e2e-dev-harness.policy.v1",
    "require_run_state": True,
    "require_artifact_registry": True,
    "require_gitnexus_for_cross_service": True,
    "require_contracts_for_cross_service": True,
    "require_handoffs_for_multi_agent": True,
    "require_requirements_archive_on_completion": True,
    "require_semantic_reviews_on_completion": True,
}
IMMUTABLE_TRUE_POLICY_FIELDS = frozenset(
    key for key, value in DEFAULT_POLICY.items() if key.startswith("require_") and value is True
)


def load_json(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def merge_policy(overrides: dict) -> dict:
    policy = dict(DEFAULT_POLICY)
    policy.update(overrides)
    for field in IMMUTABLE_TRUE_POLICY_FIELDS:
        policy[field] = DEFAULT_POLICY[field]
    return policy


def discover_policy(repo: Path, explicit: Path | None = None) -> tuple[dict, str]:
    if explicit:
        path = explicit if explicit.is_absolute() else repo / explicit
        return merge_policy(load_json(path)), str(path)
    for candidate in (
        repo / ".e2e" / "harness-policy.json",
        repo / "docs" / "harness-policy.json",
    ):
        if candidate.exists():
            return merge_policy(load_json(candidate)), str(candidate)
    return dict(DEFAULT_POLICY), "default"


def artifacts_by_type(registry: dict | None) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for item in (registry or {}).get("artifacts", []):
        if isinstance(item, dict):
            result.setdefault(str(item.get("type", "")), []).append(item)
    return result


def any_present(items: list[dict]) -> bool:
    return any(item.get("status") == "present" for item in items)


def validate_policy(
    repo: Path,
    policy_path: Path | None,
    run_state_data: dict | None,
    registry_data: dict | None,
    lifecycle: str = "",
) -> dict:
    repo = repo.resolve()
    policy, source = discover_policy(repo, policy_path)
    blocked: list[str] = []
    warnings: list[str] = []
    state = run_state_data or {}
    registry = registry_data or {}
    artifact_types = artifacts_by_type(registry)
    selected_mode = str(state.get("selected_mode") or registry.get("selected_mode") or "")
    services = state.get("services") or registry.get("services") or []
    cross_service = len(services) > 1 or selected_mode == "multi"
    effective_lifecycle = lifecycle or str(state.get("lifecycle", ""))
    completion_like = effective_lifecycle in {"VERIFIED", "ARCHIVED", "REVIEWED"}

    if policy.get("require_run_state") and not state:
        blocked.append("Policy requires run-state.json.")
    if policy.get("require_artifact_registry") and not registry:
        blocked.append("Policy requires artifact-registry.json.")
    if policy.get("require_handoffs_for_multi_agent") and selected_mode == "multi":
        if not any_present(artifact_types.get("requirements", [])) and not any_present(artifact_types.get("code_agent", [])):
            blocked.append("Policy requires populated handoff artifacts for multi-agent runs.")
    if policy.get("require_contracts_for_cross_service") and cross_service:
        if not any_present(artifact_types.get("contracts_dir", [])) and not any_present(artifact_types.get("contract_pattern", [])):
            blocked.append("Policy requires contract artifact registration for cross-service runs.")
    if policy.get("require_gitnexus_for_cross_service") and cross_service:
        if not any_present(artifact_types.get("impact_evidence", [])):
            blocked.append("Policy requires raw impact evidence for cross-service runs.")
    if completion_like and policy.get("require_requirements_archive_on_completion"):
        if not any_present(artifact_types.get("requirements_archive", [])):
            blocked.append("Policy requires requirements archive on completion.")
    if completion_like and policy.get("require_semantic_reviews_on_completion"):
        if not any_present(artifact_types.get("design_review", [])):
            blocked.append("Policy requires R1 design review on completion.")
        if not any_present(artifact_types.get("test_review", [])):
            blocked.append("Policy requires R2 test review on completion.")
        if not any_present(artifact_types.get("implementation_review", [])):
            blocked.append("Policy requires R3 implementation review on completion.")

    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "policy_source": source,
        "policy": policy,
        "selected_mode": selected_mode,
        "services": services,
        "lifecycle": effective_lifecycle,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--run-state", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--lifecycle", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    state = load_json(args.run_state if args.run_state and args.run_state.is_absolute() else (repo / args.run_state if args.run_state else None))
    registry = load_json(args.registry if args.registry and args.registry.is_absolute() else (repo / args.registry if args.registry else None))
    result = validate_policy(repo, args.policy, state, registry, args.lifecycle)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Harness policy: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
