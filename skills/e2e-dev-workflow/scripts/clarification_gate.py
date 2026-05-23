#!/usr/bin/env python3
"""Validate that a Markdown design note is ready for implementation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REQUIRED = {
    "goal": [r"^(?!non[-\s])goals?\b", r"\bobjective\b", r"(?<!非)目标"],
    "scope": [r"\bscope\b", r"\bnon[-\s]?goals?\b", r"范围", r"非目标"],
    "use_cases": [r"use cases?", r"用例", r"场景"],
    "acceptance": [r"acceptance criteria", r"验收"],
    "test_design": [r"test design", r"test plan", r"testing", r"测试"],
    "open_questions": [r"open questions?", r"questions?", r"待澄清", r"开放问题"],
}

ACCEPTANCE_ID_RE = re.compile(r"^AC-?(\d+)\b", re.IGNORECASE)
ACCEPTANCE_LINE_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*\S)")

UNRESOLVED_MARKERS = (
    "todo",
    "tbd",
    "?",
    "？",
    "unknown",
    "unclear",
    "待定",
    "待确认",
    "待澄清",
    "未确定",
)
RESOLVED_MARKERS = (
    "resolved",
    "answered",
    "confirmed",
    "decided",
    "covered",
    "已解决",
    "已回答",
    "已确认",
    "已决定",
    "已覆盖",
)

NONE_MARKERS = {
    "none",
    "n/a",
    "na",
    "no open questions",
    "no unresolved questions",
    "无",
    "无待澄清",
    "没有",
    "已清零",
}


def headings(markdown: str) -> list[tuple[str, int, int]]:
    found: list[tuple[str, int, int]] = []
    for match in re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", markdown):
        found.append((match.group(2).strip(), match.start(), match.end()))
    return found


def has_heading(title: str, patterns: list[str]) -> bool:
    normalized = title.lower()
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns)


def section_text(markdown: str, matching_patterns: list[str]) -> str | None:
    hs = headings(markdown)
    for index, (title, _start, end) in enumerate(hs):
        if has_heading(title, matching_patterns):
            next_start = hs[index + 1][1] if index + 1 < len(hs) else len(markdown)
            return markdown[end:next_start].strip()
    return None


def normalize_acceptance_id(value: str) -> str:
    match = ACCEPTANCE_ID_RE.match(value.strip())
    if match:
        return f"AC-{int(match.group(1))}"
    return value.strip().upper()


def normalize_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().strip("-*0123456789. \t").strip()
        if line and not line.startswith("<!--"):
            lines.append(line)
    return lines


def open_questions_clear(text: str | None) -> tuple[bool, list[str]]:
    if text is None:
        return False, ["missing open questions section"]
    lines = normalize_lines(text)
    if not lines:
        return False, ["open questions section is empty; write 'None' explicitly"]
    joined = " ".join(lines).lower()
    if any(marker in joined for marker in NONE_MARKERS):
        return True, []
    unresolved = [
        line
        for line in lines
        if any(marker in line.lower() for marker in UNRESOLVED_MARKERS)
    ]
    if unresolved:
        return False, unresolved
    if all(any(marker in line.lower() for marker in RESOLVED_MARKERS) for line in lines):
        return True, []
    return False, lines


def extract_acceptance_criteria(path: Path) -> list[str]:
    markdown = path.read_text(encoding="utf-8")
    text = section_text(markdown, REQUIRED["acceptance"])
    if text is None:
        return []
    results: list[str] = []
    used: set[str] = set()
    next_index = 1
    for line in text.splitlines():
        stripped = line.strip()
        match = ACCEPTANCE_ID_RE.match(stripped)
        if match:
            ac_id = normalize_acceptance_id(stripped)
            if ac_id not in used:
                results.append(ac_id)
                used.add(ac_id)
            continue
        content = ACCEPTANCE_LINE_RE.match(line)
        if content:
            body = content.group(1).strip()
            id_match = ACCEPTANCE_ID_RE.match(body)
            if id_match:
                ac_id = normalize_acceptance_id(body)
            else:
                while f"AC-{next_index}" in used:
                    next_index += 1
                ac_id = f"AC-{next_index}"
                next_index += 1
            if ac_id not in used:
                results.append(ac_id)
                used.add(ac_id)
    return results


def validate(path: Path) -> dict:
    markdown = path.read_text(encoding="utf-8")
    titles = [title for title, _start, _end in headings(markdown)]
    missing = [
        key
        for key, patterns in REQUIRED.items()
        if not any(has_heading(title, patterns) for title in titles)
    ]
    oq_text = section_text(markdown, REQUIRED["open_questions"])
    oq_clear, unresolved = open_questions_clear(oq_text)
    ready = not missing and oq_clear
    return {
        "path": str(path),
        "ready_for_implementation": ready,
        "missing_sections": missing,
        "open_questions_clear": oq_clear,
        "unresolved_open_questions": unresolved,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design_doc", type=Path)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    args = parser.parse_args()

    if not args.design_doc.exists():
        print(f"Design doc not found: {args.design_doc}", file=sys.stderr)
        return 2

    result = validate(args.design_doc)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        status = "READY" if result["ready_for_implementation"] else "BLOCKED"
        print(f"Clarification gate: {status}")
        if result["missing_sections"]:
            print("Missing sections: " + ", ".join(result["missing_sections"]))
        if not result["open_questions_clear"]:
            print("Unresolved open questions:")
            for question in result["unresolved_open_questions"]:
                print(f"- {question}")

    return 0 if result["ready_for_implementation"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
