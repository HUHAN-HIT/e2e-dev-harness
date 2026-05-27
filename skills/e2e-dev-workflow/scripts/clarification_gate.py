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
CONTENT_REQUIRED_SECTIONS = tuple(key for key in REQUIRED if key != "open_questions")

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
PLACEHOLDER_MARKERS = {
    "",
    "-",
    "todo",
    "tbd",
    "n/a",
    "na",
    "unknown",
    "unclear",
    "pending",
}
MESSAGING_RE = re.compile(
    r"\b(dmq|mq|message queue|kafka|rocketmq|jms|topic|tag|producer|consumer|publish|publisher|send|notification|event)\b",
    re.IGNORECASE,
)
CALL_CHAIN_RE = re.compile(
    r"(->|\bcall chain\b|\bentry point\b|\bcontroller\b|\bhandler\b|\bservice\b|\borchestration\b|\bworkflow\b|调用链|入口|编排)",
    re.IGNORECASE,
)
SENDER_INJECTION_RE = re.compile(
    r"\b(sender|producer|publisher|template|kafkaTemplate|rocketMQTemplate|jmsTemplate|inject|injection|constructor)\b|注入|发送器|生产者",
    re.IGNORECASE,
)


IMPACT_REQUIRED_RE = re.compile(
    r"\b("
    r"api|http|https|rest|endpoint|route|controller|client|consumer|caller|public|"
    r"dmq|mq|message queue|kafka|rocketmq|jms|topic|tag|producer|publish|event|"
    r"database|schema|migration|table|column|cache|config|configuration|"
    r"auth|authorization|authentication|tenant|security|payment|refund"
    r")\b|接口|影响面|调用方|消费者|生产者|权限|支付|退款|数据库|配置",
    re.IGNORECASE,
)
IMPACT_SECTION_PATTERNS = [
    r"impact summary",
    r"impact analysis",
    r"affected interfaces?",
    r"blast radius",
    r"影响面",
    r"影响接口",
]
IMPACT_SOURCE_RE = re.compile(r"\bsource\s*:\s*.*\b(gitnexus|scanner|dependency|manual)\b", re.IGNORECASE)
RAW_EVIDENCE_RE = re.compile(
    r"\b(raw\s+evidence|evidence)\s*:\s*(?:`)?(?:docs/|\.e2e/|evidence/|[A-Za-z0-9_.\-/\\]+\.json)",
    re.IGNORECASE,
)
IMPACT_MAX_CHARS = 2400
IMPACT_MAX_ROWS = 12
IMPACT_REQUIRED_COLUMNS = {
    "type",
    "interface",
    "affected_callers_consumers",
    "related_ac",
    "required_tests_contracts",
    "risk",
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


def normalize_table_header(value: str) -> str:
    value = value.strip().lower().replace("/", "_").replace("-", "_")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    aliases = {
        "affected_callers": "affected_callers_consumers",
        "affected_consumers": "affected_callers_consumers",
        "affected_callers_consumers": "affected_callers_consumers",
        "affected_callers_or_consumers": "affected_callers_consumers",
        "callers_consumers": "affected_callers_consumers",
        "related_acceptance": "related_ac",
        "related_acceptance_criteria": "related_ac",
        "ac": "related_ac",
        "required_tests": "required_tests_contracts",
        "tests_contracts": "required_tests_contracts",
        "required_tests_contracts": "required_tests_contracts",
    }
    return aliases.get(value, value)


def parse_first_markdown_table(text: str) -> tuple[list[str], list[dict[str, str]]]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip().startswith("|") or index + 1 >= len(lines):
            continue
        separator = lines[index + 1].strip()
        if not separator.startswith("|") or not re.fullmatch(r"[|:\-\s]+", separator):
            continue
        headers = [normalize_table_header(part) for part in line.strip().strip("|").split("|")]
        rows: list[dict[str, str]] = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].strip().startswith("|"):
            values = [part.strip() for part in lines[cursor].strip().strip("|").split("|")]
            rows.append({header: values[pos] if pos < len(values) else "" for pos, header in enumerate(headers)})
            cursor += 1
        return headers, rows
    return [], []


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


def section_has_content(text: str | None) -> bool:
    if text is None:
        return False
    lines = normalize_lines(text)
    if not lines:
        return False
    for line in lines:
        normalized = line.strip().strip(".:;").lower()
        if normalized not in PLACEHOLDER_MARKERS and not any(marker == normalized for marker in UNRESOLVED_MARKERS):
            return True
    return False


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


def extract_acceptance_items(path: Path) -> list[dict[str, str]]:
    markdown = path.read_text(encoding="utf-8", errors="replace")
    text = section_text(markdown, REQUIRED["acceptance"])
    if text is None:
        return []
    results: list[dict[str, str]] = []
    used: set[str] = set()
    next_index = 1
    for line in text.splitlines():
        stripped = line.strip()
        content = ACCEPTANCE_LINE_RE.match(line)
        body = content.group(1).strip() if content else stripped
        id_match = ACCEPTANCE_ID_RE.match(body)
        if id_match:
            ac_id = normalize_acceptance_id(body)
            description = body[id_match.end() :].strip(" :-\t")
        elif body:
            while f"AC-{next_index}" in used:
                next_index += 1
            ac_id = f"AC-{next_index}"
            next_index += 1
            description = body
        else:
            continue
        if ac_id not in used:
            results.append({"id": ac_id, "text": description or body})
            used.add(ac_id)
    return results


