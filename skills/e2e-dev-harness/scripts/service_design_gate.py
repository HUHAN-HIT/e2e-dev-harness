#!/usr/bin/env python3
"""Validate service-local design slices against the global design."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import clarification_gate  # noqa: E402
import coverage_gate  # noqa: E402
from common import posix  # noqa: E402


REQUIRED_SECTIONS = {
    "Service Scope",
    "Global Intent Summary",
    "Mapped Acceptance Criteria",
    "Runtime Path",
    "Service-local TDD Plan",
    "Dependency Boundary",
    "Test Impact",
}
AC_RE = re.compile(r"\bAC-\d+\b", re.IGNORECASE)
EMPTY_VALUES = {"", "n/a", "none", "-", "todo", "tbd"}


def resolve(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    return path if path.is_absolute() else repo / path


def section_titles(text: str) -> set[str]:
    return {
        match.group(1).strip()
        for match in re.finditer(r"^\s{0,3}##\s+(.+?)\s*$", text, re.MULTILINE)
    }


def section_body(text: str, title: str) -> str:
    return clarification_gate.section_text(text, [r"^" + re.escape(title.lower()) + r"$"]) or ""


def explicit_service_files(repo: Path, paths: list[Path] | None, service_design_dir: Path | None) -> list[Path]:
    files: list[Path] = []
    for path in paths or []:
        resolved = resolve(repo, path)
        if not resolved:
            continue
        if resolved.is_file():
            files.append(resolved)
        elif resolved.is_dir():
            files.extend(sorted(resolved.glob("*.md")))
    resolved_dir = resolve(repo, service_design_dir)
    if resolved_dir and resolved_dir.exists():
        files.extend(sorted(resolved_dir.glob("*.md")))
    return sorted(dict.fromkeys(files))


def mapped_acceptance_ids(text: str) -> set[str]:
    ids: set[str] = set()
    for row in coverage_gate.parse_markdown_tables(text):
        for key, value in row.items():
            if key in {"ac", "id", "acceptance", "global_requirement"}:
                ids.update(match.upper() for match in AC_RE.findall(value))
    ids.update(match.upper() for match in AC_RE.findall(text))
    return ids


def has_allowed_edit_scope(text: str) -> bool:
    scope = section_body(text, "Service Scope")
    for line in scope.splitlines():
        normalized = line.strip().lower().strip("-* ")
        if normalized in EMPTY_VALUES:
            continue
        if "allowed edit scope" in normalized:
            continue
        if "/" in normalized or "\\" in normalized:
            return True
    return False


def dependency_boundary_closed(text: str) -> bool:
    body = section_body(text, "Dependency Boundary")
    lowered = body.lower()
    if any(marker in lowered for marker in ("todo", "tbd", "<", "pending")):
        return False
    return "independent service change:" in lowered


def validate(repo: Path, global_design: Path | None, service_design_dir: Path | None = None, service_designs: list[Path] | None = None) -> dict:
    repo = repo.resolve()
    blocked: list[str] = []
    warnings: list[str] = []
    design_path = resolve(repo, global_design)
    global_acs: set[str] = set()
    if not design_path or not design_path.exists():
        blocked.append("Global design document is required for service design validation.")
    else:
        global_acs = {item["id"].upper() for item in clarification_gate.extract_acceptance_items(design_path)}
        if not global_acs:
            blocked.append("Global design has no acceptance criteria to map into service designs.")

    files = explicit_service_files(repo, service_designs, service_design_dir)
    if not files:
        blocked.append("No service design files found; expected service-designs/<service>.md.")

    mapped: dict[str, list[str]] = {}
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        titles = section_titles(text)
        missing = sorted(REQUIRED_SECTIONS - titles)
        if missing:
            blocked.append(f"Service design {posix(path.relative_to(repo))} missing sections: {', '.join(missing)}")
        ids = mapped_acceptance_ids(text)
        for ac_id in ids:
            mapped.setdefault(ac_id, []).append(posix(path.relative_to(repo)))
        unknown = sorted(ids - global_acs) if global_acs else []
        if unknown:
            blocked.append(f"Service design {posix(path.relative_to(repo))} maps unknown global AC ids: {', '.join(unknown)}")
        if not ids:
            blocked.append(f"Service design {posix(path.relative_to(repo))} must map at least one global AC.")
        if not has_allowed_edit_scope(text):
            blocked.append(f"Service design {posix(path.relative_to(repo))} must declare a concrete allowed edit scope.")
        if not dependency_boundary_closed(text):
            blocked.append(f"Service design {posix(path.relative_to(repo))} must close Dependency Boundary and state independent service change.")

    missing_global = sorted(ac_id for ac_id in global_acs if ac_id not in mapped)
    if missing_global:
        blocked.append("Global acceptance criteria not mapped to any service design: " + ", ".join(missing_global))
    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "global_acceptance_ids": sorted(global_acs),
        "mapped_acceptance_ids": sorted(mapped),
        "service_designs": [posix(path.relative_to(repo)) for path in files],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--global-design", required=True, type=Path)
    parser.add_argument("--service-design-dir", type=Path)
    parser.add_argument("--service-design", action="append", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(args.repo, args.global_design, args.service_design_dir, args.service_design)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Service design gate: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
