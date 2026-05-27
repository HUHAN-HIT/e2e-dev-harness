#!/usr/bin/env python3
"""Recommend single-agent or multi-agent orchestration for Spring 6 work."""

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
    "影响模块",
    "影响服务",
)


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


def requested_services_from_design(text: str) -> list[str]:
    requested: list[str] = []
    seen: set[str] = set()
    for title, body in design_sections(text).items():
        if not any(keyword in title for keyword in AFFECTED_SECTION_KEYWORDS):
            continue
        for line in body.splitlines():
            if not re.match(r"\s*[-*]\s+", line):
                continue
            item = re.sub(r"^\s*[-*]\s+", "", line).strip()
            service = normalize_path(item.split(":", 1)[0].split(" - ", 1)[0].split(" ", 1)[0])
            if service and service.lower() not in {"none", "n/a"} and service not in seen:
                seen.add(service)
                requested.append(service)
    return requested


def services_from_design(text: str, facts: dict) -> list[str]:
    candidates = [normalize_path(service) for service in facts.get("service_candidates", [])]
    selected: list[str] = []
    seen: set[str] = set()
    for requested in requested_services_from_design(text):
        matched = match_requested_service(candidates, requested)
        if matched and matched not in seen:
            seen.add(matched)
            selected.append(matched)
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


def choose_mode(requested: str, facts: dict, design_text: str, design_is_template: bool) -> tuple[str, list[str]]:
    reasons = mode_reasons(facts, design_text, design_is_template)
    if requested == "single-review":
        actionable_reasons = actionable_mode_reasons(reasons)
        if actionable_reasons:
            return "multi", ["single-review escalated to multi: " + "; ".join(actionable_reasons[:3])] + reasons
        return requested, [f"mode explicitly set to {requested}"]
    if requested in EXPLICIT_AGENT_MODES:
        return requested, [f"mode explicitly set to {requested}"]

    actionable_reasons = actionable_mode_reasons(reasons)
    if actionable_reasons:
        return "multi", reasons
    return "single", ["single service and low-risk design context detected"]


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


def service_artifacts(base: str, services: list[str] | None) -> dict:
    result: dict[str, dict[str, str]] = {}
    for service in services or []:
        slug = service_slug(service)
        service_base = f"{base}/service-plans/{slug}"
        result[service] = {
            "service_dir": service,
            "service_plan": f"{service_base}/implementation-plan.md",
            "code_agent": f"{service_base}/code-agent.md",
            "review_requests_dir": f"{service_base}/review-requests",
            "reviews_dir": f"{service_base}/reviews",
            "test_review_request": f"{service_base}/review-requests/R2-test-review-request.md",
            "test_review": f"{service_base}/reviews/R2-test-review.md",
            "implementation_review_request": f"{service_base}/review-requests/R3-implementation-review-request.md",
            "implementation_review": f"{service_base}/reviews/R3-implementation-review.md",
            "implementation_manifest": f"{service_base}/implementation-manifest.md",
            "test_evidence": f"{service_base}/unit-test-evidence.txt",
            "coverage_matrix": f"{service_base}/coverage-matrix.md",
            "business_review": f"{service_base}/business-review.md",
            "rework_dir": service_base,
            "rework_pattern": f"{service_base}/rework-NNN.md",
        }
    return result


def artifacts(slug: str, agent_run_dir: str | None = None, run_date: str | None = None, services: list[str] | None = None) -> dict:
    base = (agent_run_dir or f"docs/agent-runs/{default_run_id(slug, run_date)}").replace("\\", "/")
    handoffs = f"{base}/handoffs"
    evidence = f"{base}/evidence"
    review_requests = f"{base}/review-requests"
    reviews = f"{base}/reviews"
    return {
        "agent_run_dir": base,
        "run_state": f"{base}/run-state.json",
        "artifact_registry": f"{base}/artifact-registry.json",
        "exec_plan": f"{base}/exec-plan.md",
        "prepare_status": f"{base}/prepare.json",
        "requirements": f"{handoffs}/01-requirements-clarifier.md",
        "use_cases": f"{handoffs}/02-use-case-designer.md",
        "test_plan": f"{handoffs}/03-test-case-developer.md",
        "implementation_plan": f"{handoffs}/04-code-developer.md",
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
        "implementation_manifest": f"{evidence}/implementation-manifest.md",
        "requirements_archive": f"{base}/requirements-archive.md",
        "red_test_evidence": f"{evidence}/red-test.txt",
        "green_test_evidence": f"{evidence}/green-test.txt",
        "verification_evidence": f"{evidence}/verification.txt",
        "coverage_matrix": f"{evidence}/coverage-matrix.md",
        "business_review": f"{evidence}/business-review.md",
        "service_plans": service_artifacts(base, services),
    }


