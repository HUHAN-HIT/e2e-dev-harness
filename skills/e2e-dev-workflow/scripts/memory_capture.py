#!/usr/bin/env python3
"""Initialize, scan, and append project memory for e2e-dev-workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
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

VALID_TYPES = set(MEMORY_FILES)
VALID_SOURCES = {"user-approved", "design", "graphify", "gitnexus", "test", "code"}
VALID_CONFIDENCE = {"verified", "approved", "observed"}
HANDLED_STATUSES = {"accepted", "approved", "verified", "rejected", "deferred", "skipped"}
PROMOTE_STATUSES = {"accepted", "approved", "verified"}
PHASE_FILES = {
    "requirements": ["project.md", "workflow-preferences.md", "decisions.md"],
    "use-case": ["project.md", "service-boundaries.md", "graph-findings.md", "decisions.md"],
    "test": ["workflow-preferences.md", "decisions.md", "graph-findings.md", "service-boundaries.md"],
    "code": ["service-boundaries.md", "graph-findings.md", "decisions.md", "workflow-preferences.md"],
    "review": ["decisions.md", "service-boundaries.md", "graph-findings.md", "workflow-preferences.md"],
}
TODO_RE = re.compile(r"\b(todo|tbd|fixme|unresolved|pending)\b|待确认|未确认|未完成", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"\b[A-Za-z]:\\(?:Users|Documents|tmp|Temp|Program Files)|(?:^|\s)(?:/Users/|/home/|~/)", re.IGNORECASE)
SECRET_RE = re.compile(r"\b(api[_-]?key|secret|token|password|credential)\b\s*[:=]", re.IGNORECASE)
ENTRY_LINE_RE = re.compile(r"^\s*-\s*([A-Za-z_-]+):\s*(.*)\s*$")
ENTRY_HEADING_RE = re.compile(r"^\s*###\s+(.+?)\s*$")

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


def parse_entries(text: str, path: str | None = None) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        heading = ENTRY_HEADING_RE.match(line)
        if heading:
            if current and any(key in current for key in ("type", "source", "confidence", "status", "text")):
                entries.append(current)
            current = {"id": heading.group(1).strip()}
            if path:
                current["path"] = path
            continue
        if current is None:
            continue
        item = ENTRY_LINE_RE.match(line)
        if item:
            key = item.group(1).strip().lower().replace("-", "_")
            current[key] = item.group(2).strip()
    if current and any(key in current for key in ("type", "source", "confidence", "status", "text")):
        entries.append(current)
    return entries


def validate_entry(entry: dict[str, str], blocked: list[str], label: str, require_status: bool = False) -> None:
    for key in ("type", "source", "confidence", "text"):
        if not entry.get(key, "").strip():
            blocked.append(f"{label} missing {key}.")
    if require_status and not entry.get("status", "").strip():
        blocked.append(f"{label} missing status.")
    entry_type = entry.get("type", "")
    if entry_type and entry_type not in VALID_TYPES:
        blocked.append(f"{label} has unsupported type: {entry_type}")
    source = entry.get("source", "")
    if source and source not in VALID_SOURCES:
        blocked.append(f"{label} has unsupported source: {source}")
    confidence = entry.get("confidence", "")
    if confidence and confidence not in VALID_CONFIDENCE:
        blocked.append(f"{label} has unsupported confidence: {confidence}")


def validate_memory(repo: Path) -> dict:
    repo = repo.resolve()
    blocked: list[str] = []
    warnings: list[str] = []
    scan = scan_memory(repo)
    blocked.extend(f"Required memory file missing: {path}" for path in scan["missing"])

    seen_text: dict[str, str] = {}
    entries_count = 0
    for filename in TEMPLATES:
        path = memory_dir(repo) / filename
        if not path.exists():
            continue
        relative = str(path.relative_to(repo)).replace("\\", "/")
        text = path.read_text(encoding="utf-8", errors="replace")
        if TODO_RE.search(text):
            blocked.append(f"Memory file contains unresolved marker: {relative}")
        if LOCAL_PATH_RE.search(text):
            blocked.append(f"Memory file contains local path: {relative}")
        if SECRET_RE.search(text):
            blocked.append(f"Memory file may contain a secret or credential: {relative}")
        entries = parse_entries(text, relative)
        entries_count += len(entries)
        for entry in entries:
            label = f"{relative} entry {entry.get('id', '<unknown>')}"
            validate_entry(entry, blocked, label)
            normalized = " ".join(entry.get("text", "").lower().split())
            if normalized:
                if normalized in seen_text:
                    blocked.append(f"Duplicate memory text in {label}; first seen in {seen_text[normalized]}.")
                else:
                    seen_text[normalized] = label

    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "entries_count": entries_count,
        "scan": scan,
    }


def service_terms(service: str | None) -> list[str]:
    if not service:
        return []
    normalized = service.replace("\\", "/").strip("/")
    terms = {normalized, normalized.split("/")[-1]}
    return [term.lower() for term in terms if term]


def selected_snippet(filename: str, text: str, terms: list[str], max_chars: int) -> str:
    if terms and filename in {"service-boundaries.md", "graph-findings.md"}:
        lines = [line for line in text.splitlines() if any(term in line.lower() for term in terms)]
        return "\n".join(lines)[:max_chars].strip()
    stripped = text.strip()
    return stripped[:max_chars]


def select_memory(repo: Path, phase: str, service: str | None = None, max_chars: int = 4000) -> dict:
    repo = repo.resolve()
    filenames = PHASE_FILES[phase]
    terms = service_terms(service)
    files: list[str] = []
    snippets: list[dict[str, str]] = []
    for filename in filenames:
        path = memory_dir(repo) / filename
        if not path.exists():
            continue
        relative = str(path.relative_to(repo)).replace("\\", "/")
        files.append(relative)
        text = path.read_text(encoding="utf-8", errors="replace")
        snippet = selected_snippet(filename, text, terms, max_chars)
        if snippet:
            snippets.append({"path": relative, "text": snippet})
    return {
        "repo": str(repo),
        "phase": phase,
        "service": service,
        "files": files,
        "snippets": snippets,
    }


def validate_proposed_updates(path: Path | None) -> dict:
    blocked: list[str] = []
    warnings: list[str] = []
    if not path:
        return {"ready": True, "entries_count": 0, "blocked_reasons": blocked, "warnings": warnings}
    if not path.exists():
        blocked.append(f"Proposed memory updates file not found: {path}")
        return {"ready": False, "entries_count": 0, "blocked_reasons": blocked, "warnings": warnings}

    text = path.read_text(encoding="utf-8", errors="replace")
    entries = parse_entries(text, str(path))
    for entry in entries:
        label = f"memory update {entry.get('id', '<unknown>')}"
        validate_entry(entry, blocked, label, require_status=True)
        status = entry.get("status", "").strip().lower()
        if status and status not in HANDLED_STATUSES:
            blocked.append(f"{label} has unhandled status: {entry.get('status')}")
        if not status:
            blocked.append(f"{label} is unhandled; set status to accepted, rejected, deferred, or skipped.")
    return {
        "ready": not blocked,
        "entries_count": len(entries),
        "blocked_reasons": blocked,
        "warnings": warnings,
    }


def promote_memory_updates(repo: Path, proposed_path: Path, dry_run: bool = False) -> dict:
    repo = repo.resolve()
    proposed = proposed_path if proposed_path.is_absolute() else repo / proposed_path
    validation = validate_proposed_updates(proposed)
    if not validation["ready"]:
        return {
            "promoted_count": 0,
            "promoted": [],
            "skipped": [],
            "blocked_reasons": validation["blocked_reasons"],
            "dry_run": dry_run,
        }

    existing_texts: set[str] = set()
    for filename in TEMPLATES:
        path = memory_dir(repo) / filename
        if path.exists():
            for entry in parse_entries(path.read_text(encoding="utf-8", errors="replace")):
                normalized = " ".join(entry.get("text", "").lower().split())
                if normalized:
                    existing_texts.add(normalized)

    promoted: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    entries = parse_entries(proposed.read_text(encoding="utf-8", errors="replace"), str(proposed))
    for entry in entries:
        status = entry.get("status", "").strip().lower()
        if status not in PROMOTE_STATUSES:
            skipped.append({"id": entry.get("id", ""), "reason": f"status {status or '<missing>'} is not promotable"})
            continue
        normalized = " ".join(entry.get("text", "").lower().split())
        if normalized in existing_texts:
            skipped.append({"id": entry.get("id", ""), "reason": "duplicate text already exists"})
            continue
        if not dry_run:
            append_memory(repo, entry["type"], entry["source"], entry["confidence"], entry["text"])
        existing_texts.add(normalized)
        promoted.append({"id": entry.get("id", ""), "type": entry["type"], "text": entry["text"]})
    return {
        "promoted_count": len(promoted),
        "promoted": promoted,
        "skipped": skipped,
        "blocked_reasons": [],
        "dry_run": dry_run,
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
        default=os.environ.get("E2E_DEV_WORKFLOW_MEMORY_MODE", "auto"),
    )

    add_parser = subparsers.add_parser("add", help="Append a verified memory entry.")
    add_parser.add_argument("repo", nargs="?", default=".", type=Path)
    add_parser.add_argument("--type", choices=sorted(MEMORY_FILES), required=True)
    add_parser.add_argument("--source", choices=["user-approved", "design", "graphify", "gitnexus", "test", "code"], required=True)
    add_parser.add_argument("--confidence", choices=["verified", "approved", "observed"], required=True)
    add_parser.add_argument("--text", required=True)
    add_parser.add_argument("--json", action="store_true")

    validate_parser = subparsers.add_parser("validate", help="Validate memory quality and safety.")
    validate_parser.add_argument("repo", nargs="?", default=".", type=Path)
    validate_parser.add_argument("--json", action="store_true")

    select_parser = subparsers.add_parser("select", help="Select phase/service-scoped memory snippets.")
    select_parser.add_argument("repo", nargs="?", default=".", type=Path)
    select_parser.add_argument("--phase", choices=sorted(PHASE_FILES), required=True)
    select_parser.add_argument("--service")
    select_parser.add_argument("--max-chars", type=int, default=4000)
    select_parser.add_argument("--json", action="store_true")

    promote_parser = subparsers.add_parser("promote", help="Promote accepted proposed memory updates.")
    promote_parser.add_argument("repo", nargs="?", default=".", type=Path)
    promote_parser.add_argument("--from-file", required=True, type=Path)
    promote_parser.add_argument("--dry-run", action="store_true")
    promote_parser.add_argument("--json", action="store_true")

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
    elif args.command == "add":
        result = append_memory(repo, args.type, args.source, args.confidence, args.text)
        message = "Memory entry appended."
        exit_code = 0
    elif args.command == "validate":
        result = validate_memory(repo)
        message = "Memory validation " + ("passed." if result["ready"] else "blocked.")
        exit_code = 0 if result["ready"] else 2
    elif args.command == "select":
        result = select_memory(repo, args.phase, args.service, args.max_chars)
        message = "Memory selection complete."
        exit_code = 0
    else:
        result = promote_memory_updates(repo, args.from_file, args.dry_run)
        message = "Memory promotion complete."
        exit_code = 0 if not result["blocked_reasons"] else 2

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(message)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
