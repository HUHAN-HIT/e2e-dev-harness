#!/usr/bin/env python3
"""Plan a knowledge graph refresh for Java/Spring/Maven repositories."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import SKIP_DIRS, parse_modules, posix, split_command  # noqa: E402


DOC_SUFFIXES = {".md", ".adoc", ".rst", ".pdf", ".docx", ".pptx", ".drawio", ".puml", ".plantuml", ".mmd", ".png", ".jpg", ".jpeg"}
GRAPHIFY_GRAPH = Path("graphify-out") / "graph.json"


def walk_files(root: Path):
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        base = Path(current)
        for name in files:
            yield base / name


def contains_text(path: Path, needle: str) -> bool:
    try:
        return needle in path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def detect(repo: Path) -> dict:
    files = list(walk_files(repo))
    poms = sorted(posix(path.relative_to(repo)) for path in files if path.name == "pom.xml")
    root_modules = [posix(module) for module in parse_modules(repo / "pom.xml")] if (repo / "pom.xml").exists() else []
    spring_entrypoints = sorted(
        posix(path.relative_to(repo))
        for path in files
        if path.suffix == ".java"
        and (
            contains_text(path, "@Configuration")
            or contains_text(path, "@EnableWebMvc")
            or contains_text(path, "WebApplicationInitializer")
        )
    )
    spring_configs = sorted(
        posix(path.relative_to(repo))
        for path in files
        if path.name.startswith("application") and path.suffix in {".yml", ".yaml", ".properties"}
    )
    docs = sorted(posix(path.relative_to(repo)) for path in files if path.suffix.lower() in DOC_SUFFIXES)

    service_candidates = set()
    for app in spring_entrypoints:
        parts = Path(app).parts
        if "services" in parts:
            index = parts.index("services")
            if len(parts) > index + 1:
                service_candidates.add(posix(Path(*parts[: index + 2])))
        elif len(root_modules) == 1:
            service_candidates.add(root_modules[0])
        else:
            service_candidates.add(".")

    for module in root_modules:
        module_path = repo / module
        if (module_path / "src" / "main").exists() and (module_path / "pom.xml").exists():
            service_candidates.add(module)

    return {
        "poms": poms,
        "root_modules": root_modules,
        "spring_entrypoints": spring_entrypoints,
        "spring_configs": spring_configs,
        "design_docs_or_media_count": len(docs),
        "design_docs_or_media_sample": docs[:20],
        "graphify_graph": posix(GRAPHIFY_GRAPH),
        "graphify_graph_exists": (repo / GRAPHIFY_GRAPH).exists(),
        "service_candidates": sorted(service_candidates),
        "multi_service": len(service_candidates) > 1,
    }


def choose_tools(mode: str, facts: dict) -> list[str]:
    if mode in {"gitnexus", "graphify"}:
        return [mode]
    if mode == "both":
        return ["gitnexus", "graphify"]

    tools: list[str] = []
    has_java_code = bool(facts["poms"] or facts["spring_entrypoints"])
    has_docs = facts["design_docs_or_media_count"] > 0
    if has_java_code:
        tools.append("gitnexus")
    if has_docs or (facts["multi_service"] and len(facts["root_modules"]) > 1):
        tools.append("graphify")
    return tools


def run_command(command: str, repo: Path) -> dict:
    try:
        args = split_command(command)
    except ValueError as error:
        return {
            "command": command,
            "exit_code": 2,
            "stdout_tail": "",
            "stderr_tail": str(error),
        }
    try:
        completed = subprocess.run(args, cwd=repo, shell=False, text=True, capture_output=True)
    except FileNotFoundError as error:
        return {
            "command": command,
            "exit_code": 127,
            "stdout_tail": "",
            "stderr_tail": str(error),
        }
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def suggested_commands(selected: list[str], facts: dict, availability: dict) -> dict:
    suggestions = {
        "gitnexus": "gitnexus analyze .",
        "graphify": (
            "graphify update ."
            if facts["graphify_graph_exists"]
            else "graphify extract ."
        ),
    }
    caution = {
        "gitnexus": None,
        "graphify": (
            None
            if facts["graphify_graph_exists"]
            else "Initial graphify extract may require an LLM backend/API key; use a repo-specific command if one exists."
        ),
    }
    return {
        tool: {
            "command": suggestions[tool],
            "available": bool(availability.get(tool)),
            "caution": caution[tool],
        }
        for tool in selected
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--mode", choices=["auto", "gitnexus", "graphify", "both"], default="auto")
    parser.add_argument("--execute", action="store_true", help="Run provided graph commands.")
    parser.add_argument("--use-suggested-commands", action="store_true", help="With --execute, run safe suggested commands when explicit commands are omitted.")
    parser.add_argument("--gitnexus-command", help="Repo-specific command that refreshes GitNexus.")
    parser.add_argument("--graphify-command", help="Repo-specific command that refreshes Graphify.")
    parser.add_argument("--status-file", type=Path, help="Optional JSON status output path.")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not repo.exists():
        print(f"Repo not found: {repo}", file=sys.stderr)
        return 2

    facts = detect(repo)
    selected = choose_tools(args.mode, facts)
    availability = {"gitnexus": shutil.which("gitnexus"), "graphify": shutil.which("graphify")}
    configured_commands = {
        "gitnexus": args.gitnexus_command,
        "graphify": args.graphify_command,
    }
    suggestions = suggested_commands(selected, facts, availability)

    result = {
        "repo": str(repo),
        "mode": args.mode,
        "detected": facts,
        "selected_tools": selected,
        "available_tools": availability,
        "commands": configured_commands,
        "suggested_commands": suggestions,
        "executed": [],
        "notes": [
            "Inspect --help or repo docs before inventing Graphify/GitNexus flags.",
            "Graphify is now supported directly: update existing graphs with `graphify update .`; create missing graphs with explicit extraction.",
            "Implementation should not begin until this refresh is recorded in the design note.",
        ],
    }

    if args.execute:
        for tool in selected:
            command = configured_commands.get(tool)
            if not command and args.use_suggested_commands:
                suggestion = suggestions.get(tool, {})
                command = suggestion.get("command")
                if tool == "graphify" and not facts["graphify_graph_exists"] and not args.graphify_command:
                    result["executed"].append({
                        "tool": tool,
                        "skipped": True,
                        "reason": "Refusing to run initial `graphify extract .` without an explicit --graphify-command because it may require LLM/API credentials.",
                    })
                    continue
            if command:
                result["executed"].append(run_command(command, repo))
            else:
                result["executed"].append({
                    "tool": tool,
                    "skipped": True,
                    "reason": f"No --{tool}-command was provided.",
                })

    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.status_file:
        args.status_file.parent.mkdir(parents=True, exist_ok=True)
        args.status_file.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
