#!/usr/bin/env python3
"""Classify workflow tier and required gates for strict delivery runs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TIERS = ("auto", "basic", "standard", "critical", "audited")
BASE_GATES = [
    "clarification",
    "impact-summary",
    "test-evidence",
    "completion-proof",
    "task-alignment",
    "run-state",
    "artifact-registry",
    "agent-schedule",
    "run-summary",
]
STANDARD_GATES = BASE_GATES + [
    "r1-review",
    "r2-review",
    "r3-review",
    "coverage-matrix",
    "requirements-archive",
]
CRITICAL_GATES = STANDARD_GATES + [
    "gitnexus-impact",
    "contracts",
    "service-plans",
    "handoffs",
    "strict-guard",
]
AUDITED_GATES = CRITICAL_GATES + [
    "harness-policy",
    "harness-replay",
    "completion-replay",
    "state-history",
]
PAYMENT_KEYWORDS = {
    "payment",
    "refund",
    "settlement",
    "ledger",
    "accounting",
    "reconcile",
    "chargeback",
    "支付",
    "退款",
    "结算",
    "账务",
    "对账",
}
CONTRACT_KEYWORDS = {
    "api",
    "http",
    "rest",
    "client",
    "contract",
    "schema",
    "compatibility",
    "接口",
    "契约",
    "兼容",
}
DATA_KEYWORDS = {
    "database",
    "db",
    "sql",
    "migration",
    "transaction",
    "repository",
    "mapper",
    "audit",
    "数据",
    "迁移",
    "事务",
    "审计",
}
MESSAGING_KEYWORDS = {
    "mq",
    "dmq",
    "kafka",
    "rocketmq",
    "rabbitmq",
    "topic",
    "tag",
    "group",
    "producer",
    "consumer",
    "sender",
    "payload",
    "消息",
    "队列",
    "生产者",
    "消费者",
}
AUDIT_KEYWORDS = {
    "audit",
    "compliance",
    "incident",
    "production incident",
    "regulatory",
    "合规",
    "审计",
    "事故",
    "生产故障",
}


def gates_for(tier: str) -> list[str]:
    if tier == "audited":
        return AUDITED_GATES
    if tier == "critical":
        return CRITICAL_GATES
    if tier == "standard":
        return STANDARD_GATES
    return BASE_GATES


def keyword_reasons(text: str, keywords: set[str], label: str) -> list[str]:
    lowered = text.lower()
    reasons: list[str] = []
    for keyword in sorted(keywords):
        if re.search(r"(?<![a-z0-9])" + re.escape(keyword.lower()) + r"(?![a-z0-9])", lowered):
            reasons.append(f"{label} keyword detected: {keyword}")
            break
    return reasons


def dependency_kinds(report: dict) -> set[str]:
    kinds: set[str] = set()
    for item in report.get("dependencies", []) if isinstance(report, dict) else []:
        kind = str(item.get("kind", "")).lower()
        if kind:
            kinds.add(kind)
    return kinds


def classify_auto(design_text: str, facts: dict, dependency_report: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    service_count = len(facts.get("service_candidates", [])) if isinstance(facts, dict) else 0
    if facts.get("multi_service") or service_count > 1:
        reasons.append("multiple service candidates detected")
    kinds = dependency_kinds(dependency_report)
    if kinds:
        reasons.append("cross-service dependency kinds detected: " + ", ".join(sorted(kinds)))
    reasons.extend(keyword_reasons(design_text, AUDIT_KEYWORDS, "audit"))
    if any("audit keyword" in reason for reason in reasons):
        return "audited", reasons
    risk_reasons: list[str] = []
    risk_reasons.extend(keyword_reasons(design_text, PAYMENT_KEYWORDS, "payment/refund"))
    risk_reasons.extend(keyword_reasons(design_text, CONTRACT_KEYWORDS, "contract/API"))
    risk_reasons.extend(keyword_reasons(design_text, DATA_KEYWORDS, "data"))
    risk_reasons.extend(keyword_reasons(design_text, MESSAGING_KEYWORDS, "messaging"))
    if kinds or reasons or risk_reasons:
        return "critical", reasons + risk_reasons
    if design_text.strip():
        return "standard", ["design-backed requirement detected"]
    return "basic", ["minimal scoped change detected"]


def evaluate(requested: str, design_text: str = "", facts: dict | None = None, dependency_report: dict | None = None) -> dict:
    if requested not in TIERS:
        raise ValueError(f"Unsupported workflow tier: {requested}")
    facts = facts or {}
    dependency_report = dependency_report or {}
    if requested == "auto":
        tier, reasons = classify_auto(design_text, facts, dependency_report)
    else:
        tier, reasons = requested, [f"workflow tier explicitly set to {requested}"]
    return {
        "requested": requested,
        "tier": tier,
        "reasons": reasons,
        "required_gates": gates_for(tier),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=TIERS, default="auto")
    parser.add_argument("--design-doc", type=Path)
    parser.add_argument("--facts", type=Path)
    parser.add_argument("--dependency-report", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    design_text = args.design_doc.read_text(encoding="utf-8", errors="replace") if args.design_doc else ""
    facts = json.loads(args.facts.read_text(encoding="utf-8")) if args.facts and args.facts.exists() else {}
    dependency_report = (
        json.loads(args.dependency_report.read_text(encoding="utf-8"))
        if args.dependency_report and args.dependency_report.exists()
        else {}
    )
    result = evaluate(args.tier, design_text, facts, dependency_report)
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else result["tier"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
