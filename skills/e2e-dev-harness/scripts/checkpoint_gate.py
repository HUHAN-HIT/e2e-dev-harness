#!/usr/bin/env python3
"""Validate user confirmation checkpoints for intent and scenario alignment."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import posix  # noqa: E402


APPROVED_STATUSES = {"approved", "confirmed", "accepted", "continue", "go"}
DEFAULT_PHASES_BY_GATE = {
    "planning": ["clarify"],
    "implementation": ["clarify", "r1-design", "tdd-red"],
    "completion": ["clarify", "r1-design", "tdd-red", "implementation"],
}


def repo_path(repo: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    root = repo.resolve()
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"Checkpoint path resolves outside repository: {path}") from error
    return resolved


def parse_markdown_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*[-*]?\s*([A-Za-z][A-Za-z0-9 _-]{1,40})\s*:\s*(.+?)\s*$", line)
        if match:
            key = re.sub(r"[^a-z0-9]+", "_", match.group(1).strip().lower()).strip("_")
            fields[key] = match.group(2).strip()
    return fields


def load_confirmation(path: Path) -> tuple[dict[str, str], list[str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    except OSError as error:
        return {}, [f"Confirmation checkpoint could not be read: {path}: {error}"]
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            return {}, [f"Confirmation checkpoint is invalid JSON: {path}: {error}"]
        if not isinstance(data, dict):
            return {}, [f"Confirmation checkpoint must be an object: {path}"]
        return {str(key).lower().replace("-", "_"): str(value).strip() for key, value in data.items()}, []
    return parse_markdown_fields(text), []


def discover_confirmation_files(repo: Path, paths: list[Path] | None) -> tuple[list[Path], list[str]]:
    warnings: list[str] = []
    candidates: list[Path] = []
    if paths:
        for item in paths:
            resolved = repo_path(repo, item)
            if resolved and resolved.is_dir():
                candidates.extend(sorted(resolved.glob("*.md")))
                candidates.extend(sorted(resolved.glob("*.json")))
            elif resolved:
                candidates.append(resolved)
    else:
        root = repo / "docs" / "agent-runs"
        if root.exists():
            for directory in sorted(root.glob("*/confirmations")):
                candidates.extend(sorted(directory.glob("*.md")))
                candidates.extend(sorted(directory.glob("*.json")))
        else:
            warnings.append("No confirmation directory supplied and docs/agent-runs was not found.")
    unique = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique, warnings


def normalize_phase(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(" ", "-")


def status_approved(value: str) -> bool:
    normalized = normalize_phase(value)
    return normalized in APPROVED_STATUSES or "approved" in normalized or "confirmed" in normalized


def validate_item(path: Path, fields: dict[str, str]) -> tuple[dict, list[str]]:
    blocked: list[str] = []
    phase = normalize_phase(fields.get("phase", ""))
    status = fields.get("status", "")
    confirmed_by = fields.get("confirmed_by") or fields.get("approved_by") or fields.get("user")
    decision = fields.get("decision", "")
    if not phase:
        blocked.append(f"Confirmation checkpoint {path} must include Phase.")
    if not status_approved(status):
        blocked.append(f"Confirmation checkpoint {path} must have approved/confirmed Status.")
    if not confirmed_by:
        blocked.append(f"Confirmation checkpoint {path} must include Confirmed By.")
    if decision and normalize_phase(decision) in {"adjust", "revise", "stop", "blocked"}:
        blocked.append(f"Confirmation checkpoint {path} decision requires adjustment before continuing.")
    return {
        "path": posix(str(path)),
        "phase": phase,
        "status": status,
        "confirmed_by": confirmed_by or "",
        "decision": decision,
    }, blocked


def validate(
    repo: Path,
    confirmation_paths: list[Path] | None = None,
    required_phases: list[str] | None = None,
    mode: str = "required",
) -> dict:
    repo = repo.resolve()
    blocked: list[str] = []
    warnings: list[str] = []
    try:
        files, discovery_warnings = discover_confirmation_files(repo, confirmation_paths)
    except ValueError as error:
        return {"repo": str(repo), "ready": False, "blocked_reasons": [str(error)], "warnings": []}
    warnings.extend(discovery_warnings)
    items: list[dict] = []
    for path in files:
        if not path.exists():
            blocked.append(f"Confirmation checkpoint not found: {path}")
            continue
        fields, item_blocked = load_confirmation(path)
        if item_blocked:
            blocked.extend(item_blocked)
            continue
        item, item_blocked = validate_item(path, fields)
        items.append(item)
        blocked.extend(item_blocked)
    approved_phases = {item["phase"] for item in items if status_approved(item.get("status", ""))}
    missing = [normalize_phase(phase) for phase in required_phases or [] if normalize_phase(phase) not in approved_phases]
    if missing:
        blocked.append("Missing required confirmation checkpoints: " + ", ".join(missing))
    if mode == "advisory":
        warnings.extend(blocked)
        blocked = []
    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "required_phases": [normalize_phase(phase) for phase in required_phases or []],
        "confirmations": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--confirmation-dir", action="append", type=Path)
    parser.add_argument("--required-phase", action="append", default=[])
    parser.add_argument("--gate-phase", choices=sorted(DEFAULT_PHASES_BY_GATE))
    parser.add_argument("--mode", choices=["required", "advisory"], default="required")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    phases = args.required_phase or (DEFAULT_PHASES_BY_GATE.get(args.gate_phase or "", []))
    result = validate(args.repo, args.confirmation_dir, phases, args.mode)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Checkpoint gate: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
