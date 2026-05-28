#!/usr/bin/env python3
"""Validate agent handoff artifacts before passing work between agents."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


REQUIRED_FIELDS = {
    "agent": "agent",
    "agent_id": "agent_id",
    "status": "status",
    "inputs": "inputs",
    "outputs": "outputs",
    "input_hashes": "input_hashes",
    "output_hashes": "output_hashes",
    "consumed_by": "consumed_by",
    "open_questions": "open_questions",
}
PASS_STATUSES = {"ready", "verified", "complete", "completed", "approved", "clear"}
BLOCK_STATUSES = {"draft", "open", "in-progress", "in_progress", "blocked"}
NONE_VALUES = {"", "-", "none", "n/a", "na", "no", "no open questions"}
PLACEHOLDER_RE = re.compile(r"^\s*(<[^>]+>|\[[^\]]+\]|todo|tbd|unknown|draft|placeholder)\s*$", re.IGNORECASE)
TEMPLATE_BODY_RE = re.compile(r"\b(todo|tbd|fill in|draft guidance|not ready|placeholder)\b|<[^>]+>", re.IGNORECASE)
SHA_RE = re.compile(r"\bsha256:[0-9a-f]{64}\b", re.IGNORECASE)
HEADING_RE = re.compile(r"^\s{0,3}##\s+(?P<title>.+?)\s*$")
REQUIRED_READY_BODY_SECTIONS = {
    "summary": "Summary",
    "facts used": "Facts Used",
    "decisions made": "Decisions Made",
    "downstream assumptions": "Downstream Assumptions",
    "verification evidence": "Verification Evidence",
}


def normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def normalize_value(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def is_placeholder(value: str) -> bool:
    return not value.strip() or bool(PLACEHOLDER_RE.match(value.strip()))


def parse_scalar(value: str) -> str | list[str]:
    text = value.strip()
    if text == "[]":
        return []
    return text


def parse_frontmatter(path: Path) -> tuple[dict[str, str | list[str]], str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    fields: dict[str, str | list[str]] = {}
    current_list: str | None = None
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
        if line.startswith("  - ") and current_list:
            value = line[4:].strip()
            existing = fields.setdefault(current_list, [])
            if isinstance(existing, list):
                existing.append(value)
            continue
        match = re.match(r"^\s*([A-Za-z][A-Za-z0-9 _-]*):\s*(.*?)\s*$", line)
        if not match:
            current_list = None
            continue
        key = normalize_key(match.group(1))
        value = parse_scalar(match.group(2))
        fields[key] = value
        current_list = key if value == "" else None
        if value == "":
            fields[key] = []
    body = "\n".join(lines[end_index + 1 :]) if end_index is not None else text
    return fields, body


def as_list(value: str | list[str] | None) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def as_text(value: str | list[str] | None) -> str:
    if isinstance(value, list):
        return "\n".join(value)
    return str(value or "")


def open_questions_section(body: str) -> str:
    lines = body.splitlines()
    capturing = False
    captured: list[str] = []
    for line in lines:
        match = HEADING_RE.match(line)
        if match:
            title = match.group("title").strip().lower()
            if capturing:
                break
            capturing = title == "open questions"
            continue
        if capturing:
            captured.append(line)
    return "\n".join(captured).strip()


def section_body(body: str, wanted_title: str) -> str:
    lines = body.splitlines()
    capturing = False
    captured: list[str] = []
    wanted = wanted_title.strip().lower()
    for line in lines:
        match = HEADING_RE.match(line)
        if match:
            title = match.group("title").strip().lower()
            if capturing:
                break
            capturing = title == wanted
            continue
        if capturing:
            captured.append(line)
    return "\n".join(captured).strip()


def section_is_meaningful(text: str) -> bool:
    cleaned = "\n".join(line.strip(" -*\t") for line in text.splitlines()).strip()
    if not cleaned:
        return False
    return TEMPLATE_BODY_RE.search(cleaned) is None


def is_no_open_questions(value: str) -> bool:
    text = normalize_value(value.strip())
    if text in NONE_VALUES:
        return True
    return text.replace("\n", " ").strip() in NONE_VALUES


def explicit_files(repo: Path, inputs: list[Path] | None) -> list[Path]:
    files: list[Path] = []
    for item in inputs or []:
        resolved = item if item.is_absolute() else repo / item
        if resolved.is_file():
            files.append(resolved)
        elif resolved.is_dir():
            files.extend(sorted(resolved.glob("*.md")))
    return sorted(dict.fromkeys(files))


def explicit_partial_files(repo: Path, inputs: list[Path] | None) -> list[Path]:
    files: list[Path] = []
    for item in inputs or []:
        resolved = item if item.is_absolute() else repo / item
        if resolved.is_file() and resolved.name.endswith(".partial"):
            files.append(resolved)
        elif resolved.is_dir():
            files.extend(sorted(resolved.glob("*.partial")))
            files.extend(sorted(resolved.glob("*.md.partial")))
    return sorted(dict.fromkeys(files))


def agent_run_dir_from_path(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    resolved = path if path.is_absolute() else repo / path
    parts = resolved.resolve().parts
    for index in range(len(parts) - 2):
        if parts[index] == "docs" and parts[index + 1] == "agent-runs":
            return Path(*parts[: index + 3])
    return None


def infer_agent_run_dir(repo: Path, anchor_paths: list[Path | None] | None) -> Path | None:
    for path in anchor_paths or []:
        run_dir = agent_run_dir_from_path(repo, path)
        if run_dir:
            return run_dir
    return None


def discovered_files(repo: Path, agent_run_dir: Path | None) -> list[Path]:
    if not agent_run_dir:
        return []
    run_dir = agent_run_dir if agent_run_dir.is_absolute() else repo / agent_run_dir
    candidates: list[Path] = []
    handoffs = run_dir / "handoffs"
    if handoffs.exists():
        candidates.extend(sorted(handoffs.glob("*.md")))
    service_plans = run_dir / "service-plans"
    if service_plans.exists():
        candidates.extend(sorted(service_plans.glob("*/code-agent.md")))
        candidates.extend(sorted(service_plans.glob("*/implementation-plan.md")))
    return sorted(dict.fromkeys(candidates))


def discovered_partial_files(repo: Path, agent_run_dir: Path | None) -> list[Path]:
    if not agent_run_dir:
        return []
    run_dir = agent_run_dir if agent_run_dir.is_absolute() else repo / agent_run_dir
    candidates: list[Path] = []
    handoffs = run_dir / "handoffs"
    if handoffs.exists():
        candidates.extend(sorted(handoffs.glob("*.partial")))
        candidates.extend(sorted(handoffs.glob("*.md.partial")))
    service_plans = run_dir / "service-plans"
    if service_plans.exists():
        candidates.extend(sorted(service_plans.glob("*/*.partial")))
        candidates.extend(sorted(service_plans.glob("*.md.partial")))
    return sorted(dict.fromkeys(candidates))


def marker_path(path: Path) -> Path:
    return path.with_suffix(".ready.json")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def validate_ready_marker(path: Path, agent_id: str, status: str) -> list[str]:
    blocked: list[str] = []
    marker = marker_path(path)
    if status not in PASS_STATUSES:
        return blocked
    if not marker.exists():
        blocked.append(f"Handoff {path} is ready but missing ready marker: {marker.name}")
        return blocked
    marker_fields = read_json(marker)
    if not marker_fields:
        blocked.append(f"Handoff ready marker is missing or invalid JSON: {marker}")
        return blocked
    marker_status = normalize_value(str(marker_fields.get("status", "")))
    if marker_status not in PASS_STATUSES:
        blocked.append(f"Handoff ready marker {marker} status is not ready/verified: {marker_fields.get('status')}")
    marker_producer = str(marker_fields.get("producer_agent", "")).strip()
    if marker_producer and marker_producer != agent_id:
        blocked.append(f"Handoff ready marker {marker} producer_agent does not match agent_id.")
    marker_target = str(marker_fields.get("path", "")).strip()
    if not marker_target:
        blocked.append(f"Handoff ready marker {marker} must include path.")
    else:
        target = Path(marker_target)
        if target.name != path.name:
            blocked.append(f"Handoff ready marker {marker} path does not point to this handoff.")
    expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    marker_hash = str(marker_fields.get("sha256", "")).strip().lower()
    if marker_hash != expected_hash:
        blocked.append(f"Handoff ready marker {marker} sha256 does not match current handoff content.")
    return blocked


def validate_item(path: Path, fields: dict[str, str | list[str]], body: str) -> tuple[dict, list[str]]:
    blocked: list[str] = []
    missing = [label for key, label in REQUIRED_FIELDS.items() if key not in fields]
    if missing:
        blocked.append(f"Handoff {path} missing required fields: {', '.join(missing)}")

    agent_id = as_text(fields.get("agent_id")).strip()
    agent = as_text(fields.get("agent")).strip()
    status = normalize_value(as_text(fields.get("status")))
    if is_placeholder(agent_id):
        blocked.append(f"Handoff {path} has placeholder or missing agent id.")
    if is_placeholder(agent):
        blocked.append(f"Handoff {path} has placeholder or missing agent name.")
    if status in BLOCK_STATUSES:
        blocked.append(f"Handoff {path} is still {status}.")
    elif status and status not in PASS_STATUSES:
        blocked.append(f"Handoff {path} has unsupported status: {as_text(fields.get('status'))}")
    blocked.extend(validate_ready_marker(path, agent_id, status))

    for key in ("inputs", "outputs", "input_hashes", "output_hashes", "consumed_by"):
        values = as_list(fields.get(key))
        if not values:
            blocked.append(f"Handoff {path} must declare non-empty {key}.")
    for key in ("input_hashes", "output_hashes"):
        for value in as_list(fields.get(key)):
            if not SHA_RE.search(value):
                blocked.append(f"Handoff {path} {key} entry must include sha256:<64-hex>: {value}")

    open_questions = as_text(fields.get("open_questions"))
    body_open_questions = open_questions_section(body)
    if not is_no_open_questions(open_questions):
        blocked.append(f"Handoff {path} must declare open_questions: None before downstream consumption.")
    if body_open_questions and not is_no_open_questions(body_open_questions):
        blocked.append(f"Handoff {path} Open Questions section is not closed.")
    if status in PASS_STATUSES:
        for section_key, section_label in REQUIRED_READY_BODY_SECTIONS.items():
            text = section_body(body, section_key)
            if not section_is_meaningful(text):
                blocked.append(f"Handoff {path} ready body section is empty or template-only: {section_label}.")

    item = {
        "path": str(path),
        "agent": agent,
        "agent_id": agent_id,
        "status": status,
        "inputs": as_list(fields.get("inputs")),
        "outputs": as_list(fields.get("outputs")),
        "consumed_by": as_list(fields.get("consumed_by")),
    }
    return item, blocked


def validate(
    repo: Path,
    handoff_dirs: list[Path] | None = None,
    anchor_paths: list[Path | None] | None = None,
    require_files: bool = False,
) -> dict:
    repo = repo.resolve()
    files = explicit_files(repo, handoff_dirs)
    partials = explicit_partial_files(repo, handoff_dirs)
    inferred_run_dir = infer_agent_run_dir(repo, list(handoff_dirs or []) + list(anchor_paths or []))
    if not handoff_dirs and inferred_run_dir:
        files = discovered_files(repo, inferred_run_dir)
        partials = discovered_partial_files(repo, inferred_run_dir)
    blocked: list[str] = []
    for partial in partials:
        blocked.append(f"Partial handoff exists and must not be consumed yet: {partial}")
    if require_files and not files:
        blocked.append("Required handoff artifacts are missing; populate handoffs/ or service-plans/ before completion.")
    items: list[dict] = []
    for path in files:
        fields, body = parse_frontmatter(path)
        item, item_blocked = validate_item(path, fields, body)
        items.append(item)
        blocked.extend(item_blocked)
    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": [],
        "scanned_files": [str(path) for path in files],
        "partial_files": [str(path) for path in partials],
        "inferred_agent_run_dir": str(inferred_run_dir) if inferred_run_dir else None,
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--handoff-dir", action="append", type=Path)
    parser.add_argument("--anchor-path", action="append", type=Path)
    parser.add_argument("--require-handoffs", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(args.repo, args.handoff_dir, args.anchor_path, args.require_handoffs)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Handoff gate: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