def extract_acceptance_criteria(path: Path) -> list[str]:
    return [item["id"] for item in extract_acceptance_items(path)]


def integration_gaps(markdown: str) -> list[str]:
    behavior_text = "\n\n".join(
        text
        for text in (
            section_text(markdown, REQUIRED["acceptance"]),
            section_text(markdown, REQUIRED["use_cases"]),
            section_text(markdown, REQUIRED["scope"]),
        )
        if text
    )
    if not MESSAGING_RE.search(behavior_text):
        return []

    gaps: list[str] = []
    if not CALL_CHAIN_RE.search(markdown):
        gaps.append("Messaging/MQ requirements must declare the cross-layer call chain from entry point to sender/producer.")
    if not SENDER_INJECTION_RE.search(markdown):
        gaps.append("Messaging/MQ requirements must declare the sender/producer injection or construction point.")
    return gaps


def impact_summary_gaps(markdown: str) -> list[str]:
    behavior_text = "\n\n".join(
        text
        for text in (
            section_text(markdown, REQUIRED["acceptance"]),
            section_text(markdown, REQUIRED["use_cases"]),
            section_text(markdown, REQUIRED["scope"]),
        )
        if text
    )
    if not IMPACT_REQUIRED_RE.search(behavior_text):
        return []

    summary = section_text(markdown, IMPACT_SECTION_PATTERNS)
    if summary is None:
        return ["Impact Summary is required for public API, messaging, data, auth, payment, or cross-service requirements."]

    gaps: list[str] = []
    if len(summary) > IMPACT_MAX_CHARS:
        gaps.append("Impact Summary must stay bounded; put raw GitNexus/scanner output in an evidence file.")
    if not IMPACT_SOURCE_RE.search(summary):
        gaps.append("Impact Summary must include Source: GitNexus impact, dependency scanner, or manual non-applicability evidence.")
    if not RAW_EVIDENCE_RE.search(summary):
        gaps.append("Impact Summary must include Raw Evidence: <repo-relative evidence path> instead of pasting full output.")

    headers, rows = parse_first_markdown_table(summary)
    if not rows:
        gaps.append("Impact Summary must include an affected interfaces table.")
        return gaps

    if len(rows) > IMPACT_MAX_ROWS:
        gaps.append("Impact Summary table must stay bounded to at most 12 high-signal affected interface rows.")
    missing_columns = sorted(IMPACT_REQUIRED_COLUMNS - set(headers))
    if missing_columns:
        gaps.append("Impact Summary table missing columns: " + ", ".join(missing_columns))
    for index, row in enumerate(rows, start=1):
        row_label = row.get("interface") or f"row {index}"
        for column in sorted(IMPACT_REQUIRED_COLUMNS):
            if not row.get(column, "").strip():
                gaps.append(f"Impact Summary {row_label} missing {column}.")
        if not re.search(r"\bAC-?\d+\b", row.get("related_ac", ""), re.IGNORECASE):
            gaps.append(f"Impact Summary {row_label} must map the interface to an AC id.")
    return gaps


def validate(path: Path) -> dict:
    markdown = path.read_text(encoding="utf-8")
    titles = [title for title, _start, _end in headings(markdown)]
    missing = [
        key
        for key, patterns in REQUIRED.items()
        if not any(has_heading(title, patterns) for title in titles)
    ]
    empty_sections = [
        key
        for key in CONTENT_REQUIRED_SECTIONS
        if key not in missing and not section_has_content(section_text(markdown, REQUIRED[key]))
    ]
    oq_text = section_text(markdown, REQUIRED["open_questions"])
    oq_clear, unresolved = open_questions_clear(oq_text)
    gaps = integration_gaps(markdown)
    impact_gaps = impact_summary_gaps(markdown)
    ready = not missing and not empty_sections and oq_clear and not gaps and not impact_gaps
    return {
        "path": str(path),
        "ready_for_implementation": ready,
        "missing_sections": missing,
        "empty_sections": empty_sections,
        "open_questions_clear": oq_clear,
        "unresolved_open_questions": unresolved,
        "integration_gaps": gaps,
        "impact_gaps": impact_gaps,
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
        if result.get("empty_sections"):
            print("Empty sections: " + ", ".join(result["empty_sections"]))
        if not result["open_questions_clear"]:
            print("Unresolved open questions:")
            for question in result["unresolved_open_questions"]:
                print(f"- {question}")
        if result.get("impact_gaps"):
            print("Impact summary gaps:")
            for gap in result["impact_gaps"]:
                print(f"- {gap}")

    return 0 if result["ready_for_implementation"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
