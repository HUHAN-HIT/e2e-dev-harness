#!/usr/bin/env python3
"""Pre-action guard that blocks code writes outside the implementation phase."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


WRITE_TOOLS = {"write", "edit", "multiedit", "notebookedit"}
CODE_SUFFIXES = {
    ".java",
    ".kt",
    ".groovy",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".sql",
    ".xml",
    ".yml",
    ".yaml",
    ".properties",
    ".gradle",
}
CODE_FILENAMES = {"pom.xml", "build.gradle", "settings.gradle", "Dockerfile"}
ARTIFACT_PREFIXES = ("docs/agent-runs/",)
DOC_PREFIXES = ("docs/design/", "docs/requirements/", "docs/review-profiles/", ".e2e/")


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def normalize_tool(value: str) -> str:
    return value.strip().lower().replace("_", "").replace("-", "")


def posix_relative(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/").lstrip("/")


def is_code_path(repo: Path, path: Path) -> bool:
    relative = posix_relative(repo, path)
    if relative.startswith(ARTIFACT_PREFIXES):
        return False
    if relative.startswith(DOC_PREFIXES):
        return False
    name = path.name
    return name in CODE_FILENAMES or path.suffix in CODE_SUFFIXES


def discover_lock(repo: Path, explicit: Path | None = None, run_dir: Path | None = None) -> Path | None:
    if explicit:
        return explicit if explicit.is_absolute() else repo / explicit
    if run_dir:
        base = run_dir if run_dir.is_absolute() else repo / run_dir
        return base / ".phase-lock"
    runs = repo / "docs" / "agent-runs"
    if not runs.exists():
        return None
    matches = sorted(runs.glob("*/.phase-lock"), key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def parse_hook_input(text: str) -> tuple[str, list[str]]:
    if not text.strip():
        return "", []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return "", []
    tool = str(data.get("tool_name") or data.get("tool") or "")
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else data
    paths: list[str] = []
    for key in ("file_path", "path", "target", "notebook_path"):
        value = tool_input.get(key) if isinstance(tool_input, dict) else None
        if value:
            paths.append(str(value))
    return tool, paths


def validate_action(
    repo: Path,
    tool: str,
    paths: list[Path],
    lock_path: Path | None = None,
    run_dir: Path | None = None,
) -> dict:
    repo = repo.resolve()
    normalized = normalize_tool(tool)
    code_paths = [path for path in paths if is_code_path(repo, path if path.is_absolute() else repo / path)]
    if normalized not in WRITE_TOOLS or not code_paths:
        return {"ready": True, "blocked_reasons": [], "warnings": [], "code_paths": [str(path) for path in code_paths]}
    lock = discover_lock(repo, lock_path, run_dir)
    if not lock or not lock.exists():
        return {
            "ready": False,
            "blocked_reasons": ["Code write blocked: phase lock not found for active agent run."],
            "warnings": [],
            "code_paths": [str(path) for path in code_paths],
        }
    data = load_json(lock)
    lifecycle = str(data.get("lifecycle", ""))
    allowed = set(data.get("allowed_code_write_lifecycles") or ["IMPLEMENTED"])
    if lifecycle not in allowed:
        return {
            "ready": False,
            "blocked_reasons": [
                f"Code write blocked: lifecycle {lifecycle or '<missing>'} is not in allowed phases: "
                + ", ".join(sorted(allowed))
            ],
            "warnings": [],
            "phase_lock": str(lock),
            "lifecycle": lifecycle,
            "code_paths": [str(path) for path in code_paths],
        }
    return {
        "ready": True,
        "blocked_reasons": [],
        "warnings": [],
        "phase_lock": str(lock),
        "lifecycle": lifecycle,
        "code_paths": [str(path) for path in code_paths],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--tool", default="")
    parser.add_argument("--path", action="append", type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--hook-input", help="JSON hook input, or '-' for stdin.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    tool = args.tool
    paths = list(args.path or [])
    if args.hook_input:
        hook_text = sys.stdin.read() if args.hook_input == "-" else args.hook_input
        hook_tool, hook_paths = parse_hook_input(hook_text)
        tool = tool or hook_tool
        paths.extend(Path(path) for path in hook_paths)
    result = validate_action(args.repo, tool, paths, args.lock, args.run_dir)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Phase guard: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
