#!/usr/bin/env python3
"""Environment doctor for e2e-dev-harness adoption."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import install_hooks  # noqa: E402


MIN_PYTHON = (3, 10)


def check(check_id: str, status: str, severity: str, message: str, remediation: str = "") -> dict:
    return {
        "id": check_id,
        "status": status,
        "severity": severity,
        "message": message,
        "remediation": remediation,
    }


def executable(name: str) -> str:
    return shutil.which(name) or ""


def python_check() -> dict:
    version = sys.version_info
    text = f"Python {version.major}.{version.minor}.{version.micro}"
    if (version.major, version.minor) < MIN_PYTHON:
        return check(
            "python",
            "fail",
            "error",
            text + " is below the supported minimum.",
            "Install Python 3.10+ and rerun doctor.",
        )
    return check("python", "pass", "info", text)


def skill_layout_check() -> dict:
    required = [
        SKILL_DIR / "SKILL.md",
        SCRIPT_DIR / "e2e_dev_harness.py",
        SCRIPT_DIR / "phase_guard.py",
        SCRIPT_DIR / "harness_stop_guard.py",
        SCRIPT_DIR / "session_checkpoint.py",
        SKILL_DIR / "hooks" / "claude-code-settings.example.json",
        SKILL_DIR / "review-profiles" / "default.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return check(
            "skill-layout",
            "fail",
            "error",
            "Required skill files are missing: " + ", ".join(missing),
            "Reinstall or repair the e2e-dev-harness skill directory.",
        )
    return check("skill-layout", "pass", "info", f"Skill directory looks complete: {SKILL_DIR}")


def repo_shape_check(repo: Path) -> dict:
    markers = [".git", "pom.xml", "services", "docs"]
    present = [marker for marker in markers if (repo / marker).exists()]
    if not present:
        return check(
            "repo-shape",
            "warn",
            "warning",
            "No common project markers were found at repo root.",
            "Run doctor from the target repository root.",
        )
    return check("repo-shape", "pass", "info", "Detected project markers: " + ", ".join(present))


def pytest_check() -> dict:
    if executable("pytest"):
        return check("pytest", "pass", "info", "pytest is available.")
    return check(
        "pytest",
        "warn",
        "warning",
        "pytest is not on PATH.",
        "Install test dependencies before running harness self-tests.",
    )


def maven_check(repo: Path) -> dict:
    has_maven_project = (repo / "pom.xml").exists() or any(repo.glob("*/pom.xml"))
    mvn = executable("mvn") or executable("mvn.cmd")
    if mvn:
        return check("maven", "pass", "info", f"Maven is available: {mvn}")
    if has_maven_project:
        return check(
            "maven",
            "fail",
            "error",
            "Maven project detected but mvn/mvn.cmd is not on PATH.",
            "Install Maven or add mvn.cmd to PATH.",
        )
    return check("maven", "warn", "warning", "No Maven executable found; no pom.xml was detected.")


def gitnexus_check() -> dict:
    gitnexus = executable("gitnexus")
    if gitnexus:
        return check("gitnexus", "pass", "info", f"GitNexus CLI is available: {gitnexus}")
    return check(
        "gitnexus",
        "warn",
        "warning",
        "GitNexus CLI is not on PATH.",
        "Install GitNexus or plan an approved degradation path for critical/audited Java impact evidence.",
    )


def claude_hook_check(repo: Path) -> dict:
    project_target = repo / ".claude" / "settings.json"
    user_target = Path.home() / ".claude" / "settings.json"
    project = install_hooks.validate_config(project_target)
    user = install_hooks.validate_config(user_target)
    if project["ready"]:
        return check("claude-hooks", "pass", "info", f"Project Claude PreToolUse and Stop hooks are ready: {project_target}")
    if user["ready"]:
        return check(
            "claude-hooks",
            "pass",
            "info",
            f"User Claude PreToolUse and Stop hooks are ready: {user_target}",
            "Project hook is not ready; user-level hook is currently providing enforcement.",
        )
    if project_target.parent.exists():
        return check(
            "claude-hooks",
            "fail",
            "error",
            "Project Claude hook directory exists but no enforcing e2e-dev-harness PreToolUse/Stop hook pair is ready: "
            + "; ".join(project.get("blocked_reasons", [])),
            "Run install_hooks.py . --runtime claude --json and confirm PreToolUse includes Read/Grep/Glob/Bash and Stop calls harness_stop_guard.py.",
        )
    if user_target.parent.exists():
        return check(
            "claude-hooks",
        "warn",
        "warning",
        "User Claude hook config exists but is not an enforcing e2e-dev-harness PreToolUse/Stop hook pair.",
        "Install project-local hooks for this repository or use pre-code in runtimes without blocking hooks.",
        )
    return check(
        "claude-hooks",
        "warn",
        "warning",
        "No Claude hook configuration directory was found.",
        "Run install_hooks.py . --runtime claude --json when using Claude Code, or use pre-code in runtimes without blocking hooks.",
    )


def evaluate(repo: Path, strict: bool = False) -> dict:
    repo = repo.resolve()
    checks = [
        python_check(),
        skill_layout_check(),
        repo_shape_check(repo),
        pytest_check(),
        maven_check(repo),
        gitnexus_check(),
        claude_hook_check(repo),
    ]
    blockers = [
        item for item in checks
        if item["status"] == "fail" or (strict and item["status"] == "warn")
    ]
    return {
        "schema": "e2e-dev-harness.doctor.v1",
        "repo": str(repo),
        "ready": not blockers,
        "strict": strict,
        "checks": checks,
        "blocked_reasons": [item["message"] for item in blockers],
        "warnings": [item["message"] for item in checks if item["status"] == "warn"],
    }


def format_text(result: dict) -> str:
    lines = ["Harness doctor: " + ("READY" if result["ready"] else "BLOCKED")]
    for item in result["checks"]:
        marker = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}.get(item["status"], item["status"].upper())
        lines.append(f"- {marker} {item['id']}: {item['message']}")
        if item.get("remediation"):
            lines.append(f"  fix: {item['remediation']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--strict", action="store_true", help="Treat warnings as blockers.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = evaluate(args.repo, args.strict)
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else format_text(result))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
