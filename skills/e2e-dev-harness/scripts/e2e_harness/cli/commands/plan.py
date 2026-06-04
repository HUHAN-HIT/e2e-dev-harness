"""Plan command facade."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import artifact_registry
import run_state


def _legacy_cli():
    return importlib.import_module("e2e_dev_harness")


def run(
    repo: Path,
    mode: str,
    design_doc: Path | None = None,
    agent_run_dir: str | None = None,
    run_date: str | None = None,
    service_scope: str = "auto",
    services_requested: list[str] | None = None,
    paths_requested: list[str] | None = None,
    dependency_report: Path | None = None,
    create_archive: bool = False,
    write_exec_plan: Path | bool | None = None,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    legacy = _legacy_cli()
    repo = legacy.as_repo(repo)
    kg_facts = legacy.kg_refresh.detect(repo)
    result = legacy.orchestration_status(
        repo,
        mode,
        design_doc,
        agent_run_dir,
        run_date,
        service_scope,
        services_requested,
        paths_requested,
        kg_facts,
        dependency_report,
    )
    if (create_archive or write_exec_plan) and not result.get("handoff_artifacts"):
        result["blocked"] = True
        result["blocked_reasons"] = [
            "Discovery scope does not create ExecPlan or agent-run archives; rerun with --service-scope affected plus --service or --path."
        ]
        legacy.write_status(status_file, result)
        return 2, result
    if create_archive or write_exec_plan:
        run_dir = legacy.require_repo_path(repo, Path(result["agent_run_dir"]), "agent run directory")
        (run_dir / "handoffs").mkdir(parents=True, exist_ok=True)
        (run_dir / "evidence").mkdir(parents=True, exist_ok=True)
        (run_dir / "confirmations").mkdir(parents=True, exist_ok=True)
        legacy.require_repo_path(repo, Path(result["handoff_artifacts"]["review_requests_dir"]), "review requests directory").mkdir(parents=True, exist_ok=True)
        legacy.require_repo_path(repo, Path(result["handoff_artifacts"]["reviews_dir"]), "reviews directory").mkdir(parents=True, exist_ok=True)
        legacy.require_repo_path(repo, Path(result["handoff_artifacts"]["rework_dir"]), "rework directory").mkdir(parents=True, exist_ok=True)
        legacy.require_repo_path(repo, Path(result["handoff_artifacts"]["contracts_dir"]), "contracts directory").mkdir(parents=True, exist_ok=True)
        legacy.require_repo_path(repo, Path(result["handoff_artifacts"]["service_designs_dir"]), "service designs directory").mkdir(parents=True, exist_ok=True)
        if design_doc:
            result["handoff_artifacts"]["design_doc"] = str(design_doc).replace("\\", "/")
        result["handoff_files_created"] = legacy.create_handoff_files(
            repo,
            result["handoff_artifacts"],
            result.get("agent_schedule"),
        )
        proposed = legacy.require_repo_path(
            repo,
            Path(result["handoff_artifacts"]["proposed_memory_updates"]),
            "proposed memory updates",
        )
        if not proposed.exists():
            proposed.write_text("# Proposed Memory Updates\n\n", encoding="utf-8")
        schedule_path = legacy.require_repo_path(
            repo,
            Path(result["handoff_artifacts"]["agent_schedule"]),
            "agent schedule",
        )
        schedule_path.write_text(json.dumps(result["agent_schedule"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result["agent_schedule_written"] = str(schedule_path)
        kg_artifact = legacy.write_kg_status_artifact(
            repo,
            Path(result["handoff_artifacts"]["knowledge_graph_status"]),
            "auto",
            kg_facts,
        )
        result["knowledge_graph_status_written"] = kg_artifact["path"]
        result["knowledge_graph"] = kg_artifact["status"]
        result["agent_run_archive_created"] = str(run_dir)
    if write_exec_plan or create_archive:
        target = legacy.require_repo_path(
            repo,
            write_exec_plan if isinstance(write_exec_plan, Path) else Path(result["handoff_artifacts"]["exec_plan"]),
            "exec plan",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(legacy.exec_plan_text(repo, design_doc, result), encoding="utf-8")
        result["exec_plan_written"] = str(target)
    if create_archive:
        registry_artifacts = dict(result["handoff_artifacts"])
        registry = artifact_registry.build_registry(
            repo,
            result["agent_run_dir"],
            registry_artifacts,
            result.get("selected_mode", ""),
            result.get("selected_services", []),
        )
        registry_path = legacy.require_repo_path(
            repo,
            Path(result["handoff_artifacts"]["artifact_registry"]),
            "artifact registry",
        )
        artifact_registry.write_registry(repo, registry_path, registry)
        lifecycle = (
            "SERVICE_DESIGN_REQUIRED"
            if result.get("selected_mode") == "multi" and len(result.get("selected_services", [])) > 1
            else "PLANNED"
        )
        state = run_state.build_state(
            result["agent_run_dir"],
            result.get("selected_mode", ""),
            result.get("slice_services", result.get("selected_services", [])),
            result["handoff_artifacts"]["artifact_registry"],
            lifecycle=lifecycle,
            shared_edit_scopes=result.get("shared_edit_scopes", []),
            shared_edit_scope_owners=result.get("shared_edit_scope_owners", {}),
        )
        state_path = legacy.require_repo_path(repo, Path(result["handoff_artifacts"]["run_state"]), "run state")
        run_state.write_state(repo, state_path, state)
        result["artifact_registry_written"] = str(registry_path)
        result["run_state_written"] = str(state_path)
        result["run_state_lifecycle"] = lifecycle
    legacy.write_status(status_file, result)
    return 0, result


def run_from_args(args) -> tuple[int, dict]:
    return run(
        getattr(args, "repo"),
        mode=getattr(args, "mode"),
        design_doc=getattr(args, "design_doc", None),
        agent_run_dir=getattr(args, "agent_run_dir", None),
        run_date=getattr(args, "run_date", None),
        service_scope=getattr(args, "service_scope", "auto"),
        services_requested=getattr(args, "service", None),
        paths_requested=getattr(args, "path", None),
        dependency_report=getattr(args, "dependency_report", None),
        create_archive=getattr(args, "create_archive", False),
        write_exec_plan=getattr(args, "write_exec_plan", None),
        status_file=getattr(args, "status_file", None),
    )
