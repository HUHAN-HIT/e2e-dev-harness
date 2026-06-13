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

# Adversarial-review triggers (design "Tier and Selection Policy"): high-stakes
# surfaces where "how could this fail?" matters more than "does this look right?".
# These never select a tier — recommend.py surfaces them as an opt-in
# `--pipeline adversarial` suggestion the user confirms.
_CONTROL_PLANE = {"control plane", "control-plane", "coordinator", "lifecycle",
                  "phase guard", "state machine", "orchestration", "orchestrator",
                  "控制面", "协调器", "状态机", "编排"}
_EVIDENCE_GATE = {"evidence", "gate", "gating", "dispatch", "dispatcher",
                  "证据", "门禁", "派发", "网关"}
_CONCURRENCY = {"concurrency", "concurrent", "parallel", "parallelism",
                "race condition", "fan-out", "fanout", "multi-track", "multitrack",
                "并发", "并行", "竞态", "多轨", "扇出"}
_VERIFICATION_SEMANTICS = {"verification semantics", "verification gate",
                           "test framework", "test harness", "replay", "gate validator",
                           "验证语义", "测试框架", "回放"}
# label -> keyword set; security reuses the tier classifier's _SECURITY surface.
_ADVERSARIAL_TRIGGERS = (
    ("control-plane", _CONTROL_PLANE),
    ("evidence/gate/dispatch", _EVIDENCE_GATE),
    ("cross-module concurrency", _CONCURRENCY),
    ("verification/test-semantics", _VERIFICATION_SEMANTICS),
    ("security-sensitive", _SECURITY),
)


def _first_keyword(text: str, keywords: set[str]) -> str | None:
    lowered = text.lower()
    for kw in sorted(keywords):
        if re.search(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])", lowered):
            return kw
    return None


def _hits(text: str, keywords: set[str], label: str) -> list[str]:
    kw = _first_keyword(text, keywords)
    return [f"{label} keyword detected: {kw}"] if kw else []


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


def adversarial_triggers(request_text: str, scope: dict | None = None) -> list[str]:
    """Advisory adversarial-review triggers (Slice 3). Returns reason strings, empty
    when none fire. This NEVER selects a tier or pipeline — recommend.py surfaces
    these as a user-confirmed `--pipeline adversarial` suggestion. Triggers: high
    GitNexus impact, security-sensitive, control-plane, cross-module concurrency,
    evidence/gate/dispatch, and verification/test-semantics changes."""
    text = request_text or ""
    reasons: list[str] = []
    gitnexus = (scope or {}).get("gitnexus") or {}
    risk = str((gitnexus.get("impact_summary") or {}).get("risk") or "").upper()
    if risk in {"HIGH", "CRITICAL"}:
        reasons.append(f"adversarial-review trigger (high GitNexus impact): {risk}")
    for label, keywords in _ADVERSARIAL_TRIGGERS:
        kw = _first_keyword(text, keywords)
        if kw:
            reasons.append(f"adversarial-review trigger ({label}): {kw}")
    return reasons
