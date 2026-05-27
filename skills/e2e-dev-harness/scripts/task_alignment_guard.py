#!/usr/bin/env python3
"""Detect task drift between requirements, declared scope, and changed files."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import clarification_gate  # noqa: E402
import coverage_gate  # noqa: E402
import implementation_manifest  # noqa: E402
from common import posix  # noqa: E402


ALWAYS_ALLOWED_PREFIXES = (
    "docs/agent-runs/",
    "docs/design/",
    "docs/requirements/",
    "docs/review-profiles/",
    ".e2e/",
    "skills/e2e-dev-harness/",
)
TEST_HINTS = ("/src/test/", "/test/", "/tests/", "test/", "tests/")


def repo_path(repo: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    root = repo.resolve()
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"Path resolves outside repository: {path}") from error
    return resolved


def read_text(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")


def changed_files_from_file(path: Path | None) -> list[str]:
    text = read_text(path)
    files: list[str] = []
    for line in text.splitlines():
        item = line.strip().replace("\\", "/")
        if not item or item.startswith("#"):
            continue
        if "\t" in item:
            item = item.split("\t")[-1].strip()
        files.append(item)
    return files


def changed_files_from_git(repo: Path, base_ref: str | None) -> tuple[list[str], list[str]]:
    if not base_ref:
        return [], []
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", base_ref, "--"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        return [], [f"Unable to run git diff for task alignment: {error}"]
    if completed.returncode != 0:
        return [], [completed.stderr.strip() or f"git diff failed with exit code {completed.returncode}"]
    return [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()], []


def normalize_scope(value: str) -> str:
    text = value.strip().strip("`").replace("\\", "/")
    text = text.split(":", 1)[0].strip()
    text = text.strip("/ ")
    return text


def coverage_services(matrix_path: Path | None) -> set[str]:
    text = read_text(matrix_path)
    services: set[str] = set()
    for row in coverage_gate.parse_markdown_tables(text):
        for value in implementation_manifest.split_cell_values(row.get("service", "")):
            service = normalize_scope(value)
            if service:
                services.add(service)
    return services


def manifest_scopes(repo: Path, manifest_path: Path | None) -> set[str]:
    text = read_text(manifest_path)
    scopes: set[str] = set()
    for row in coverage_gate.parse_markdown_tables(text):
        for module in implementation_manifest.module_names_from_row(row):
            scopes.add(normalize_scope(module))
        for artifact in implementation_manifest.split_artifacts(row.get("artifact", "")):
            artifact_path = normalize_scope(artifact)
            if "/" in artifact_path:
                parts = artifact_path.split("/")
                if parts[0] == "services" and len(parts) >= 2:
                    scopes.add("/".join(parts[:2]))
                else:
                    scopes.add(parts[0])
    return {scope for scope in scopes if scope}


def design_scopes(design_path: Path | None) -> set[str]:
    return {normalize_scope(value) for value in implementation_manifest.extract_design_modules(design_path)}


def allowed_scopes(repo: Path, design_doc: Path | None, manifest: Path | None, coverage_matrix: Path | None) -> set[str]:
    scopes = set()
    scopes.update(design_scopes(design_doc))
    scopes.update(manifest_scopes(repo, manifest))
    scopes.update(coverage_services(coverage_matrix))
    broad_roots = {"none", "n/a", "na", "services", "src", "docs", "java", "main", "test"}
    return {scope for scope in scopes if scope and scope.lower() not in broad_roots}


def path_allowed(path: str, scopes: set[str]) -> bool:
    normalized = normalize_scope(path)
    if not normalized:
        return True
    if normalized.startswith(ALWAYS_ALLOWED_PREFIXES):
        return True
    if any(hint in f"/{normalized}" for hint in TEST_HINTS):
        return True
    if not scopes:
        return False
    return any(normalized == scope or normalized.startswith(scope.rstrip("/") + "/") for scope in scopes)


def missing_coverage_ids(design_doc: Path | None, coverage_matrix: Path | None) -> list[str]:
    if not design_doc or not design_doc.exists() or not coverage_matrix or not coverage_matrix.exists():
        return []
    expected = [item["id"] for item in clarification_gate.extract_acceptance_items(design_doc)]
    rows = coverage_gate.parse_markdown_tables(read_text(coverage_matrix))
    covered = {clarification_gate.normalize_acceptance_id(row.get("id", "")) for row in rows}
    return [ac_id for ac_id in expected if ac_id not in covered]


def manifest_missing_ids(design_doc: Path | None, manifest: Path | None) -> list[str]:
    if not design_doc or not design_doc.exists() or not manifest or not manifest.exists():
        return []
    expected = [item["id"] for item in clarification_gate.extract_acceptance_items(design_doc)]
    manifest_text = read_text(manifest)
    return [ac_id for ac_id in expected if ac_id not in manifest_text]


def correction_actions(scope_drift: list[str], missing_coverage: list[str], missing_manifest: list[str], scopes: set[str]) -> list[dict]:
    actions: list[dict] = []
    if not scopes and scope_drift:
        actions.append(
            {
                "return_phase": "clarify",
                "reason": "No allowed implementation scope is declared, but code files changed.",
                "required_action": "Update the design Scope/Affected Modules or remove unrelated code changes.",
            }
        )
    elif scope_drift:
        actions.append(
            {
                "return_phase": "plan",
                "reason": "Changed files are outside declared design/manifest/coverage scope.",
                "required_action": "Either justify the expanded scope in the design and plan, or revert/move the unrelated changes.",
            }
        )
    if missing_coverage:
        actions.append(
            {
                "return_phase": "tdd-red",
                "reason": "Acceptance criteria are missing from the coverage matrix.",
                "required_action": "Add or repair tests and coverage rows for: " + ", ".join(missing_coverage),
            }
        )
    if missing_manifest:
        actions.append(
            {
                "return_phase": "implementation",
                "reason": "Acceptance criteria are missing from the implementation manifest.",
                "required_action": "Map implementation artifacts and code paths for: " + ", ".join(missing_manifest),
            }
        )
    return actions


def validate(
    repo: Path,
    design_doc: Path | None = None,
    implementation_manifest_path: Path | None = None,
    coverage_matrix: Path | None = None,
    changed_files_path: Path | None = None,
    base_ref: str | None = None,
) -> dict:
    repo = repo.resolve()
    blocked: list[str] = []
    warnings: list[str] = []
    try:
        design_path = repo_path(repo, design_doc)
        manifest_path = repo_path(repo, implementation_manifest_path)
        coverage_path = repo_path(repo, coverage_matrix)
        changed_path = repo_path(repo, changed_files_path)
    except ValueError as error:
        return {"repo": str(repo), "ready": False, "blocked_reasons": [str(error)], "warnings": []}

    scopes = allowed_scopes(repo, design_path, manifest_path, coverage_path)
    file_list = changed_files_from_file(changed_path)
    git_files, git_warnings = changed_files_from_git(repo, base_ref)
    warnings.extend(git_warnings)
    if git_files:
        file_list.extend(git_files)
    file_list = sorted(dict.fromkeys(posix(item) for item in file_list))
    scope_drift = [path for path in file_list if not path_allowed(path, scopes)]
    for path in scope_drift:
        blocked.append(f"Changed file is outside declared task scope: {path}")

    missing_coverage = missing_coverage_ids(design_path, coverage_path)
    if missing_coverage:
        blocked.append("Acceptance criteria missing from coverage matrix: " + ", ".join(missing_coverage))
    missing_manifest = manifest_missing_ids(design_path, manifest_path)
    if missing_manifest:
        blocked.append("Acceptance criteria missing from implementation manifest: " + ", ".join(missing_manifest))

    if not file_list:
        warnings.append("No changed-file evidence supplied; scope drift could not be fully checked.")

    actions = correction_actions(scope_drift, missing_coverage, missing_manifest, scopes)
    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "allowed_scopes": sorted(scopes),
        "changed_files": file_list,
        "scope_drift_files": scope_drift,
        "missing_coverage_acceptance_ids": missing_coverage,
        "missing_manifest_acceptance_ids": missing_manifest,
        "correction_actions": actions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--design-doc", type=Path)
    parser.add_argument("--implementation-manifest", type=Path)
    parser.add_argument("--coverage-matrix", type=Path)
    parser.add_argument("--changed-files", type=Path)
    parser.add_argument("--base-ref")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(
        args.repo,
        args.design_doc,
        args.implementation_manifest,
        args.coverage_matrix,
        args.changed_files,
        args.base_ref,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Task alignment: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for action in result.get("correction_actions", []):
            print(f"return {action['return_phase']}: {action['required_action']}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
