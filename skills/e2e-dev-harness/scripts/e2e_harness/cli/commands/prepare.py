"""Prepare command facade."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path


def _legacy_cli():
    return importlib.import_module("e2e_dev_harness")


def run(
    repo: Path,
    design_doc: Path | None = None,
    paths: list[str] | None = None,
    services: list[str] | None = None,
    agent_mode: str = "strict",
    agent_scope: str = "auto",
    include_agent_content: bool = False,
    max_agent_chars: int = 12000,
    max_discovered_services: int | None = None,
    superpowers_mode: str = "auto",
    memory_mode: str = "auto",
    agent_orchestration_mode: str = "auto",
    service_scope: str = "auto",
    agent_run_dir: str | None = None,
    run_date: str | None = None,
    kg_mode: str = "auto",
    dependency_scan_mode: str = "auto",
    dependency_output_dir: Path | None = None,
    workflow_tier: str = "auto",
    write_dependency_report: bool = True,
    status_file: Path | None = None,
    **extra,
) -> tuple[int, dict]:
    legacy = _legacy_cli()
    args = argparse.Namespace(
        repo=repo,
        design_doc=design_doc,
        path=paths,
        service=services,
        agent_mode=agent_mode,
        agent_scope=agent_scope,
        include_agent_content=include_agent_content,
        max_agent_chars=max_agent_chars,
        max_discovered_services=(
            max_discovered_services
            if max_discovered_services is not None
            else legacy.agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT
        ),
        superpowers_mode=superpowers_mode,
        memory_mode=memory_mode,
        agent_orchestration_mode=agent_orchestration_mode,
        service_scope=service_scope,
        agent_run_dir=agent_run_dir,
        run_date=run_date,
        kg_mode=kg_mode,
        dependency_scan_mode=dependency_scan_mode,
        dependency_output_dir=dependency_output_dir,
        workflow_tier=workflow_tier,
        write_dependency_report=write_dependency_report,
        status_file=status_file,
        **extra,
    )
    return run_from_args(args)


def run_from_args(args) -> tuple[int, dict]:
    legacy = _legacy_cli()
    repo = legacy.as_repo(args.repo)
    effective_agent_scope, effective_service_scope, scope_notes = legacy.align_prepare_scopes(
        args.agent_scope,
        args.service_scope,
    )
    kg_facts = legacy.kg_refresh.detect(repo)
    dependency_scan = legacy.dependency_scan_status(repo, args)
    dependency_report_path = dependency_scan.get("report_paths", {}).get("json")
    agent = (
        {"mode": args.agent_mode, "enabled": False, "blocked": False}
        if args.agent_mode == "off"
        else legacy.agent_instructions.scan(
            repo,
            args.include_agent_content,
            args.max_agent_chars,
            args.path,
            effective_agent_scope,
            args.service,
            args.max_discovered_services,
        )
    )
    if args.agent_mode != "off":
        missing = (
            agent["missing"]["root"]
            or bool(agent["missing"]["services"])
            or bool(agent["missing"].get("requested_services"))
        )
        agent.update({"mode": args.agent_mode, "enabled": True, "blocked": args.agent_mode == "strict" and missing})

    result = {
        "repo": str(repo),
        "scope_alignment": {
            "requested_agent_scope": args.agent_scope,
            "requested_service_scope": args.service_scope,
            "effective_agent_scope": effective_agent_scope,
            "effective_service_scope": effective_service_scope,
            "notes": scope_notes,
        },
        "agent_instructions": agent,
        "superpowers": legacy.superpowers_status(args.superpowers_mode, "all"),
        "memory": legacy.memory_status(repo, args.memory_mode),
        "orchestration": legacy.orchestration_status(
            repo,
            args.agent_orchestration_mode,
            args.design_doc,
            args.agent_run_dir,
            args.run_date,
            effective_service_scope,
            args.service,
            args.path,
            kg_facts,
            Path(dependency_report_path) if dependency_report_path else None,
        ),
        "knowledge_graph": legacy.kg_status(repo, args.kg_mode, kg_facts),
        "cross_service_dependencies": dependency_scan,
        "workflow_tier": legacy.workflow_tier_status(repo, args, kg_facts, dependency_scan),
    }
    blocked = [
        name
        for name in ("agent_instructions", "superpowers", "memory", "orchestration")
        if result[name].get("blocked")
    ]
    result["blocked"] = bool(blocked)
    result["blocked_components"] = blocked
    legacy.write_status(args.status_file, result)
    return (2 if blocked else 0), result
