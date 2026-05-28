#!/usr/bin/env python3
"""Create and validate incremental test impact plans."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import coverage_gate  # noqa: E402
from common import parse_modules, posix  # noqa: E402


SCHEMA = "e2e-dev-harness.test-impact-plan.v1"
DOC_EXTENSIONS = {".md", ".adoc", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".svg"}
BUILD_FILES = {"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"}


def resolve_repo_path(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    return path if path.is_absolute() else repo / path


def read_json(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def parse_changed_files(path: Path | None) -> list[str]:
    if not path or not path.exists():
        return []
    changed: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        candidate = parts[-1] if len(parts) > 1 and re.fullmatch(r"[AMDRCU?]{1,3}", parts[0]) else line
        candidate = posix(candidate.strip('"')).lstrip("./")
        if candidate and candidate not in seen:
            seen.add(candidate)
            changed.append(candidate)
    return changed


def is_docs_only(path: str) -> bool:
    normalized = posix(path)
    if normalized.startswith(("docs/", ".e2e/", ".agents/", ".claude/")):
        return True
    return Path(normalized).suffix.lower() in DOC_EXTENSIONS


def closest_maven_module(repo: Path, changed_file: str) -> str | None:
    candidate = (repo / changed_file).parent
    repo = repo.resolve()
    try:
        candidate.resolve().relative_to(repo)
    except ValueError:
        return None
    while True:
        if (candidate / "pom.xml").exists():
            relative = candidate.relative_to(repo)
            return "." if str(relative) == "." else posix(relative)
        if candidate == repo:
            return None
        candidate = candidate.parent


def module_for_changed_file(repo: Path, changed_file: str) -> tuple[str | None, str]:
    normalized = posix(changed_file)
    if is_docs_only(normalized):
        return None, "documentation or harness-only change"
    parts = normalized.split("/")
    if len(parts) >= 2 and parts[0] == "services" and (repo / parts[0] / parts[1] / "pom.xml").exists():
        return f"services/{parts[1]}", "service-local Maven module"
    module = closest_maven_module(repo, normalized)
    if module:
        return module, "nearest Maven module"
    if Path(normalized).name in BUILD_FILES or normalized.startswith(("src/", "config/", "deploy/", ".github/")):
        return ".", "root/shared build or source change"
    if Path(normalized).suffix.lower() in {".java", ".kt", ".xml", ".yml", ".yaml", ".properties"}:
        return ".", "source/config change without a local module"
    return None, "no test-bearing module detected"


def services_from_dependency_report(path: Path | None) -> list[str]:
    report = read_json(path)
    services: list[str] = []
    seen: set[str] = set()
    for dependency in report.get("dependencies", []):
        if not isinstance(dependency, dict):
            continue
        for key in ("source_service", "target_service", "service", "module"):
            value = dependency.get(key)
            if isinstance(value, str):
                normalized = posix(value).strip("/")
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    services.append(normalized)
    return services


def command_for_module(module: str) -> str:
    return "mvn test" if module == "." else f"mvn -pl {module} -am test"


def build_plan(repo: Path, changed_files: list[str], dependency_report: Path | None = None) -> dict:
    repo = repo.resolve()
    commands: list[dict] = []
    modules: dict[str, set[str]] = {}
    reasons: dict[str, set[str]] = {}
    ignored: list[dict] = []
    for changed_file in changed_files:
        module, reason = module_for_changed_file(repo, changed_file)
        if not module:
            ignored.append({"path": changed_file, "reason": reason})
            continue
        modules.setdefault(module, set()).add(changed_file)
        reasons.setdefault(module, set()).add(reason)

    for service in services_from_dependency_report(dependency_report):
        if (repo / service / "pom.xml").exists():
            modules.setdefault(service, set()).add(f"dependency-report:{service}")
            reasons.setdefault(service, set()).add("cross-service dependency report")

    root_modules = set(parse_modules(repo / "pom.xml"))
    for index, module in enumerate(sorted(modules), start=1):
        command = command_for_module(module)
        scope = "full" if module == "." else "module"
        if module != "." and root_modules and module not in root_modules and not (repo / module / "pom.xml").exists():
            scope = "module-unverified"
        commands.append(
            {
                "id": f"TST-{index:03d}",
                "scope": scope,
                "module": module,
                "command": command,
                "required": True,
                "reason": "; ".join(sorted(reasons[module])),
                "changed_files": sorted(modules[module]),
            }
        )

    status = "ready" if commands or ignored else "incomplete"
    return {
        "schema": SCHEMA,
        "status": status,
        "strategy": "incremental-tests",
        "repo": str(repo),
        "changed_files": changed_files,
        "ignored_changes": ignored,
        "commands": commands,
        "notes": (
            "Run every required command and store JSON command evidence. "
            "Use full Maven verification when root/shared changes are present."
        ),
    }


def normalize_command(command: str) -> str:
    command = command.replace("\\", "/").strip().strip('"')
    command = re.sub(r'"([^"]+)"', r"\1", command)
    command = re.sub(r"'([^']+)'", r"\1", command)
    parts = command.split()
    if parts:
        first = parts[0].lower()
        if first.endswith("/mvn.cmd") or first.endswith("/mvn") or first in {"mvn.cmd", "mvn"}:
            parts[0] = "mvn"
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def load_plan(repo: Path, path: Path) -> tuple[dict | None, list[str]]:
    resolved = resolve_repo_path(repo, path)
    assert resolved is not None
    if not resolved.exists():
        return None, [f"Test impact plan not found: {resolved}"]
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return None, [f"Test impact plan is invalid JSON and must be repaired before completion: {error}"]
    if not isinstance(data, dict):
        return None, ["Test impact plan must be a JSON object."]
    return data, []


def validate(repo: Path, test_impact_plan: Path | None, unit_test_evidence: Path | None) -> dict:
    blocked: list[str] = []
    warnings: list[str] = []
    if not test_impact_plan:
        return {
            "ready": True,
            "blocked_reasons": [],
            "warnings": ["No test impact plan supplied; incremental test scope was not checked."],
            "required_commands": [],
            "matched_commands": [],
        }
    plan, load_errors = load_plan(repo, test_impact_plan)
    blocked.extend(load_errors)
    if not plan:
        return {
            "ready": False,
            "blocked_reasons": blocked,
            "warnings": warnings,
            "required_commands": [],
            "matched_commands": [],
        }
    if plan.get("schema") != SCHEMA:
        blocked.append(f"Test impact plan schema must be {SCHEMA}.")
    if plan.get("status") == "template":
        blocked.append("Test impact plan is still a starter template; generate it from changed files before completion.")
    elif plan.get("status") not in {"ready", None}:
        blocked.append("Test impact plan status must be ready before completion.")
    commands = [item for item in plan.get("commands", []) if isinstance(item, dict)]
    required = [item for item in commands if item.get("required", True)]
    if not commands and not plan.get("ignored_changes"):
        blocked.append("Test impact plan must include required commands or explicit ignored_changes.")
    evidence_entries: list[dict] = []
    if required:
        evidence_path = resolve_repo_path(repo, unit_test_evidence)
        if not evidence_path or not evidence_path.exists():
            blocked.append("Required test impact commands need --unit-test-evidence JSON.")
        else:
            evidence_blocked: list[str] = []
            evidence_text = evidence_path.read_text(encoding="utf-8", errors="replace")
            evidence_entries = coverage_gate.validate_command_evidence(evidence_text, "Unit test", evidence_blocked)
            blocked.extend(evidence_blocked)
    matched: list[str] = []
    evidence_by_command = {
        normalize_command(str(entry.get("command", ""))): entry
        for entry in evidence_entries
        if str(entry.get("command", "")).strip()
    }
    for item in required:
        expected = normalize_command(str(item.get("command", "")))
        if not expected:
            blocked.append(f"Test impact command {item.get('id', '<unknown>')} is missing command.")
            continue
        match = evidence_by_command.get(expected)
        if not match:
            match = next(
                (entry for command, entry in evidence_by_command.items() if expected in command or command in expected),
                None,
            )
        if not match:
            blocked.append(f"Required test impact command was not found in unit evidence: {item.get('id')} {expected}")
            continue
        matched.append(expected)
        if match.get("exit_code") != 0:
            blocked.append(f"Required test impact command did not pass: {item.get('id')} {expected}")
    if not required:
        warnings.append("Test impact plan has no required test commands; verify this is docs-only or explicitly non-code work.")
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "required_commands": [item.get("command", "") for item in required],
        "matched_commands": matched,
        "ignored_changes": plan.get("ignored_changes", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--changed-files", type=Path)
    parser.add_argument("--dependency-report", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate", dest="validate_plan", type=Path)
    parser.add_argument("--unit-test-evidence", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if args.validate_plan:
        result = validate(repo, args.validate_plan, args.unit_test_evidence)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print("Test impact plan: " + ("READY" if result["ready"] else "BLOCKED"))
            for reason in result["blocked_reasons"]:
                print(f"- {reason}")
            for warning in result["warnings"]:
                print(f"warning: {warning}")
        return 0 if result["ready"] else 2

    changed = parse_changed_files(resolve_repo_path(repo, args.changed_files))
    dependency_report = resolve_repo_path(repo, args.dependency_report)
    result = build_plan(repo, changed, dependency_report)
    if args.output:
        output = resolve_repo_path(repo, args.output)
        assert output is not None
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Test impact commands:")
        for command in result["commands"]:
            print(f"- {command['id']}: {command['command']} ({command['reason']})")
        if not result["commands"]:
            print("- none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
