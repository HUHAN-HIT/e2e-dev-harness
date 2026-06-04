"""Service-design command facade."""

from __future__ import annotations

import re
from pathlib import Path

import clarification_gate
from common import posix
import orchestration_plan
import preflight as preflight_checks
import service_design_gate
from e2e_harness.cli.status import write_status
from e2e_harness.engine import state_store


def _as_repo(path: Path) -> Path:
    repo = Path(path).resolve()
    if not repo.exists():
        raise FileNotFoundError(f"Repo not found: {repo}")
    return repo


def _resolve_repo_path(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    path = Path(path)
    return path if path.is_absolute() else repo / path


def _require_repo_path(repo: Path, path: Path | None, label: str) -> Path:
    resolved = _resolve_repo_path(repo, path)
    if resolved is None:
        raise ValueError(f"{label} is required")
    return resolved


def _optional_text(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def service_tokens(service: str) -> list[str]:
    values = {service.lower(), orchestration_plan.service_slug(service).lower(), Path(service).name.lower()}
    for value in list(values):
        values.update(part for part in value.replace("_", "-").replace("/", "-").split("-") if len(part) > 2)
    return sorted(values, key=len, reverse=True)


def acceptance_items_from_text(markdown: str) -> list[dict[str, str]]:
    body = clarification_gate.section_text(markdown, clarification_gate.REQUIRED["acceptance"]) if markdown else None
    if not body:
        return []
    results: list[dict[str, str]] = []
    used: set[str] = set()
    next_index = 1
    for line in body.splitlines():
        stripped = line.strip()
        content = clarification_gate.ACCEPTANCE_LINE_RE.match(line)
        item_text = content.group(1).strip() if content else stripped
        if not item_text or set(item_text) <= {"|", "-", " "}:
            continue
        id_match = clarification_gate.ACCEPTANCE_ID_RE.match(item_text)
        if id_match:
            ac_id = clarification_gate.normalize_acceptance_id(item_text)
            description = item_text[id_match.end():].strip(" :-\t") or item_text
        else:
            while f"AC-{next_index}" in used:
                next_index += 1
            ac_id = f"AC-{next_index}"
            next_index += 1
            description = item_text
        if ac_id not in used:
            results.append({"id": ac_id, "text": description})
            used.add(ac_id)
    return results


def one_line_section(markdown: str, key: str) -> str:
    patterns = clarification_gate.REQUIRED.get(key, [])
    body = clarification_gate.section_text(markdown, patterns) if markdown and patterns else None
    for line in (body or "").splitlines():
        normalized = line.strip().strip("-* ")
        if normalized:
            return normalized
    return ""


def service_test_class_name(service: str) -> str:
    slug = orchestration_plan.service_slug(service)
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", slug) if part]
    base = "".join(part[:1].upper() + part[1:] for part in parts) or "Service"
    return f"{base}Test"


def service_acceptance_rows(service: str, global_design_text: str) -> str:
    items = acceptance_items_from_text(global_design_text)
    if not items:
        return f"| AC-1 | Derived from global design after clarification | {service} service responsibility to be confirmed during service-design gate | {service_test_class_name(service)} |\n"
    tokens = service_tokens(service)
    matched = [item for item in items if any(token in item["text"].lower() for token in tokens)]
    selected = matched or items
    test_class = service_test_class_name(service)
    return "".join(
        f"| {item['id']} | {item['text']} | {service} owns the service-local behavior, integration points, or non-applicability decision for this AC | {test_class} |\n"
        for item in selected
    )


def service_scope_excerpt(service: str, global_design_text: str) -> str:
    scope = one_line_section(global_design_text, "scope")
    return scope or f"{service} service/module slice from the global design."


def service_design_template(
    service: str,
    global_design: str,
    global_design_text: str = "",
    merged_members: list[str] | None = None,
) -> str:
    ac_rows = service_acceptance_rows(service, global_design_text)
    test_class = service_test_class_name(service)
    intent = one_line_section(global_design_text, "restated_intent") or one_line_section(global_design_text, "goal")
    service_scope = service_scope_excerpt(service, global_design_text)
    members = merged_members or [service]
    module_label = ", ".join(members) if merged_members else service
    allowed_scope = "\n".join(f"  - {member}/" for member in members)
    maven_block = "\n".join(f"- Required Maven command: mvn -pl {member} -am test" for member in members)
    test_impact_block = "\n".join(
        f"- Service-local test impact plan: mvn -pl {member} -am test" for member in members
    )
    return f"""# Service Design Slice: {service}

Global design: {global_design}

Primary development contract: this service design is the primary input for the service code agent. Keep global context bounded; copy only the ACs, constraints, and dependency facts this service needs.

## Service Scope
- Service/module: {module_label}
- Allowed edit scope:
{allowed_scope}
- Explicitly out of scope: other services unless listed in Dependency Boundary

## Global Intent Summary
- Restated user intent: {intent or 'See global design and requirements handoff.'}
- This service's responsibility: {service_scope}

## Mapped Acceptance Criteria
| AC | global requirement | service responsibility | local tests |
| --- | --- | --- | --- |
{ac_rows.rstrip()}

## Runtime Path
- Entry point: GitNexus-confirmed entry point -> {service_test_class_name(service).removesuffix('Test')}#method
- Service/domain path: {service_test_class_name(service).removesuffix('Test')}#method -> domain/service collaborator
- Repository/client/sender path: repository/client/sender decided by service-design gate
- Output or side effect: service-local state, API response, or event named in mapped ACs

## Local Sequence
```mermaid
sequenceDiagram
    participant Test as {test_class}
    participant Entry as {service} entry point
    participant Domain as service/domain logic
    participant Edge as repository/client/sender
    Test->>Entry: Exercise mapped AC rows
    Entry->>Domain: Execute service-local behavior
    Domain->>Edge: Persist, call, or publish declared side effect
    Edge-->>Domain: Result or acknowledgement
    Domain-->>Entry: Service-local outcome
    Entry-->>Test: Assertion target
```

## Service-local TDD Plan
- First red test: {test_class} should fail before implementation
- Expected failure: missing mapped service-local behavior
- Minimal green implementation: implement only the mapped AC rows above
- Refactor checks: keep edits inside allowed scope and declared dependency boundary
{maven_block}

## Dependency Boundary
- Independent service change: generated starter requires service owner confirmation before code dispatch
- HTTP/API dependencies: use dependency report and GitNexus impact evidence, or state None
- MQ/DMQ/Kafka dependencies: use dependency report and GitNexus impact evidence, or state None
- Shared DB/schema/config/security dependencies: list shared edit scope or state None
- Required contracts or explicit non-applicability: record before implementation

## Test Impact
{test_impact_block}
- Broadened verification: run impacted upstream/downstream modules from test-impact plan

## Reviewer Focus
- Service-local R2 review: mapped ACs, red test, dependency boundary
- Service-local R3 review: concrete code path, tests, and side effects for mapped ACs
- Known risks: generated starter must be verified against GitNexus evidence and project instructions
"""


def service_design_dispatch_blockers(repo: Path, run_state_path: Path | str | None) -> list[str]:
    return preflight_checks.service_design_dispatch_blockers(repo, run_state_path)


def run(
    repo: Path,
    global_design: Path | None,
    service_design_dir: Path | None = None,
    service_designs: list[Path] | None = None,
    emit_templates: list[str] | None = None,
    run_state: Path | None = None,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    repo = _as_repo(repo)
    templates_written: list[str] = []
    active_service_design_dir = service_design_dir
    for service in emit_templates or []:
        target_dir = _require_repo_path(
            repo,
            active_service_design_dir or Path("docs/agent-runs/service-designs"),
            "service design directory",
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        slug = orchestration_plan.service_slug(str(service))
        target = target_dir / f"{slug}.md"
        if not target.exists():
            global_design_path = _resolve_repo_path(repo, global_design)
            target.write_text(
                service_design_template(str(service), posix(global_design or ""), _optional_text(global_design_path)),
                encoding="utf-8",
            )
        templates_written.append(posix(target.relative_to(repo)))
        active_service_design_dir = target_dir

    result = service_design_gate.validate(repo, global_design, active_service_design_dir, service_designs)
    if templates_written:
        result["templates_written"] = templates_written

    if run_state and result["ready"]:
        dispatch_blockers = service_design_dispatch_blockers(repo, run_state)
        if dispatch_blockers:
            result["ready"] = False
            result.setdefault("blocked_reasons", []).extend(dispatch_blockers)
            result["service_design_dispatch"] = {"ready": False, "blocked_reasons": dispatch_blockers}
            write_status(status_file, result)
            return 2, result
        evidence = active_service_design_dir or (service_designs[0] if service_designs else None)
        transition = state_store.transition_lifecycle(
            repo,
            run_state,
            "PLANNED",
            gate="service_design",
            gate_status="passed",
            evidence=evidence,
        )
        result["run_state_transition"] = transition
        if not transition["ready"]:
            result["ready"] = False
            result["blocked_reasons"].extend("Run state transition: " + reason for reason in transition["blocked_reasons"])

    write_status(status_file, result)
    return (0 if result["ready"] else 2), result


def run_from_args(args) -> tuple[int, dict]:
    return run(
        getattr(args, "repo"),
        global_design=getattr(args, "global_design", None),
        service_design_dir=getattr(args, "service_design_dir", None),
        service_designs=getattr(args, "service_design", None),
        emit_templates=getattr(args, "emit_template", None),
        run_state=getattr(args, "run_state", None),
        status_file=getattr(args, "status_file", None),
    )
