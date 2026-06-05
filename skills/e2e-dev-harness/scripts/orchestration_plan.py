#!/usr/bin/env python3
"""Recommend split-role or multi-service orchestration for Spring 6 work."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import agent_roles  # noqa: E402
from kg_refresh import detect  # noqa: E402


AGENT_MODES = ("auto", "single", "single-review", "multi")
EXPLICIT_AGENT_MODES = {"single", "single-review", "multi"}
LARGE_DESIGN_CHAR_THRESHOLD = 6000
RISK_KEYWORDS = {
    "contract",
    "schema",
    "migration",
    "database",
    "transaction",
    "auth",
    "authentication",
    "authorization",
    "permission",
    "security",
    "idempotent",
    "retry",
    "topic",
    "producer",
    "consumer",
    "listener",
    "publish",
    "subscribe",
    "payload",
    "dmq",
    "rocketmq",
    "kafka",
    "rabbitmq",
    "payment",
    "refund",
    "settlement",
    "payout",
    "withdraw",
    "notify",
    "notice",
    "callback",
    "webhook",
    "跨服务",
    "契约",
    "消息契约",
    "主题",
    "生产者",
    "消费者",
    "监听",
    "发布",
    "订阅",
    "载荷",
    "队列",
    "数据库",
    "迁移",
    "权限",
    "幂等",
    "重试",
}
SERVICE_SCOPES = ("auto", "discovery", "affected", "all")
MERGED_SERVICE_ID = "merged-modules"


def env_default(primary: str, legacy: str, default: str) -> str:
    return os.environ.get(primary, os.environ.get(legacy, default))


SECTION_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*$")
AFFECTED_SECTION_KEYWORDS = (
    "scope",
    "affected service",
    "affected services",
    "affected module",
    "affected modules",
    "affected services/modules",
    "in-scope",
    "in scope",
    "涉及模块",
    "涉及服务",
    "涉及微服务",
    "影响模块",
    "影响服务",
    "影响微服务",
    "受影响服务",
    "受影响模块",
    "微服务",
)
GENERIC_SERVICE_LABELS = {
    "service",
    "services",
    "module",
    "modules",
    "affected service",
    "affected services",
    "affected module",
    "affected modules",
    "服务",
    "模块",
    "微服务",
    "影响服务",
    "涉及服务",
}
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def read_design(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def read_json(path: Path | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def services_from_dependency_report(path: Path | None) -> list[str]:
    report = read_json(path)
    selected: list[str] = []
    seen: set[str] = set()
    for dependency in report.get("dependencies", []):
        for key in ("source_service", "target_service"):
            service = dependency.get(key)
            if service and service not in seen:
                seen.add(service)
                selected.append(normalize_path(str(service)))
    return selected


def design_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        match = SECTION_HEADING_RE.match(line)
        if match:
            current = match.group("title").strip().lower()
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(line)
    return {title: "\n".join(lines).strip() for title, lines in sections.items()}


def affected_section_bodies(text: str) -> list[str]:
    return [
        body
        for title, body in design_sections(text).items()
        if any(keyword in title for keyword in AFFECTED_SECTION_KEYWORDS)
    ]


def clean_service_token(value: str) -> str:
    token = value.strip().strip("`'\".,;，。；、()[]")
    token = token.replace("\\", "/")
    token = token.split(" - ", 1)[0].split(" -- ", 1)[0].split("：", 1)[0].split(":", 1)[0]
    token = re.split(r"\s+", token.strip(), maxsplit=1)[0] if token.strip() else ""
    return normalize_path(token)


def add_requested_service_token(requested: list[str], seen: set[str], value: str) -> None:
    service = clean_service_token(value)
    lowered = service.lower()
    if not service or lowered in {"none", "n/a", "na"} or lowered in GENERIC_SERVICE_LABELS:
        return
    if service not in seen:
        seen.add(service)
        requested.append(service)


def service_tokens_from_design_line(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped or TABLE_SEPARATOR_RE.match(stripped):
        return []
    if "|" in stripped:
        cells = [cell.strip() for cell in stripped.strip("|").split("|") if cell.strip()]
        if not cells:
            return []
        first = cells[0].lower()
        if first in GENERIC_SERVICE_LABELS:
            return []
        return [cells[0]]

    item = LIST_ITEM_RE.sub("", stripped).strip()
    if not item:
        return []
    if ":" in item or "：" in item:
        separator = ":" if ":" in item else "："
        left, right = item.split(separator, 1)
        if left.strip().lower() in GENERIC_SERVICE_LABELS:
            return [part.strip() for part in re.split(r"[,，、;；]", right) if part.strip()]
        return [left.strip()]
    return [part.strip() for part in re.split(r"[,，、;；]", item) if part.strip()]


def requested_services_from_design(text: str) -> list[str]:
    requested: list[str] = []
    seen: set[str] = set()
    for body in affected_section_bodies(text):
        for line in body.splitlines():
            for token in service_tokens_from_design_line(line):
                add_requested_service_token(requested, seen, token)
    return requested


def service_mentioned_in_text(service: str, text: str) -> bool:
    if not text:
        return False
    normalized_text = normalize_path(text).lower()
    service_value = normalize_path(service).lower()
    service_name = service_value.rstrip("/").split("/")[-1]
    for value in (service_value, service_name):
        if not value:
            continue
        pattern = r"(?<![a-z0-9_.-])" + re.escape(value) + r"(?![a-z0-9_.-])"
        if re.search(pattern, normalized_text):
            return True
    return False


def services_from_design(text: str, facts: dict) -> list[str]:
    candidates = [normalize_path(service) for service in facts.get("service_candidates", [])]
    selected: list[str] = []
    seen: set[str] = set()
    for requested in requested_services_from_design(text):
        matched = match_requested_service(candidates, requested)
        if matched and matched not in seen:
            seen.add(matched)
            selected.append(matched)
    affected_text = "\n".join(affected_section_bodies(text))
    for candidate in candidates:
        if candidate not in seen and service_mentioned_in_text(candidate, affected_text):
            seen.add(candidate)
            selected.append(candidate)
    return selected


def feature_slug(design_doc: Path | None) -> str:
    if design_doc and design_doc.name:
        name = design_doc.stem
        for suffix in ("-design", "-requirements", "-use-cases", "-test-plan", "-implementation-plan"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        return name or "feature"
    return "feature"


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
    return slug or "feature"


def default_run_id(slug: str, run_date: str | None = None) -> str:
    return f"{run_date or date.today().isoformat()}-{safe_slug(slug)}"


def keyword_matches(keyword: str, lowered_text: str) -> bool:
    if re.fullmatch(r"[a-z0-9][a-z0-9 -]*", keyword):
        pattern = r"(?<![a-z0-9])" + re.escape(keyword).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        return re.search(pattern, lowered_text) is not None
    return keyword.lower() in lowered_text


def mode_reasons(facts: dict, design_text: str, design_is_template: bool) -> list[str]:
    reasons: list[str] = []
    service_count = len(facts.get("service_candidates", []))
    if facts.get("multi_service") or service_count > 1:
        reasons.append("multiple service candidates detected")
    if design_is_template:
        reasons.append("template design doc detected; placeholder risk keywords ignored")
    elif len(design_text) > LARGE_DESIGN_CHAR_THRESHOLD:
        reasons.append("design document is large enough to benefit from context isolation")
    if not design_is_template:
        lowered = design_text.lower()
        matched = sorted(keyword for keyword in RISK_KEYWORDS if keyword_matches(keyword, lowered))
        if matched:
            reasons.append("risk keywords detected: " + ", ".join(matched[:8]))
    if not design_is_template and facts.get("design_docs_or_media_count", 0) >= 12:
        reasons.append("many design/media artifacts detected")
    return reasons


def actionable_mode_reasons(reasons: list[str]) -> list[str]:
    return [reason for reason in reasons if not reason.startswith("template design doc")]


def multi_forcing_reasons(reasons: list[str]) -> list[str]:
    return [
        reason
        for reason in actionable_mode_reasons(reasons)
        if reason.startswith("multiple service candidates")
    ]


def review_isolation_reasons(reasons: list[str]) -> list[str]:
    return [
        reason
        for reason in actionable_mode_reasons(reasons)
        if reason not in multi_forcing_reasons(reasons)
    ]


def choose_mode(requested: str, facts: dict, design_text: str, design_is_template: bool) -> tuple[str, list[str]]:
    reasons = mode_reasons(facts, design_text, design_is_template)
    low_risk_single_approved = bool(facts.get("low_risk_single_service_approved"))
    if requested in {"single", "single-review"}:
        multi_reasons = multi_forcing_reasons(reasons)
        if multi_reasons:
            return "multi", [f"{requested} escalated to multi: " + "; ".join(multi_reasons[:3])] + reasons
        if requested == "single":
            review_reasons = review_isolation_reasons(reasons)
            if review_reasons:
                return "single-review", ["single escalated to single-review: " + "; ".join(review_reasons[:3])] + reasons
            if not low_risk_single_approved:
                return "single-review", ["single requires machine-verified low-risk approval; using single-review floor"] + reasons
            return "single", ["mode explicitly set to single with machine-verified low-risk single-service approval"] + reasons
        return requested, [f"mode explicitly set to {requested}"]
    if requested in EXPLICIT_AGENT_MODES:
        return requested, [f"mode explicitly set to {requested}"]

    multi_reasons = multi_forcing_reasons(reasons)
    if multi_reasons:
        return "multi", reasons
    review_reasons = review_isolation_reasons(reasons)
    if review_reasons:
        return "single-review", reasons
    if low_risk_single_approved:
        return "single", ["machine-verified low-risk single-service approval"] + reasons
    return "single-review", ["single-review floor for non-trivial harness run"] + reasons


def service_slug(service: str) -> str:
    name = service.replace("\\", "/").rstrip("/").split("/")[-1]
    return safe_slug(name)


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip("/")


def resolve_service_scope(service_scope: str, requested_services: list[str] | None, requested_paths: list[str] | None) -> str:
    if service_scope != "auto":
        return service_scope
    if requested_services or requested_paths:
        return "affected"
    return "discovery"


def match_requested_service(candidates: list[str], requested: str) -> str | None:
    value = normalize_path(requested).lower()
    for candidate in candidates:
        normalized = normalize_path(candidate).lower()
        if value == normalized or value == normalized.split("/")[-1]:
            return candidate
    return None


def service_for_path(candidates: list[str], requested_path: str) -> str | None:
    value = normalize_path(requested_path).lower()
    matches = [
        candidate
        for candidate in candidates
        if value == normalize_path(candidate).lower() or value.startswith(normalize_path(candidate).lower() + "/")
    ]
    if not matches:
        return None
    return sorted(matches, key=len, reverse=True)[0]


def unmatched_requested_services(facts: dict, requested_services: list[str] | None) -> list[str]:
    candidates = [normalize_path(service) for service in facts.get("service_candidates", [])]
    return [
        requested
        for requested in requested_services or []
        if not match_requested_service(candidates, requested)
    ]


def design_risk_in_text(lowered_text: str) -> bool:
    """Risk-keyword scan for service-design slicing.

    Unlike ``keyword_matches`` this treats ``-`` and ``_`` as token boundaries so a keyword that is
    only present as part of a hyphenated module name (e.g. ``payment`` inside ``jeepay-payment``)
    does not count as risk. A standalone ``payment`` word still matches.
    """
    for keyword in RISK_KEYWORDS:
        if re.fullmatch(r"[a-z0-9][a-z0-9 -]*", keyword):
            pattern = r"(?<![a-z0-9_-])" + re.escape(keyword).replace(r"\ ", r"\s+") + r"(?![a-z0-9_-])"
            if re.search(pattern, lowered_text):
                return True
        elif keyword.lower() in lowered_text:
            return True
    return False


def service_design_risk(service: str, design_text: str) -> bool:
    """True when any design section that mentions the service also carries a risk keyword."""
    if not design_text:
        return False
    for body in design_sections(design_text).values():
        if not body or not service_mentioned_in_text(service, body):
            continue
        if design_risk_in_text(body.lower()):
            return True
    return False


def _service_in_requested(service: str, requested: list[str] | None) -> bool:
    return any(match_requested_service([service], value) for value in requested or [])


def _service_in_paths(service: str, requested_paths: list[str] | None) -> bool:
    return any(service_for_path([service], path) for path in requested_paths or [])


def slice_worthy_service(
    service: str,
    explicit_services: list[str] | None,
    explicit_paths: list[str] | None,
    dependency_services: list[str] | None,
    design_text: str,
) -> bool:
    """A service earns its own slice when isolation is explicitly required or design risk is detected."""
    return (
        _service_in_requested(service, explicit_services)
        or _service_in_paths(service, explicit_paths)
        or _service_in_requested(service, dependency_services)
        or service_design_risk(service, design_text)
    )


def partition_services(
    services: list[str],
    explicit_services: list[str] | None = None,
    explicit_paths: list[str] | None = None,
    dependency_services: list[str] | None = None,
    design_text: str = "",
    facts: dict | None = None,
) -> tuple[list[str], list[str]]:
    """Split selected services into independent slices and a low-risk merge group, preserving order."""
    slice_services: list[str] = []
    merged_services: list[str] = []
    for service in services:
        if slice_worthy_service(service, explicit_services, explicit_paths, dependency_services, design_text):
            slice_services.append(service)
        else:
            merged_services.append(service)
    return slice_services, merged_services


def plan_service_layout(
    services: list[str],
    explicit_services: list[str] | None = None,
    explicit_paths: list[str] | None = None,
    dependency_services: list[str] | None = None,
    design_text: str = "",
    facts: dict | None = None,
) -> dict:
    """Return the artifact/run-state layout: per-service slices plus one merged slice for low-risk services.

    A merge only happens when 2+ services are selected; otherwise the single service stays a slice so
    single-service runs keep their existing behavior. Merged services are routed through run-state
    ``shared_edit_scopes`` (not ``services``) so phase_guard treats them as one shared edit scope.
    """
    if len(services) < 2:
        return {
            "slice_services": list(services),
            "merged_services": [],
            "merged_id": "",
            "artifact_services": list(services),
            "shared_edit_scopes": [],
            "shared_edit_scope_owners": {},
        }
    slice_services, merged_services = partition_services(
        services,
        explicit_services,
        explicit_paths,
        dependency_services,
        design_text,
        facts,
    )
    merged_id = MERGED_SERVICE_ID if merged_services else ""
    artifact_services = list(slice_services)
    if merged_services:
        artifact_services.append(merged_id)
    shared_edit_scopes = [normalize_path(service) + "/" for service in merged_services]
    shared_edit_scope_owners = {scope: merged_id for scope in shared_edit_scopes}
    return {
        "slice_services": slice_services,
        "merged_services": merged_services,
        "merged_id": merged_id,
        "artifact_services": artifact_services,
        "shared_edit_scopes": shared_edit_scopes,
        "shared_edit_scope_owners": shared_edit_scope_owners,
    }


def select_services(
    facts: dict,
    requested_services: list[str] | None = None,
    requested_paths: list[str] | None = None,
    service_scope: str = "auto",
) -> tuple[list[str], str]:
    candidates = [normalize_path(service) for service in facts.get("service_candidates", [])]
    resolved = resolve_service_scope(service_scope, requested_services, requested_paths)
    if resolved == "discovery":
        return [], resolved
    if resolved == "all":
        return candidates, resolved

    selected: list[str] = []
    seen: set[str] = set()
    for requested in requested_services or []:
        matched = match_requested_service(candidates, requested)
        if matched and matched not in seen:
            seen.add(matched)
            selected.append(matched)
    for path in requested_paths or []:
        matched = service_for_path(candidates, path)
        if matched and matched not in seen:
            seen.add(matched)
            selected.append(matched)
    return selected, resolved


def mode_facts_for_service_scope(facts: dict, selected_services: list[str], resolved_service_scope: str) -> dict:
    scoped = dict(facts)
    if resolved_service_scope == "discovery":
        scoped["service_candidates"] = []
        scoped["multi_service"] = False
    elif resolved_service_scope == "affected":
        scoped["service_candidates"] = selected_services
        scoped["multi_service"] = len(selected_services) > 1
    elif resolved_service_scope == "all":
        scoped["service_candidates"] = facts.get("service_candidates", [])
        scoped["multi_service"] = len(scoped["service_candidates"]) > 1
    return scoped


def detection_summary(facts: dict, limit: int = 20) -> dict:
    services = facts.get("service_candidates", [])
    return {
        "service_candidates_count": len(services),
        "service_candidates_sample": services[:limit],
        "service_candidates_truncated": len(services) > limit,
        "multi_service": facts.get("multi_service", False),
        "design_docs_or_media_count": facts.get("design_docs_or_media_count", 0),
        "spring_entrypoints_count": len(facts.get("spring_entrypoints", [])),
    }


def discovery_result(
    repo: Path,
    requested_mode: str,
    requested_service_scope: str,
    requested_services: list[str] | None,
    requested_paths: list[str] | None,
    facts: dict,
) -> dict:
    return {
        "repo": str(repo),
        "requested_mode": requested_mode,
        "selected_mode": "discovery",
        "requested_service_scope": requested_service_scope,
        "resolved_service_scope": "discovery",
        "requested_services": requested_services or [],
        "requested_paths": requested_paths or [],
        "selected_services": [],
        "reasons": [
            "discovery scope defers implementation agent planning until affected services are known"
        ],
        "detected": detection_summary(facts),
        "handoff_artifacts": {},
        "agents": [],
        "next_steps": [
            "Clarify requirements and identify affected services or paths.",
            "Rerun orchestration with --service-scope affected plus --service or --path.",
            "Create agent-run archives only after affected services are known.",
        ],
    }


def service_artifacts(base: str, services: list[str] | None, merged_members: list[str] | None = None) -> dict:
    result: dict[str, dict[str, str]] = {}
    for service in services or []:
        slug = service_slug(service)
        service_base = f"{base}/service-plans/{slug}"
        entry: dict[str, object] = {
            "service_dir": service,
            "service_design": f"{base}/service-designs/{slug}.md",
            "service_plan": f"{service_base}/implementation-plan.md",
            "code_agent": f"{service_base}/code-agent.md",
            "review_requests_dir": f"{service_base}/review-requests",
            "reviews_dir": f"{service_base}/reviews",
            "test_review_request": f"{service_base}/review-requests/R2-test-review-request.md",
            "test_review": f"{service_base}/reviews/R2-test-review.md",
            "implementation_review_request": f"{service_base}/review-requests/R3-implementation-review-request.md",
            "implementation_review": f"{service_base}/reviews/R3-implementation-review.md",
            "implementation_manifest": f"{service_base}/implementation-manifest.md",
            "test_impact_plan": f"{service_base}/test-impact-plan.json",
            "red_test_evidence": f"{service_base}/red-test-evidence.txt",
            "test_evidence": f"{service_base}/unit-test-evidence.txt",
            "coverage_matrix": f"{service_base}/coverage-matrix.md",
            "business_review": f"{service_base}/business-review.md",
            "rework_dir": service_base,
            "rework_pattern": f"{service_base}/rework-NNN.md",
        }
        if merged_members and service == MERGED_SERVICE_ID:
            entry["merged_members"] = list(merged_members)
        result[service] = entry
    return result


# Derived from the role registry so the template file set tracks the canonical
# roles automatically (insertion order follows ROLE_REGISTRY, unchanged).
ROLE_TEMPLATE_FILES = {role: f"{role}.md" for role in agent_roles.ROLE_REGISTRY}
DEFAULT_COMPLETION_MODE = "dispatcher-confirmed"
DEFAULT_EXECUTION_MODEL = "coordinator-only-dispatch"


def role_templates(base: str) -> dict[str, str]:
    return {
        role: f"{base}/agent-roles/{filename}"
        for role, filename in ROLE_TEMPLATE_FILES.items()
    }


def artifacts(slug: str, agent_run_dir: str | None = None, run_date: str | None = None, services: list[str] | None = None, merged_members: list[str] | None = None) -> dict:
    base = (agent_run_dir or f"docs/agent-runs/{default_run_id(slug, run_date)}").replace("\\", "/")
    handoffs = f"{base}/handoffs"
    evidence = f"{base}/evidence"
    review_requests = f"{base}/review-requests"
    reviews = f"{base}/reviews"
    return {
        "agent_run_dir": base,
        "run_state": f"{base}/run-state.json",
        "workflow_plan": f"{base}/workflow-plan.json",
        "artifact_registry": f"{base}/artifact-registry.json",
        "agent_schedule": f"{base}/agent-schedule.json",
        "run_summary": f"{base}/run-summary.json",
        "run_summary_md": f"{base}/run-summary.md",
        "execution_trace": f"{base}/execution-trace.json",
        "exec_plan": f"{base}/exec-plan.md",
        "prepare_status": f"{base}/prepare.json",
        "requirements": f"{handoffs}/01-requirements-clarifier.md",
        "use_cases": f"{handoffs}/02-use-case-designer.md",
        "test_plan": f"{handoffs}/03-test-case-developer.md",
        "implementation_plan": f"{handoffs}/04-code-developer.md",
        "role_templates_dir": f"{base}/agent-roles",
        "role_templates": role_templates(base),
        "service_designs_dir": f"{base}/service-designs",
        "service_design_pattern": f"{base}/service-designs/<service>.md",
        "proposed_memory_updates": f"{base}/proposed-memory-updates.md",
        "review_requests_dir": review_requests,
        "reviews_dir": reviews,
        "design_review_request": f"{review_requests}/R1-design-review-request.md",
        "design_review": f"{reviews}/R1-design-review.md",
        "test_review_request": f"{review_requests}/R2-test-review-request.md",
        "test_review": f"{reviews}/R2-test-review.md",
        "implementation_review_request": f"{review_requests}/R3-implementation-review-request.md",
        "implementation_review": f"{reviews}/R3-implementation-review.md",
        "rework_dir": f"{base}/rework",
        "rework_pattern": f"{base}/rework/rework-NNN.md",
        "contracts_dir": f"{base}/contracts",
        "contract_pattern": f"{base}/contracts/<contract-id>.md",
        "knowledge_graph_status": f"{evidence}/knowledge-graph-refresh.json",
        "dependency_report": f"{evidence}/cross-service-dependencies.json",
        "impact_summary": f"{evidence}/impact-summary.md",
        "impact_evidence": f"{evidence}/impact-analysis.json",
        "test_impact_plan": f"{evidence}/test-impact-plan.json",
        "context_pack_pattern": f"{base}/context-packs/<agent-or-task>.json",
        "implementation_manifest": f"{evidence}/implementation-manifest.md",
        "requirements_archive": f"{base}/requirements-archive.md",
        "red_test_evidence": f"{evidence}/red-test.txt",
        "green_test_evidence": f"{evidence}/green-test.txt",
        "verification_evidence": f"{evidence}/verification.txt",
        "phase_coverage": f"{evidence}/phase-coverage.json",
        "strict_guard_result": f"{evidence}/strict-guard.json",
        "coverage_matrix": f"{evidence}/coverage-matrix.md",
        "business_review": f"{evidence}/business-review.md",
        "service_plans": service_artifacts(base, services, merged_members),
}


def role_template_key(agent_name: str) -> str:
    return agent_roles.resolve_role_key(agent_name)


def with_role_template(agent: dict, artifact_paths: dict) -> dict:
    key = role_template_key(str(agent.get("name", "")))
    templates = artifact_paths.get("role_templates", {})
    if key and key in templates:
        agent = dict(agent)
        agent["role_template"] = templates[key]
        agent["role_template_key"] = key
    return agent


def agent_plan(selected_mode: str, artifact_paths: dict, services: list[str] | None = None) -> list[dict]:
    if selected_mode == "discovery":
        return []
    service_plans = artifact_paths.get("service_plans", {})
    has_service_slices = bool(service_plans and selected_mode not in {"single", "single-review"})
    agents: list[dict] = []
    agents.extend([
        {
            "name": "requirements-clarifier",
            "owns": ["goal", "non-goals", "constraints", "impact summary", "acceptance criteria", "open questions"],
            "inputs": ["user request", "knowledge graph summary", artifact_paths["dependency_report"]],
            "outputs": [artifact_paths["requirements"], artifact_paths["impact_summary"], artifact_paths["impact_evidence"]],
            "gate": "Behavior/API/data/test-impacting open questions and bounded impact summary gaps must be resolved.",
        },
        {
            "name": "use-case-designer",
            "owns": ["happy paths", "failure paths", "cross-service flow", "contracts", "data effects"],
            "inputs": [
                artifact_paths["requirements"],
                artifact_paths["impact_summary"],
                "knowledge graph summary",
                artifact_paths["dependency_report"],
            ],
            "outputs": [artifact_paths["use_cases"]],
            "gate": "Every acceptance criterion maps to a use case or is explicitly deferred.",
        },
    ])
    if not has_service_slices:
        agents.append(
            {
                "name": "test-case-developer",
                "owns": ["test strategy", "first red test", "contract tests", "Maven test scope"],
                "inputs": [artifact_paths["requirements"], artifact_paths["use_cases"], *agent_roles.role_skills("test-case-developer")],
                "outputs": [artifact_paths["test_plan"]],
                "gate": "First red test must be written and observed failing for the expected reason.",
            }
        )
    design_reviewer_name = "single-reviewer-r1-design" if selected_mode == "single-review" else "design-reviewer"
    test_reviewer_name = "single-reviewer-r2-test" if selected_mode == "single-review" else "test-reviewer"
    implementation_reviewer_name = (
        "single-reviewer-r3-implementation" if selected_mode == "single-review" else "implementation-reviewer"
    )
    agents.extend([
        {
            "name": design_reviewer_name,
            "owns": ["semantic review of requirements, AC completeness, affected modules, security-sensitive paths, reference patterns"],
            "inputs": [
                artifact_paths["design_review_request"],
                artifact_paths["requirements"],
                artifact_paths["impact_summary"],
                artifact_paths["use_cases"],
                "task request",
                "project reference patterns",
            ],
            "outputs": [artifact_paths["design_review"]],
            "gate": "Blocked findings become rework before implementation planning continues.",
        },
        {
            "name": test_reviewer_name,
            "owns": ["semantic review of red tests, happy/failure paths, security and contract coverage"],
            "inputs": (
                [
                    artifact_paths["test_review_request"],
                    artifact_paths["impact_summary"],
                    artifact_paths["dependency_report"],
                ]
                + [
                    item
                    for paths in service_plans.values()
                    for item in (paths["service_design"], paths["red_test_evidence"], paths["test_impact_plan"])
                ]
                if has_service_slices
                else [
                    artifact_paths["test_review_request"],
                    artifact_paths["requirements"],
                    artifact_paths["impact_summary"],
                    artifact_paths["use_cases"],
                    artifact_paths["test_plan"],
                    artifact_paths["test_impact_plan"],
                ]
            ),
            "outputs": [artifact_paths["test_review"]],
            "gate": "Production code waits until test review is approved or rework is routed.",
        },
        {
            "name": "implementation-planner",
            "owns": ["implementation plan refinement", "dispatch sequencing", "review-driven rework routing"],
            "inputs": [
                artifact_paths["requirements"],
                artifact_paths["impact_summary"],
                artifact_paths["use_cases"],
                artifact_paths["design_review"],
                artifact_paths["dependency_report"],
            ],
            "outputs": [artifact_paths["exec_plan"]],
            "gate": "Must run after independent R1 review; TDD waits until the planner records dispatch-ready plan evidence.",
        },
    ])
    if has_service_slices:
        for service, paths in service_plans.items():
            agents.append(
                {
                    "name": f"service-designer-{service_slug(service)}",
                    "owns": [f"service design slice for {service}", "allowed edit scope", "service-local TDD plan"],
                    "inputs": [
                        artifact_paths["requirements"],
                        artifact_paths["impact_summary"],
                        artifact_paths["use_cases"],
                        artifact_paths["dependency_report"],
                        paths["service_plan"],
                    ],
                    "outputs": [paths["service_design"]],
                    "gate": "Produce the service-local design slice before service-local TDD or implementation tasks may proceed.",
                }
            )
            agents.append(
                {
                    "name": f"test-case-developer-{service_slug(service)}",
                    "owns": [f"service-local first red test for {service}", "service-local TDD evidence"],
                    "inputs": [
                        artifact_paths["impact_summary"],
                        paths["service_design"],
                        paths["service_plan"],
                        paths["test_impact_plan"],
                        artifact_paths["dependency_report"],
                    ],
                    "outputs": [
                        paths["red_test_evidence"],
                        paths["test_impact_plan"],
                    ],
                    "gate": "Write only the service-local red test and evidence; production code stays locked until implementation gate.",
                }
            )
            agents.append(
                {
                    "name": f"code-developer-{service_slug(service)}",
                    "owns": [f"implementation for {service}", "service-local tests", "service-local verification evidence"],
                    "inputs": [
                        artifact_paths["impact_summary"],
                        paths["service_design"],
                        paths["service_plan"],
                        paths["test_impact_plan"],
                        artifact_paths["dependency_report"],
                        paths["red_test_evidence"],
                        "failing tests for this service",
                    ],
                    "outputs": [
                        paths["code_agent"],
                        paths["implementation_manifest"],
                        paths["test_evidence"],
                        paths["coverage_matrix"],
                        paths["business_review"],
                    ],
                    "gate": "May edit only its assigned service/module and shared files explicitly listed in the service plan.",
                }
            )
            agents.append(
                {
                    "name": f"implementation-reviewer-{service_slug(service)}",
                    "owns": [
                        f"independent semantic implementation review for {service}",
                        "service-local completeness",
                        "service-local tests and business logic risks",
                    ],
                    "inputs": [
                        paths["implementation_review_request"],
                        artifact_paths["requirements"],
                        artifact_paths["impact_summary"],
                        artifact_paths["use_cases"],
                        artifact_paths["test_plan"],
                        paths["service_design"],
                        paths["service_plan"],
                        paths["implementation_manifest"],
                        paths["coverage_matrix"],
                        paths["business_review"],
                    ],
                    "outputs": [paths["implementation_review"]],
                    "gate": "Must run as an independent reviewer agent with no inherited developer chat context.",
                }
            )
    else:
        agents.append({
            "name": "code-developer",
            "owns": ["minimal implementation", "red-green-refactor", "verification"],
            "inputs": [
                artifact_paths["requirements"],
                artifact_paths["use_cases"],
                artifact_paths["implementation_plan"],
                artifact_paths["test_plan"],
                "failing tests",
            ],
            "outputs": [artifact_paths["implementation_plan"], "code changes", "test results"],
            "gate": "Must be a different agent from design and test roles; all narrow and broadened verification commands pass.",
        })
    agents.append({
        "name": implementation_reviewer_name,
        "owns": ["semantic review of implementation completeness, code/test depth, security risks, and project pattern consistency"],
        "inputs": [
            artifact_paths["implementation_review_request"],
            artifact_paths["requirements"],
            artifact_paths["impact_summary"],
            artifact_paths["use_cases"],
            artifact_paths["test_plan"],
            artifact_paths["test_impact_plan"],
            artifact_paths["dependency_report"],
            artifact_paths["implementation_manifest"],
        ],
        "outputs": [artifact_paths["implementation_review"]],
        "gate": "Findings create rework items; completion cannot proceed while implementation review is blocked.",
    })
    agents.append({
        "name": "coverage-reviewer",
        "owns": ["design coverage matrix", "unit test evidence check", "business logic review"],
        "inputs": [
            artifact_paths["requirements"],
            artifact_paths["impact_summary"],
            artifact_paths["use_cases"],
            artifact_paths["test_plan"],
            artifact_paths["implementation_plan"],
            artifact_paths["dependency_report"],
            artifact_paths["implementation_manifest"],
        ],
        "outputs": [
            artifact_paths["implementation_manifest"],
            artifact_paths["coverage_matrix"],
            artifact_paths["business_review"],
            artifact_paths["verification_evidence"],
            artifact_paths["requirements_archive"],
        ],
        "gate": "Every acceptance criterion maps to use cases, required implementation artifacts, tests, code refs, and business review evidence.",
    })
    return [with_role_template(agent, artifact_paths) for agent in agents]


def phase_for_agent(name: str) -> str:
    # Intentionally NOT a thin wrapper over agent_roles.resolve_role_key: a
    # semantic-reviewer name must disambiguate to r1/r2/r3 by its
    # design/test/implementation keyword, but
    # `role_to_phase(resolve_role_key(name))` collapses every reviewer onto the
    # single canonical `r1-review` phase. The explicit role-prefix precedence
    # below (code-developer / coverage over an incidental service-slug keyword,
    # so e.g. "code-developer-payment-test" -> `implement`) now matches
    # resolve_role_key's ordering, so the only remaining divergence is reviewer
    # disambiguation. See tests.PhaseFunctionTests and
    # harness-role-phase-convergence-plan Step 3.
    if "requirements" in name or "clarifier" in name:
        return "clarify"
    if "use-case" in name or "designer" in name:
        return "design"
    if "planner" in name:
        return "plan"
    if "code-developer" in name:
        return "implement"
    if "coverage" in name:
        return "completion"
    if "reviewer" in name or "review" in name:
        if "design" in name:
            return "r1-review"
        if "test" in name:
            return "r2-review"
        return "r3-review"
    if "test" in name:
        return "tdd-red"
    return "plan"


def depends_on_for_phase(phase: str) -> list[str]:
    # Single source of truth: agent_roles.PHASE_REGISTRY. The ["plan"] default
    # for unknown phases is preserved by agent_roles.depends_on_for_phase.
    return agent_roles.depends_on_for_phase(phase)


def role_group_for_phase(phase: str) -> str:
    return agent_roles.PHASE_ROLE_GROUPS.get(phase, "coordination")


REVIEWER_SUBAGENT_TYPE_ENV = "E2E_HARNESS_REVIEWER_SUBAGENT_TYPE"


def reviewer_subagent_type() -> str:
    """Project-supplied reviewer subagent type, or the portable default.

    Set E2E_HARNESS_REVIEWER_SUBAGENT_TYPE to a runtime subagent your project
    actually has (e.g. a dedicated code-reviewer agent) to route R1/R2/R3 and
    coverage reviews to it. Left unset, every task stays on general-purpose so
    the harness remains runtime-portable.
    """
    return str(os.environ.get(REVIEWER_SUBAGENT_TYPE_ENV, "") or "").strip() or "general-purpose"


def runtime_subagent_type_for_phase(phase: str) -> str:
    # Route from the canonical role's declared subagent_kind so declaration and
    # routing stay in one place (see agent_roles.phase_subagent_kind).
    if agent_roles.phase_subagent_kind(phase) == "reviewer":
        return reviewer_subagent_type()
    return "general-purpose"


def agent_schedule(selected_mode: str, services: list[str], agents: list[dict]) -> dict:
    tasks: list[dict] = []
    for index, agent in enumerate(agents, start=1):
        name = str(agent.get("name", f"agent-{index}"))
        phase = phase_for_agent(name)
        service = ""
        for candidate in services:
            if service_slug(candidate) in name:
                service = candidate
                break
        tasks.append(
            {
                "id": f"T{index:02d}",
                "agent": name,
                "phase": phase,
                "role_group": role_group_for_phase(phase),
                "role_template": agent.get("role_template", ""),
                "role_template_key": agent.get("role_template_key", ""),
                "service": service,
                "parallel_group": f"service:{service}" if service and phase in {"tdd-red", "implement", "r3-review"} else phase,
                "depends_on_phases": depends_on_for_phase(phase),
                "inputs": agent.get("inputs", []),
                "outputs": agent.get("outputs", []),
                "status": "planned",
                "requires_runtime_dispatch": True,
                "dispatch_contract": "fresh-subagent",
                "runtime_subagent_type": runtime_subagent_type_for_phase(phase),
            }
        )
    return {
        "schema": "e2e-dev-harness.agent-schedule.v1",
        "selected_mode": selected_mode,
        "completion_mode": DEFAULT_COMPLETION_MODE,
        "execution_model": DEFAULT_EXECUTION_MODEL,
        "require_role_templates": True,
        "services": services,
        "coordination": "machine-readable task board; agents update task status and artifact hashes instead of exchanging long free-form chat.",
        "tasks": tasks,
    }


def multi_agent_decision(selected_mode: str, services: list[str], reasons: list[str]) -> dict:
    criteria = [
        "multiple affected services/modules",
        "HTTP/DMQ/shared contract boundary",
        "database/schema/config/security/payment/refund risk",
        "large or design-heavy implementation context",
        "user explicitly requested split agents",
    ]
    evidence = list(reasons)
    if services:
        evidence.append("selected services/modules: " + ", ".join(services))
    return {
        "use_multi_agent": selected_mode == "multi",
        "selected_mode": selected_mode,
        "criteria": criteria,
        "evidence": evidence,
        "required_when_multi": [
            "one service-plans/<service>/implementation-plan.md per affected service/module",
            "one service-plans/<service>/code-agent.md handoff per code agent",
            "service-local implementation manifest, tests, coverage, business review",
            "service-local R2/R3 reviews plus global R1/R2/R3 review requests",
            "completion gate passes --require-handoffs for multi-service/split-agent runs",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument(
        "--mode",
        choices=AGENT_MODES,
        default=env_default("E2E_DEV_HARNESS_AGENT_MODE", "E2E_DEV_WORKFLOW_AGENT_MODE", "auto"),
    )
    parser.add_argument("--design-doc", type=Path)
    parser.add_argument("--agent-run-dir", help="Archive directory for generated agent run files.")
    parser.add_argument("--run-date", help="Date prefix for default agent run directory, YYYY-MM-DD.")
    parser.add_argument("--path", action="append", help="Path that may be touched; can be repeated.")
    parser.add_argument("--service", action="append", help="Affected service directory or service name; can be repeated.")
    parser.add_argument("--service-scope", choices=SERVICE_SCOPES, default=env_default("E2E_DEV_HARNESS_SERVICE_SCOPE", "E2E_DEV_WORKFLOW_SERVICE_SCOPE", "auto"))
    parser.add_argument("--dependency-report", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not repo.exists():
        print(f"Repo not found: {repo}", file=sys.stderr)
        return 2

    design_path = args.design_doc
    if design_path and not design_path.is_absolute():
        design_path = repo / design_path
    design_text = read_design(design_path)
    facts = detect(repo)
    design_is_template = bool(design_path and "template" in design_path.stem.lower())
    dependency_report = args.dependency_report
    if dependency_report and not dependency_report.is_absolute():
        dependency_report = repo / dependency_report
    dependency_services = services_from_dependency_report(dependency_report)
    design_services = [] if design_is_template else services_from_design(design_text, facts)
    requested_services = args.service
    if args.service_scope == "auto" and not requested_services and not args.path:
        if dependency_services:
            requested_services = dependency_services
        elif design_services:
            requested_services = design_services
    elif args.service_scope == "affected" and not requested_services and not args.path and design_services:
        requested_services = design_services
    services, resolved_service_scope = select_services(facts, requested_services, args.path, args.service_scope)
    unmatched_services = unmatched_requested_services(facts, requested_services)
    if unmatched_services:
        result = {
            "repo": str(repo),
            "requested_mode": args.mode,
            "selected_mode": "blocked",
            "requested_service_scope": args.service_scope,
            "resolved_service_scope": resolved_service_scope,
            "requested_services": requested_services or [],
            "design_selected_services": design_services,
            "dependency_report": str(dependency_report) if dependency_report else None,
            "requested_paths": args.path or [],
            "selected_services": services,
            "unmatched_requested_services": unmatched_services,
            "blocked": True,
            "blocked_reasons": [
                "Requested services were not found in service_candidates: " + ", ".join(unmatched_services)
            ],
            "detected": detection_summary(facts),
            "handoff_artifacts": {},
            "agents": [],
        }
        text = json.dumps(result, indent=2, ensure_ascii=False)
        print(text)
        if args.status_file:
            args.status_file.parent.mkdir(parents=True, exist_ok=True)
            args.status_file.write_text(text + "\n", encoding="utf-8")
        return 2
    if resolved_service_scope == "discovery":
        result = discovery_result(repo, args.mode, args.service_scope, requested_services, args.path, facts)
        text = json.dumps(result, indent=2, ensure_ascii=False)
        if args.json:
            print(text)
        else:
            print("Orchestration mode: discovery")
            print("Next steps:")
            for step in result["next_steps"]:
                print(f"- {step}")
        if args.status_file:
            args.status_file.parent.mkdir(parents=True, exist_ok=True)
            args.status_file.write_text(text + "\n", encoding="utf-8")
        return 0
    mode_facts = mode_facts_for_service_scope(facts, services, resolved_service_scope)
    selected, reasons = choose_mode(args.mode, mode_facts, design_text, design_is_template)
    slug = feature_slug(design_path)
    artifact_paths = artifacts(slug, args.agent_run_dir, args.run_date, services)
    result = {
        "repo": str(repo),
        "requested_mode": args.mode,
        "selected_mode": selected,
        "requested_service_scope": args.service_scope,
        "resolved_service_scope": resolved_service_scope,
        "requested_services": requested_services or [],
        "design_selected_services": design_services,
        "requested_paths": args.path or [],
        "selected_services": services,
        "dependency_report": str(dependency_report) if dependency_report else None,
        "reasons": reasons,
        "detected": {
            "service_candidates": facts.get("service_candidates", []),
            "multi_service": facts.get("multi_service", False),
            "design_docs_or_media_count": facts.get("design_docs_or_media_count", 0),
            "spring_entrypoints": facts.get("spring_entrypoints", []),
        },
        "handoff_artifacts": artifact_paths,
        "multi_agent_decision": multi_agent_decision(selected, services, reasons),
        "agents": agent_plan(selected, artifact_paths, services),
        "notes": [
            "Use files as handoff boundaries; do not rely on chat memory.",
            "For multi-service or multi-module work, keep each service/module implementation plan and code agent handoff separate.",
            "Use superpowers:brainstorming before implementation planning.",
            "Use superpowers:test-driven-development before production-code edits.",
        ],
    }

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json:
        print(text)
    else:
        print(f"Orchestration mode: {selected}")
        print("Reasons:")
        for reason in reasons:
            print(f"- {reason}")
        print("Handoff artifacts:")
        for name, path in artifact_paths.items():
            print(f"- {name}: {path}")
        print("Agents:")
        for agent in result["agents"]:
            print(f"- {agent['name']}: {', '.join(agent['owns'])}")

    if args.status_file:
        args.status_file.parent.mkdir(parents=True, exist_ok=True)
        args.status_file.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
