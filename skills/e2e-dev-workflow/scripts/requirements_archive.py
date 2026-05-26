#!/usr/bin/env python3
"""Validate final requirements archive artifacts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REQUIRED_SECTIONS = [
    "Original Request",
    "Final Clarified Requirement",
    "Scope And Non-Goals",
    "Acceptance Criteria Status",
    "Use Case Coverage",
    "Impacted Services APIs And Contracts",
    "Implementation Evidence",
    "Test Evidence",
    "Review And Rework Summary",
    "Deferred And Residual Risks",
    "Promoted Memory Entries",
    "Follow Up Opportunities",
]

HEADING_RE = re.compile(r"^\s*(#{2,3})\s+(.+?)\s*$", re.MULTILINE)
PLACEHOLDER_RE = re.compile(r"\b(TBD|TODO|FIXME|UNKNOWN|PLACEHOLDER)\b|<[^>]+>", re.IGNORECASE)


def normalize_heading(value: str) -> str:
    value = re.sub(r"[`*_]", "", value.strip())
    value = value.replace("&", " And ")
    value = re.sub(r"[^A-Za-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def section_map(text: str) -> dict[str, str]:
    matches = list(HEADING_RE.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[normalize_heading(title)] = text[start:end].strip()
    return sections


def resolve_archive(repo: Path, archive: Path | None) -> Path | None:
    if not archive:
        return None
    return archive if archive.is_absolute() else repo / archive


def inside_repo(repo: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(repo.resolve())
        return True
    except ValueError:
        return False


def validate(repo: Path, archive: Path | None) -> dict:
    repo = repo.resolve()
    blocked: list[str] = []
    warnings: list[str] = []
    resolved = resolve_archive(repo, archive)

    if not resolved:
        blocked.append("Requirements archive path is required.")
        return {
            "repo": str(repo),
            "path": None,
            "ready": False,
            "blocked_reasons": blocked,
            "warnings": warnings,
            "section_count": 0,
            "sections": [],
        }
    if not inside_repo(repo, resolved):
        blocked.append(f"Requirements archive resolves outside repository: {resolved}")
    if not resolved.exists():
        blocked.append(f"Requirements archive not found: {resolved}")
        return {
            "repo": str(repo),
            "path": str(resolved),
            "ready": False,
            "blocked_reasons": blocked,
            "warnings": warnings,
            "section_count": 0,
            "sections": [],
        }

    text = resolved.read_text(encoding="utf-8", errors="replace")
    sections = section_map(text)
    for required in REQUIRED_SECTIONS:
        key = normalize_heading(required)
        body = sections.get(key, "")
        if not body:
            blocked.append(f"Requirements archive {resolved} missing required section content: {required}")
            continue
        if PLACEHOLDER_RE.search(body):
            blocked.append(f"Requirements archive {resolved} has placeholder content in section: {required}")

    if "requirements archive" not in text.lower().splitlines()[0].lower() if text.splitlines() else True:
        warnings.append("Requirements archive should start with a Requirements Archive title.")

    return {
        "repo": str(repo),
        "path": str(resolved),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "section_count": len([name for name in REQUIRED_SECTIONS if normalize_heading(name) in sections]),
        "sections": sorted(sections),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(args.repo, args.archive)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Requirements archive: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
