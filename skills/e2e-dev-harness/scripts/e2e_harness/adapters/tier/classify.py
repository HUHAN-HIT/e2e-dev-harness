"""Narrow tier classification (ported from legacy task_tier keyword logic).

Maps request text -> one of minimal / standard / critical / audited. When a
scanner scope (scanner-scope.v1) is supplied, it raises the tier *floor* by
structural risk (design §11): >=2 services => at least `standard`; >=1
cross-service dependency edge => `critical`. The scope never downgrades a
higher text-derived tier — the final tier is the more severe of the two.
"""
from __future__ import annotations

import re

# Severity order; index = how strict the tier is.
_ORDER = ["minimal", "standard", "critical", "audited"]

_PAYMENT = {"payment", "refund", "settlement", "ledger", "accounting", "reconcile",
            "chargeback", "billing", "invoice", "charge", "transfer", "withdraw",
            "withdrawal", "deposit", "wire",
            "支付", "退款", "结算", "账务", "对账", "账单", "发票", "转账", "提现", "充值"}
# Security-sensitive surfaces (auth/identity/secrets/access) escalate to critical:
# a subtle bug here is a vulnerability, not just a defect (design §11, G4).
_SECURITY = {"auth", "authentication", "authorization", "authorize", "login",
             "signin", "logout", "password", "passwd", "credential", "credentials",
             "token", "oauth", "sso", "session", "permission", "permissions",
             "rbac", "acl",
             "鉴权", "认证", "授权", "权限", "密码", "凭证", "登录", "令牌", "会话"}
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


def _classify_text(text: str) -> tuple[str, list[str]]:
    audit = _hits(text, _AUDIT, "audit")
    if audit:
        return "audited", audit
    risk: list[str] = []
    risk += _hits(text, _SECURITY, "security")
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


def _scanner_floor(scope: dict) -> tuple[str, list[str]]:
    """Lowest tier the scanner scope justifies, with reasons. minimal if none."""
    services = scope.get("services") or []
    dependencies = scope.get("dependencies") or []
    if dependencies:
        return "critical", [
            f"scanner: {len(dependencies)} cross-service dependency edge(s) detected"
        ]
    if len(services) >= 2:
        return "standard", [
            f"scanner: {len(services)} services detected"
        ]
    return "minimal", []


def classify_tier(request_text: str, scope: dict | None = None,
                  *, auto: bool = False) -> tuple[str, list[str]]:
    text = request_text or ""
    tier, reasons = _classify_text(text)
    if scope:
        floor, floor_reasons = _scanner_floor(scope)
        if _ORDER.index(floor) > _ORDER.index(tier):
            tier, reasons = floor, floor_reasons
        elif floor_reasons and _ORDER.index(floor) == _ORDER.index(tier):
            reasons = reasons + floor_reasons
    # G4: auto baseline floor. When the tier is being *derived* (no explicit
    # --tier), a no-risk request floors to `standard` rather than `minimal` so
    # review is the default. An explicit `--tier minimal` bypasses this (it never
    # calls classify_tier with auto=True). The floor only ever lifts minimal; it
    # never downgrades a higher text/scanner tier.
    if auto and tier == "minimal":
        tier = "standard"
        reasons = reasons + [
            "auto baseline floor: standard (no risk keyword detected; "
            "pass --tier minimal to opt down)"
        ]
    return tier, reasons
