#!/usr/bin/env python3
"""Validate that a Markdown design note is ready for implementation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from common import configure_utf8_stdio


REQUIRED = {
    "restated_intent": [r"restated intent", r"user intent", r"intent confirmation", r"\u610f\u56fe\u56de\u663e", r"\u7528\u6237\u610f\u56fe"],
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

SECTION_LABELS = {
    "restated_intent": "Restated Intent / user confirmation",
    "goal": "Goal",
    "scope": "Scope / affected services / non-goals",
    "use_cases": "Use Cases",
    "acceptance": "Acceptance Criteria",
    "test_design": "Test Design",
    "open_questions": "Open Questions",
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
CHANGE_LOGIC_SECTION_PATTERNS = [
    r"change logic",
    r"implementation logic",
    r"logic changes?",
    r"behavior changes?",
    r"\u6539\u52a8\u903b\u8f91",
    r"\u53d8\u66f4\u903b\u8f91",
    r"\u5b9e\u73b0\u903b\u8f91",
]
CURRENT_BEHAVIOR_RE = re.compile(
    r"\b(current|existing|before|today|as-is|baseline)\b|"
    r"\u73b0\u72b6|\u5f53\u524d|\u6539\u524d|\u5df2\u6709",
    re.IGNORECASE,
)
TARGET_BEHAVIOR_RE = re.compile(
    r"\b(target|after|new|to-be|expected|desired)\b|"
    r"\u76ee\u6807|\u6539\u540e|\u65b0\u589e|\u9884\u671f",
    re.IGNORECASE,
)
RUNTIME_PATH_RE = re.compile(
    r"(->|\bentry\b|\bcontroller\b|\bhandler\b|\bservice\b|\brepository\b|\bclient\b|\bsender\b|\bproducer\b|"
    r"\u5165\u53e3|\u8c03\u7528\u94fe|\u6d41\u7a0b|\u7f16\u6392)",
    re.IGNORECASE,
)
STATE_DATA_EFFECT_RE = re.compile(
    r"\b(state|status|database|table|column|cache|config|payload|response|request|field|audit)\b|"
    r"\u72b6\u6001|\u6570\u636e|\u8868|\u5b57\u6bb5|\u914d\u7f6e|\u8bf7\u6c42|\u54cd\u5e94|\u8f7d\u8377|\u5ba1\u8ba1",
    re.IGNORECASE,
)


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


def clarification_questions(result: dict) -> list[str]:
    questions: list[str] = []
    if result.get("intent_required") and "restated_intent" in result.get("missing_sections", []):
        questions.append("Ask the user to confirm the agent's restated intent before planning.")
    for key in result.get("missing_sections", []):
        if key == "restated_intent":
            continue
        label = SECTION_LABELS.get(key, key.replace("_", " ").title())
        questions.append(f"Ask the user what belongs in {label}, or record the evidence-backed answer in the design doc.")
    for key in result.get("empty_sections", []):
        label = SECTION_LABELS.get(key, key.replace("_", " ").title())
        questions.append(f"Ask the user to clarify {label}, or record the evidence-backed answer in the design doc.")
    for question in result.get("unresolved_open_questions", []):
        questions.append(f"Resolve with the user: {question}")
    for gap in result.get("integration_gaps", []):
        questions.append(f"Clarify integration behavior before implementation: {gap}")
    for gap in result.get("impact_gaps", []):
        questions.append(f"Clarify impact evidence before implementation: {gap}")
    for gap in result.get("change_logic_gaps", []):
        questions.append(f"Clarify change logic before implementation: {gap}")
    return questions


def interaction_contract(result: dict) -> dict:
    questions = clarification_questions(result)
    return {
        "schema": "e2e-dev-harness.clarification-interaction.v1",
        "interaction_required": bool(questions),
        "must_wait_for_user_answer": bool(questions),
        "questions_to_ask_user": questions,
        "allowed_before_user_answer": [
            "bounded GitNexus or scanner discovery for evidence",
            "drafting design sections clearly marked pending confirmation",
        ],
        "blocked_until_resolved": [
            "planning",
            "TDD",
            "production-code edits",
            "review dispatch that depends on clarified behavior",
        ],
    }


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


def change_logic_gaps(markdown: str) -> list[str]:
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

    text = section_text(markdown, CHANGE_LOGIC_SECTION_PATTERNS)
    if text is None:
        return ["Change Logic is required for public API, messaging, data, auth, payment, refund, or cross-service requirements."]

    gaps: list[str] = []
    if not CURRENT_BEHAVIOR_RE.search(text):
        gaps.append("Change Logic must describe the current/before behavior being changed.")
    if not TARGET_BEHAVIOR_RE.search(text):
        gaps.append("Change Logic must describe the target/after behavior.")
    if not RUNTIME_PATH_RE.search(text):
        gaps.append("Change Logic must trace the runtime path from entry point through service/client/sender/repository.")
    if not STATE_DATA_EFFECT_RE.search(text):
        gaps.append("Change Logic must name state, data, config, request/response, payload, or audit effects.")
    return gaps


def validate(path: Path, require_intent: bool = False) -> dict:
    markdown = path.read_text(encoding="utf-8")
    titles = [title for title, _start, _end in headings(markdown)]
    required_items = REQUIRED if require_intent else {key: value for key, value in REQUIRED.items() if key != "restated_intent"}
    missing = [
        key
        for key, patterns in required_items.items()
        if not any(has_heading(title, patterns) for title in titles)
    ]
    empty_sections = [
        key
        for key in CONTENT_REQUIRED_SECTIONS
        if key in required_items and key not in missing and not section_has_content(section_text(markdown, REQUIRED[key]))
    ]
    oq_text = section_text(markdown, REQUIRED["open_questions"])
    oq_clear, unresolved = open_questions_clear(oq_text)
    gaps = integration_gaps(markdown)
    impact_gaps = impact_summary_gaps(markdown)
    logic_gaps = change_logic_gaps(markdown)
    ready = not missing and not empty_sections and oq_clear and not gaps and not impact_gaps and not logic_gaps
    result = {
        "path": str(path),
        "ready_for_implementation": ready,
        "missing_sections": missing,
        "empty_sections": empty_sections,
        "open_questions_clear": oq_clear,
        "unresolved_open_questions": unresolved,
        "integration_gaps": gaps,
        "impact_gaps": impact_gaps,
        "change_logic_gaps": logic_gaps,
        "intent_required": require_intent,
    }
    result["interaction_contract"] = interaction_contract(result)
    result["interaction_required"] = result["interaction_contract"]["interaction_required"]
    result["questions_to_ask_user"] = result["interaction_contract"]["questions_to_ask_user"]
    return result


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design_doc", type=Path)
    parser.add_argument("--require-intent", action="store_true", help="Require a Restated Intent/User Intent section.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    args = parser.parse_args()

    if not args.design_doc.exists():
        print(f"Design doc not found: {args.design_doc}", file=sys.stderr)
        return 2

    result = validate(args.design_doc, require_intent=args.require_intent)
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
        if result.get("change_logic_gaps"):
            print("Change logic gaps:")
            for gap in result["change_logic_gaps"]:
                print(f"- {gap}")

    return 0 if result["ready_for_implementation"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
