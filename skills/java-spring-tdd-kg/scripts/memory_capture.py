#!/usr/bin/env python3
"""Initialize, scan, and append project memory for java-spring-tdd-kg."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


MEMORY_FILES = {
    "project": "project.md",
    "decision": "decisions.md",
    "service-boundary": "service-boundaries.md",
    "graph-finding": "graph-findings.md",
    "workflow-preference": "workflow-preferences.md",
}

TEMPLATES = {
    "project.md": """# Project Memory

## Summary

- Stack:
- Runtime:
- Repository shape:

## Glossary

| Term | Meaning |
| --- | --- |
|  |  |

## Conventions

- 
""",
    "decisions.md": """# Decisions Memory

Record user-approved or verified architecture/product decisions.

## Entries

""",
    "service-boundaries.md": """# Service Boundaries Memory

Record ownership, APIs, events, data, and integration boundaries.

## Entries

""",
    "graph-findings.md": """# Graph Findings Memory

Record verified Graphify/GitNexus findings that are likely to be reused.

## Entries

""",
    "workflow-preferences.md": """# Workflow Preferences Memory

Record team preferences for clarification, TDD, review, and verification.

## Entries

""",
}


def memory_dir(repo: Path) -> Path:
    return repo / "memory"


def graphify_memory_dir(repo: Path) -> Path:
    return repo / "graphify-out" / "memory"


def init_memory(repo: Path) -> dict:
    mem = memory_dir(repo)
    mem.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    existing: list[str] = []
    for filename, template in TEMPLATES.items():
        path = mem / filename
        if path.exists():
            existing.append(str(path.relative_to(repo)))
            continue
        path.write_text(template, encoding="utf-8")
        created.append(str(path.relative_to(repo)))
    return {"created": created, "existing": existing}


def scan_memory(repo: Path) -> dict:
    mem = memory_dir(repo)
    files = {}
    missing = []
    for filename in TEMPLATES:
        path = mem / filename
        if path.exists():
            stat = path.stat()
            files[filename] = {
                "path": str(path.relative_to(repo)),
                "bytes": stat.st_size,
                "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
        else:
            missing.append(str(Path("memory") / filename))

    graph_mem = graphify_memory_dir(repo)
    graph_files = []
    if graph_mem.exists():
        graph_files = [
            str(path.relative_to(repo))
            for path in sorted(graph_mem.rglob("*"))
            if path.is_file()
        ]

    return {
        "memory_dir": str(mem.relative_to(repo)),
        "files": files,
        "missing": missing,
        "graphify_memory_dir": str(graph_mem.relative_to(repo)),
        "graphify_memory_files": graph_files[:50],
        "graphify_memory_count": len(graph_files),
        "recommendations": [
            "Run `memory_capture.py init .` if required memory files are missing.",
            "Read memory as context hints; current code, tests, and fresh graph output take precedence.",
            "Append only verified or user-approved facts.",
        ],
    }


def entry_type_to_file(entry_type: str) -> str:
    return MEMORY_FILES[entry_type]


def append_memory(repo: Path, entry_type: str, source: str, confidence: str, text: str) -> dict:
    mem = memory_dir(repo)
    mem.mkdir(parents=True, exist_ok=True)
    filename = entry_type_to_file(entry_type)
    path = mem / filename
    if not path.exists():
        path.write_text(TEMPLATES[filename], encoding="utf-8")

    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    entry = (
        f"\n### {timestamp}\n\n"
        f"- Type: {entry_type}\n"
        f"- Source: {source}\n"
        f"- Confidence: {confidence}\n"
        f"- Text: {text.strip()}\n"
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry)
    return {"path": str(path.relative_to(repo)), "entry": entry.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create memory files if missing.")
    init_parser.add_argument("repo", nargs="?", default=".", type=Path)
    init_parser.add_argument("--json", action="store_true")

    scan_parser = subparsers.add_parser("scan", help="Summarize memory files.")
    scan_parser.add_argument("repo", nargs="?", default=".", type=Path)
    scan_parser.add_argument("--json", action="store_true")
    scan_parser.add_argument(
        "--mode",
        choices=["auto", "strict", "optional", "off"],
        default=os.environ.get("JAVA_SPRING_TDD_KG_MEMORY_MODE", "auto"),
    )

    add_parser = subparsers.add_parser("add", help="Append a verified memory entry.")
    add_parser.add_argument("repo", nargs="?", default=".", type=Path)
    add_parser.add_argument("--type", choices=sorted(MEMORY_FILES), required=True)
    add_parser.add_argument("--source", choices=["user-approved", "design", "graphify", "gitnexus", "test", "code"], required=True)
    add_parser.add_argument("--confidence", choices=["verified", "approved", "observed"], required=True)
    add_parser.add_argument("--text", required=True)
    add_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    repo = args.repo.resolve()
    if not repo.exists():
        print(f"Repo not found: {repo}", file=sys.stderr)
        return 2

    if args.command == "init":
        result = init_memory(repo)
        message = "Memory initialized."
        exit_code = 0
    elif args.command == "scan":
        if args.mode == "off":
            result = {"mode": args.mode, "enabled": False, "message": "Memory adapter disabled by policy."}
            message = result["message"]
            exit_code = 0
        else:
            result = scan_memory(repo)
            result["mode"] = args.mode
            result["enabled"] = True
            message = "Memory scan complete."
            exit_code = 2 if args.mode == "strict" and result["missing"] else 0
    else:
        result = append_memory(repo, args.type, args.source, args.confidence, args.text)
        message = "Memory entry appended."
        exit_code = 0

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(message)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
