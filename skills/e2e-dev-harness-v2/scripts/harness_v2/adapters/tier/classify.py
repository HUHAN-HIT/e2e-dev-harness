"""Narrow tier classification (ported from legacy task_tier keyword logic, text-only).

Multi-service / dependency-report escalation is intentionally omitted until the
scanner leaf is ported (design §16). Maps request text -> one of
minimal / standard / critical / audited.
"""
from __future__ import annotations

import re

_PAYMENT = {"payment", "refund", "settlement", "ledger", "accounting", "reconcile",
            "chargeback", "支付", "退款", "结算", "账务", "对账"}
_CONTRACT = {"contract", "compatibility", "接口", "契约", "兼容"}
_WEAK_CONTRACT = {"api", "http", "rest", "client", "endpoint"}
_DATA = {"database", "db", "sql", "migration", "transaction", "audit",
         "数据", "迁移", "事务", "审计"}
_MESSAGING = {"mq", "kafka", "rocketmq", "rabbitmq", "topic", "producer", "consumer",
              "payload", "消息", "队列", "生产者", "消费者"}
_AUDIT = {"audit", "compliance", "incident", "regulatory", "合规", "审计", "事故"}


def _hits(text: str, keywords: set[str], label: str) -> list[str]:
    lowered = text.lower()
    for kw in sorted(keywords):
        if re.search(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])", lowered):
            return [f"{label} keyword detected: {kw}"]
    return []


def classify_tier(request_text: str) -> tuple[str, list[str]]:
    text = request_text or ""
    audit = _hits(text, _AUDIT, "audit")
    if audit:
        return "audited", audit
    risk: list[str] = []
    risk += _hits(text, _PAYMENT, "payment/refund")
    risk += _hits(text, _CONTRACT, "contract/API")
    risk += _hits(text, _DATA, "data")
    risk += _hits(text, _MESSAGING, "messaging")
    if risk:
        return "critical", risk
    weak = _hits(text, _WEAK_CONTRACT, "contract/API")
    if weak:
        return "standard", ["single-service API surface detected"] + weak
    return "minimal", ["no risk keyword detected"]