def agent_plan(selected_mode: str, artifact_paths: dict, services: list[str] | None = None) -> list[dict]:
    if selected_mode == "discovery":
        return []
    agents: list[dict] = []
    if selected_mode in {"single", "single-review"}:
        review_owner = "single-reviewer phase-boundary invocations" if selected_mode == "single-review" else "independent reviewer agents"
        agents.append(
            {
                "name": "single-agent",
                "owns": ["requirements", "impact summary", "use cases", "tests", "implementation"],
                "inputs": ["user request", "knowledge graph summary", artifact_paths["dependency_report"]],
                "outputs": [
                    artifact_paths["exec_plan"],
                    artifact_paths["requirements"],
                    artifact_paths["impact_summary"],
                    artifact_paths["impact_evidence"],
                    artifact_paths["use_cases"],
                    artifact_paths["test_plan"],
                    artifact_paths["implementation_plan"],
                    artifact_paths["implementation_manifest"],
                    artifact_paths["coverage_matrix"],
                    artifact_paths["business_review"],
                    artifact_paths["verification_evidence"],
                ],
                "gate": f"Must not write semantic review reports; {review_owner} own R1/R2/R3 review artifacts.",
            }
        )
    else:
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
        {
            "name": "test-case-developer",
            "owns": ["test strategy", "first red test", "contract tests", "Maven test scope"],
            "inputs": [artifact_paths["requirements"], artifact_paths["use_cases"], "superpowers:test-driven-development"],
            "outputs": [artifact_paths["test_plan"]],
            "gate": "First red test must be written and observed failing for the expected reason.",
        },
    ])
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
            "inputs": [
                artifact_paths["test_review_request"],
                artifact_paths["requirements"],
                artifact_paths["impact_summary"],
                artifact_paths["use_cases"],
                artifact_paths["test_plan"],
            ],
            "outputs": [artifact_paths["test_review"]],
            "gate": "Production code waits until test review is approved or rework is routed.",
        },
    ])
    service_plans = artifact_paths.get("service_plans", {})
    if service_plans and selected_mode not in {"single", "single-review"}:
        for service, paths in service_plans.items():
            agents.append(
                {
                    "name": f"code-developer-{service_slug(service)}",
                    "owns": [f"implementation for {service}", "service-local tests", "service-local verification evidence"],
                    "inputs": [
                        artifact_paths["requirements"],
                        artifact_paths["impact_summary"],
                        artifact_paths["use_cases"],
                        artifact_paths["test_plan"],
                        paths["service_plan"],
                        artifact_paths["dependency_report"],
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
                        paths["service_plan"],
                        paths["implementation_manifest"],
                        paths["coverage_matrix"],
                        paths["business_review"],
                    ],
                    "outputs": [paths["implementation_review"]],
                    "gate": "Must run as an independent reviewer agent with no inherited developer chat context.",
                }
            )
    elif selected_mode not in {"single", "single-review"}:
        agents.append({
            "name": "code-developer",
            "owns": ["minimal implementation", "red-green-refactor", "verification"],
            "inputs": [artifact_paths["requirements"], artifact_paths["use_cases"], artifact_paths["test_plan"], "failing tests"],
            "outputs": [artifact_paths["implementation_plan"], "code changes", "test results"],
            "gate": "All narrow and broadened verification commands pass.",
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
    return agents


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
        default=os.environ.get("E2E_DEV_WORKFLOW_AGENT_MODE", "auto"),
    )
    parser.add_argument("--design-doc", type=Path)
    parser.add_argument("--agent-run-dir", help="Archive directory for generated agent run files.")
    parser.add_argument("--run-date", help="Date prefix for default agent run directory, YYYY-MM-DD.")
    parser.add_argument("--path", action="append", help="Path that may be touched; can be repeated.")
    parser.add_argument("--service", action="append", help="Affected service directory or service name; can be repeated.")
    parser.add_argument("--service-scope", choices=SERVICE_SCOPES, default=os.environ.get("E2E_DEV_WORKFLOW_SERVICE_SCOPE", "auto"))
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
