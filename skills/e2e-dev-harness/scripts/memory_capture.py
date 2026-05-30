#!/usr/bin/env python3
"""Initialize, scan, and append project memory for e2e-dev-harness."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import parse_modules, posix  # noqa: E402


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
SECRET_RE = re.compile(r"\b(api[_-]?key|secret|token|password|credential)\b\s*[:=]", re.IGNORECASE)
ENTRY_LINE_RE = re.compile(r"^\s*-\s*([A-Za-z_-]+):\s*(.*)\s*$")
ENTRY_HEADING_RE = re.compile(r"^\s*###\s+(.+?)\s*$")
TAG_RE = re.compile(r"^#[a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)*$")
OBSIDIAN_LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")

TODO_RE = re.compile(
    r"\b(todo|tbd|fixme|unresolved|pending)\b|"
    r"\u5f85\u786e\u8ba4|\u672a\u786e\u8ba4|\u672a\u5b8c\u6210",
    re.IGNORECASE,
)
LOCAL_PATH_RE = re.compile(r"\b[A-Za-z]:\\|(?:^|\s)(?:/Users/|/home/|/tmp/|~/)", re.IGNORECASE)


def env_default(primary: str, legacy: str, default: str) -> str:
    return os.environ.get(primary, os.environ.get(legacy, default))


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
    tag_index: dict[str, int] = {}
    link_index: dict[str, int] = {}
    for filename in TEMPLATES:
        path = mem / filename
        if path.exists():
            stat = path.stat()
            files[filename] = {
                "path": str(path.relative_to(repo)),
                "bytes": stat.st_size,
                "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
            for entry in parse_entries(path.read_text(encoding="utf-8", errors="replace")):
                for tag in parse_tags(entry.get("tags", "")):
                    tag_index[tag] = tag_index.get(tag, 0) + 1
                for link in parse_links(entry.get("links", "")):
                    link_index[link] = link_index.get(link, 0) + 1
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
        "tag_index": dict(sorted(tag_index.items())),
        "link_index": dict(sorted(link_index.items())),
        "recommendations": [
            "Run `memory_capture.py init .` if required memory files are missing.",
            "Read memory as context hints; current code, tests, and fresh graph output take precedence.",
            "Append only verified or user-approved facts.",
            "Use controlled Obsidian tags and links for memory navigation, not as a replacement for verified text.",
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


def _normalized_text(text: str) -> str:
    return " ".join(text.lower().split())


def _word_set(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    return set(words + cjk_chars)


def parse_tags(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\s,]+", value.strip()) if part.strip()]


def normalize_tag_for_write(tag: str) -> str:
    value = tag.strip().lower()
    return value if value.startswith("#") else f"#{value}"


def format_tags(tags: list[str] | None) -> str:
    if not tags:
        return ""
    seen: set[str] = set()
    normalized: list[str] = []
    for tag in tags:
        value = normalize_tag_for_write(tag)
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    return " ".join(normalized)


def parse_links(value: str) -> list[str]:
    return [match.strip() for match in OBSIDIAN_LINK_RE.findall(value) if match.strip()]


def normalize_link_for_write(link: str) -> str:
    value = link.strip()
    matches = parse_links(value)
    if matches and OBSIDIAN_LINK_RE.sub("", value).strip(" ,"):
        return value
    if matches:
        return matches[0]
    return value


def format_links(links: list[str] | None) -> str:
    if not links:
        return ""
    seen: set[str] = set()
    normalized: list[str] = []
    for link in links:
        target = normalize_link_for_write(link)
        if target and target not in seen:
            seen.add(target)
            normalized.append(f"[[{target}]]")
    return " ".join(normalized)


def service_tag_values(repo: Path | None) -> set[str]:
    if not repo:
        return set()
    values: set[str] = set()
    services_dir = repo / "services"
    if services_dir.exists():
        for child in services_dir.iterdir():
            if child.is_dir() and ((child / "pom.xml").exists() or (child / "src").exists()):
                normalized = posix(child.relative_to(repo))
                values.add(normalized)
                values.add(child.name)
    for module in parse_modules(repo / "pom.xml"):
        module_path = repo / module
        if module_path.exists():
            normalized = posix(module)
            values.add(normalized)
            values.add(Path(module).name)
    return {value.lower() for value in values}


def validate_tags(entry: dict[str, str], blocked: list[str], label: str, repo: Path | None = None) -> None:
    tags = parse_tags(entry.get("tags", ""))
    known_services = service_tag_values(repo)
    for tag in tags:
        if not TAG_RE.fullmatch(tag):
            blocked.append(
                f"{label} has invalid tag `{tag}`. Use lowercase Obsidian tags like #decision or #service/order-service."
            )
            continue
        if tag.startswith("#service/") and known_services:
            service_value = tag[len("#service/") :]
            if service_value not in known_services:
                blocked.append(f"{label} has service tag `{tag}` that does not match a discovered service.")


def validate_links(entry: dict[str, str], blocked: list[str], label: str) -> None:
    raw = entry.get("links", "").strip()
    if not raw:
        return
    links = parse_links(raw)
    remainder = OBSIDIAN_LINK_RE.sub("", raw).strip(" ,")
    if not links or remainder:
        blocked.append(f"{label} links must use plain Obsidian syntax like [[services/order-service]].")
    for link in links:
        if "|" in link:
            blocked.append(f"{label} link `{link}` must not use Obsidian aliases; link the canonical target directly.")
        if "://" in link:
            blocked.append(f"{label} link `{link}` must not be a URL.")
        if "\\" in link or link.startswith(("/", "~")) or ".." in link.split("/"):
            blocked.append(f"{label} link `{link}` must not be a local or relative filesystem path.")
        _check_text_safety(link, f"{label} link `{link}`", blocked=blocked, check_empty=True)


def _memory_text_index(repo: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    for filename in TEMPLATES:
        path = memory_dir(repo) / filename
        if not path.exists():
            continue
        relative = str(path.relative_to(repo)).replace("\\", "/")
        entries = parse_entries(path.read_text(encoding="utf-8", errors="replace"), relative)
        for entry in entries:
            normalized = _normalized_text(entry.get("text", ""))
            if normalized and normalized not in index:
                index[normalized] = f"{relative} entry {entry.get('id', '<unknown>')}"
    return index


def _check_text_safety(
    text: str,
    label: str,
    *,
    blocked: list[str],
    warnings: list[str] | None = None,
    check_empty: bool = True,
) -> None:
    if TODO_RE.search(text):
        blocked.append(f"{label} contains unresolved TODO/TBD marker.")
    if LOCAL_PATH_RE.search(text):
        blocked.append(f"{label} contains local path.")
    if SECRET_RE.search(text):
        blocked.append(f"{label} may contain a secret or credential.")
    if check_empty and not text.strip():
        blocked.append(f"{label} has empty text.")


def _check_fuzzy_duplicate(text: str, label: str, seen_text: dict[str, str], *, warnings: list[str]) -> None:
    normalized = _normalized_text(text)
    if not normalized:
        return
    if normalized in seen_text:
        return  # exact duplicate is handled by caller as blocked
    words = _word_set(normalized)
    if len(words) < 3:
        return
    for existing_normalized, existing_label in seen_text.items():
        existing_words = _word_set(existing_normalized)
        if len(existing_words) < 3:
            continue
        intersection = words & existing_words
        union = words | existing_words
        if union and len(intersection) / len(union) >= 0.8:
            warnings.append(f"{label} is semantically similar to {existing_label} (Jaccard >= 0.8).")


def validate_entry(
    entry: dict[str, str],
    blocked: list[str],
    label: str,
    require_status: bool = False,
    repo: Path | None = None,
) -> None:
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
    validate_tags(entry, blocked, label, repo)
    validate_links(entry, blocked, label)


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
        _check_text_safety(
            text,
            f"Memory file {relative}",
            blocked=blocked,
            warnings=warnings,
            check_empty=False,
        )
        entries = parse_entries(text, relative)
        entries_count += len(entries)
        for entry in entries:
            label = f"{relative} entry {entry.get('id', '<unknown>')}"
            validate_entry(entry, blocked, label, repo=repo)
            entry_text = entry.get("text", "")
            _check_text_safety(entry_text, label, blocked=blocked, warnings=warnings)
            normalized = _normalized_text(entry_text)
            if normalized:
                if normalized in seen_text:
                    blocked.append(f"Duplicate memory text in {label}; first seen in {seen_text[normalized]}.")
                else:
                    _check_fuzzy_duplicate(entry_text, label, seen_text, warnings=warnings)
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
    service_name = normalized.split("/")[-1]
    terms = {
        normalized,
        service_name,
        f"#service/{service_name}",
        f"[[{normalized}]]",
        f"[[{service_name}]]",
    }
    return [term.lower() for term in terms if term]


def render_entry(entry: dict[str, str]) -> str:
    lines = [f"### {entry.get('id', '<unknown>')}"]
    for key, title in (
        ("type", "Type"),
        ("source", "Source"),
        ("confidence", "Confidence"),
        ("status", "Status"),
        ("tags", "Tags"),
        ("links", "Links"),
        ("text", "Text"),
    ):
        value = entry.get(key, "").strip()
        if value:
            lines.append(f"- {title}: {value}")
    return "\n".join(lines)


def entry_matches_terms(entry: dict[str, str], terms: list[str]) -> bool:
    haystack = "\n".join(
        entry.get(key, "")
        for key in ("id", "type", "source", "confidence", "status", "tags", "links", "text")
    ).lower()
    return any(term in haystack for term in terms)


def selected_snippet(filename: str, text: str, terms: list[str], max_chars: int) -> str:
    if terms:
        entries = parse_entries(text)
        if entries:
            matched = [render_entry(entry) for entry in entries if entry_matches_terms(entry, terms)]
            return "\n\n".join(matched)[:max_chars].strip()
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


def validate_proposed_updates(path: Path | None, repo: Path | None = None) -> dict:
    blocked: list[str] = []
    warnings: list[str] = []
    if not path:
        return {"ready": True, "entries_count": 0, "blocked_reasons": blocked, "warnings": warnings}
    if not path.exists():
        blocked.append(f"Proposed memory updates file not found: {path}")
        return {"ready": False, "entries_count": 0, "blocked_reasons": blocked, "warnings": warnings}

    text = path.read_text(encoding="utf-8", errors="replace")
    _check_text_safety(text, f"proposed file {path}", blocked=blocked, warnings=warnings)
    entries = parse_entries(text, str(path))
    repo = repo.resolve() if repo else None
    existing_text = _memory_text_index(repo) if repo else {}
    seen_text: dict[str, str] = {}
    for entry in entries:
        label = f"memory update {entry.get('id', '<unknown>')}"
        validate_entry(entry, blocked, label, require_status=True, repo=repo)
        status = entry.get("status", "").strip().lower()
        if status and status not in HANDLED_STATUSES:
            blocked.append(f"{label} has unhandled status: {entry.get('status')}")
        if not status:
            blocked.append(f"{label} is unhandled; set status to accepted, rejected, deferred, or skipped.")
        entry_text = entry.get("text", "")
        _check_text_safety(entry_text, label, blocked=blocked, warnings=warnings)
        normalized = _normalized_text(entry_text)
        if normalized:
            if normalized in seen_text:
                blocked.append(f"{label} has duplicate text; first seen in {seen_text[normalized]}.")
            elif normalized in existing_text:
                blocked.append(f"{label} text already exists in {existing_text[normalized]}.")
            else:
                _check_fuzzy_duplicate(entry_text, label, {**existing_text, **seen_text}, warnings=warnings)
                seen_text[normalized] = label
    return {
        "ready": not blocked,
        "entries_count": len(entries),
        "blocked_reasons": blocked,
        "warnings": warnings,
    }


def promote_memory_updates(repo: Path, proposed_path: Path, dry_run: bool = False) -> dict:
    repo = repo.resolve()
    proposed = proposed_path if proposed_path.is_absolute() else repo / proposed_path
    validation = validate_proposed_updates(proposed, repo)
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
                normalized = _normalized_text(entry.get("text", ""))
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
        normalized = _normalized_text(entry.get("text", ""))
        if normalized in existing_texts:
            skipped.append({"id": entry.get("id", ""), "reason": "duplicate text already exists"})
            continue
        if not dry_run:
            append_memory(
                repo,
                entry["type"],
                entry["source"],
                entry["confidence"],
                entry["text"],
                tags=parse_tags(entry.get("tags", "")),
                links=parse_links(entry.get("links", "")),
            )
        existing_texts.add(normalized)
        promoted.append({
            "id": entry.get("id", ""),
            "type": entry["type"],
            "text": entry["text"],
            "tags": parse_tags(entry.get("tags", "")),
            "links": parse_links(entry.get("links", "")),
        })
    return {
        "promoted_count": len(promoted),
        "promoted": promoted,
        "skipped": skipped,
        "blocked_reasons": [],
        "dry_run": dry_run,
    }


def entry_type_to_file(entry_type: str) -> str:
    return MEMORY_FILES[entry_type]


def append_memory(
    repo: Path,
    entry_type: str,
    source: str,
    confidence: str,
    text: str,
    tags: list[str] | None = None,
    links: list[str] | None = None,
) -> dict:
    repo = repo.resolve()
    pre_blocked: list[str] = []
    pre_warnings: list[str] = []
    tag_text = format_tags(tags)
    link_text = format_links(links)
    validate_entry(
        {
            "type": entry_type,
            "source": source,
            "confidence": confidence,
            "text": text,
            "tags": tag_text,
            "links": link_text,
        },
        pre_blocked,
        "new memory entry",
        repo=repo,
    )
    _check_text_safety(text, "new memory entry", blocked=pre_blocked, warnings=pre_warnings)
    normalized = _normalized_text(text)
    existing_text = _memory_text_index(repo)
    if normalized and normalized in existing_text:
        pre_blocked.append(f"new memory entry is duplicate; first seen in {existing_text[normalized]}.")
    elif normalized:
        _check_fuzzy_duplicate(text, "new memory entry", existing_text, warnings=pre_warnings)
    if pre_blocked:
        return {
            "path": None,
            "entry": None,
            "blocked_reasons": pre_blocked,
            "warnings": pre_warnings,
        }

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
    )
    if tag_text:
        entry += f"- Tags: {tag_text}\n"
    if link_text:
        entry += f"- Links: {link_text}\n"
    entry += f"- Text: {text.strip()}\n"
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
        default=env_default("E2E_DEV_HARNESS_MEMORY_MODE", "E2E_DEV_WORKFLOW_MEMORY_MODE", "auto"),
    )

    add_parser = subparsers.add_parser("add", help="Append a verified memory entry.")
    add_parser.add_argument("repo", nargs="?", default=".", type=Path)
    add_parser.add_argument("--type", choices=sorted(MEMORY_FILES), required=True)
    add_parser.add_argument("--source", choices=["user-approved", "design", "graphify", "gitnexus", "test", "code"], required=True)
    add_parser.add_argument("--confidence", choices=["verified", "approved", "observed"], required=True)
    add_parser.add_argument("--text", required=True)
    add_parser.add_argument("--tag", action="append", help="Obsidian tag such as #decision or #service/sample-service; can be repeated.")
    add_parser.add_argument("--link", action="append", help="Obsidian link target such as services/sample-service or [[AC-1]]; can be repeated.")
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
        result = append_memory(repo, args.type, args.source, args.confidence, args.text, args.tag, args.link)
        blocked = result.get("blocked_reasons", [])
        message = "Memory append blocked." if blocked else "Memory entry appended."
        exit_code = 2 if blocked else 0
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
