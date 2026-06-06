#!/usr/bin/env python3
"""Create and validate agent-run artifact registries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from common import posix


DIRECTORY_KEYS = {
    "agent_run_dir",
    "review_requests_dir",
    "reviews_dir",
    "rework_dir",
    "contracts_dir",
    "service_designs_dir",
}
PATTERN_KEYS = {
    "rework_pattern",
    "contract_pattern",
    "context_pack_pattern",
    "service_design_pattern",
}
REQUIRED_BY_COMPLETION = {
    "design_doc",
    "exec_plan",
    "requirements",
    "use_cases",
    "test_plan",
    "implementation_plan",
    "agent_schedule",
    "knowledge_graph_status",
    "dependency_report",
    "impact_summary",
    "impact_evidence",
    "test_impact_plan",
    "service_design",
    "implementation_manifest",
    "requirements_archive",
    "red_test_evidence",
    "green_test_evidence",
    "coverage_matrix",
    "business_review",
    "phase_coverage",
    "strict_guard_result",
}
DERIVED_BY_COMPLETION = {
    "knowledge_graph_status": "python skills/e2e-dev-harness/scripts/kg_refresh.py . --json",
    "dependency_report": "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py prepare . --json-full",
    "impact_summary": "gitnexus impact <changed-symbol> --repo <repo-root>",
    "impact_evidence": "gitnexus detect-changes --repo <repo-root> --scope unstaged",
    "test_impact_plan": "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py test-impact . --output <path>",
}
MATERIALIZED_REQUIRED_BY_COMPLETION = REQUIRED_BY_COMPLETION - set(DERIVED_BY_COMPLETION)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def resolve(repo: Path, value: str) -> Path:
    repo_root = repo.resolve()
    path = Path(value)
    resolved = (path if path.is_absolute() else repo_root / path).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as error:
        raise ValueError(f"Artifact path resolves outside repository: {value}") from error
    return resolved


def artifact_entry(repo: Path, key: str, value: str, owner: str = "global") -> dict:
    resolved = resolve(repo, value)
    is_pattern = key in PATTERN_KEYS or "<" in value
    is_dir = key in DIRECTORY_KEYS
    exists = resolved.exists() if not is_pattern else False
    entry = {
        "id": f"{owner}:{key}",
        "type": key,
        "owner": owner,
        "path": posix(value),
        "kind": "pattern" if is_pattern else ("directory" if is_dir else "file"),
        "required_by_completion": key in MATERIALIZED_REQUIRED_BY_COMPLETION,
        "derived_by_completion": key in DERIVED_BY_COMPLETION,
        "status": "pattern" if is_pattern else ("present" if exists else "planned"),
        "sha256": sha256(resolved) if exists and resolved.is_file() else "",
    }
    if key in DERIVED_BY_COMPLETION:
        entry["regenerate_command"] = DERIVED_BY_COMPLETION[key]
    return entry


def flatten_artifacts(repo: Path, artifacts: dict) -> list[dict]:
    entries: list[dict] = []
    for key, value in artifacts.items():
        if key == "service_plans" or not isinstance(value, str):
            continue
        entries.append(artifact_entry(repo, key, value))
    for service, paths in artifacts.get("service_plans", {}).items():
        for key, value in paths.items():
            if isinstance(value, str):
                entries.append(artifact_entry(repo, key, value, owner=service))
    return entries


def build_registry(repo: Path, run_id: str, artifacts: dict, selected_mode: str = "", services: list[str] | None = None) -> dict:
    return {
        "schema": "e2e-dev-harness.artifact-registry.v1",
        "run_id": run_id,
        "selected_mode": selected_mode,
        "services": services or [],
        "artifacts": flatten_artifacts(repo, artifacts),
    }


def write_registry(repo: Path, path: Path, registry: dict) -> None:
    target = resolve(repo, str(path))
    atomic_write_text(target, json.dumps(registry, indent=2, ensure_ascii=False) + "\n")


def validate_registry(repo: Path, registry_path: Path, strict: bool = False) -> dict:
    repo = repo.resolve()
    blocked: list[str] = []
    warnings: list[str] = []
    try:
        path = resolve(repo, str(registry_path))
    except ValueError as error:
        return {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": [str(error)],
            "warnings": warnings,
            "registry": str(registry_path),
            "artifact_count": 0,
        }
    if not path.exists():
        return {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": [f"Artifact registry not found: {path}"],
            "warnings": warnings,
            "registry": str(path),
            "artifact_count": 0,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": [f"Artifact registry is invalid JSON: {error}"],
            "warnings": warnings,
            "registry": str(path),
            "artifact_count": 0,
        }
    if data.get("schema") != "e2e-dev-harness.artifact-registry.v1":
        blocked.append("Artifact registry schema must be e2e-dev-harness.artifact-registry.v1.")
    artifacts = data.get("artifacts", [])
    if not isinstance(artifacts, list) or not artifacts:
        blocked.append("Artifact registry must include at least one artifact entry.")
        artifacts = []
    for item in artifacts:
        item_path = str(item.get("path", ""))
        if not item_path:
            blocked.append("Artifact registry entry is missing path.")
            continue
        if item.get("kind") == "pattern":
            continue
        try:
            resolved = resolve(repo, item_path)
        except ValueError as error:
            blocked.append(str(error))
            continue
        if item.get("required_by_completion") and strict and not resolved.exists():
            blocked.append(f"Required completion artifact is missing: {item_path}")
        if resolved.exists() and resolved.is_file():
            current_hash = sha256(resolved)
            recorded_hash = str(item.get("sha256", ""))
            if recorded_hash and recorded_hash != current_hash:
                blocked.append(f"Artifact hash is stale: {item_path}")
            elif not recorded_hash:
                if strict:
                    blocked.append(f"Artifact hash is missing (strict mode): {item_path}")
                else:
                    warnings.append(f"Artifact hash is missing: {item_path}")
    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "registry": str(path),
        "artifact_count": len(artifacts),
    }


def refresh_registry(repo: Path, registry_path: Path) -> dict:
    repo = repo.resolve()
    blocked: list[str] = []
    warnings: list[str] = []
    try:
        path = resolve(repo, str(registry_path))
    except ValueError as error:
        return {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": [str(error)],
            "warnings": warnings,
            "registry": str(registry_path),
            "changed": [],
        }
    if not path.exists():
        return {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": [f"Artifact registry not found: {path}"],
            "warnings": warnings,
            "registry": str(path),
            "changed": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": [f"Artifact registry is invalid JSON: {error}"],
            "warnings": warnings,
            "registry": str(path),
            "changed": [],
        }
    artifacts = data.get("artifacts", [])
    if not isinstance(artifacts, list):
        blocked.append("Artifact registry artifacts must be a list.")
        artifacts = []
    changed: list[str] = []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "pattern":
            continue
        item_path = str(item.get("path", ""))
        if not item_path:
            continue
        try:
            resolved = resolve(repo, item_path)
        except ValueError as error:
            blocked.append(str(error))
            continue
        old_status = item.get("status")
        old_hash = item.get("sha256", "")
        if resolved.exists():
            item["status"] = "present"
            item["sha256"] = sha256(resolved) if resolved.is_file() else ""
        else:
            item["status"] = "planned"
            item["sha256"] = ""
        if item.get("status") != old_status or item.get("sha256", "") != old_hash:
            changed.append(str(item.get("id") or item_path))
    if not blocked:
        atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "registry": str(path),
        "changed": changed,
        "artifact_count": len(artifacts),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = refresh_registry(args.repo, args.registry) if args.refresh else validate_registry(args.repo, args.registry, args.strict)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Artifact registry: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
