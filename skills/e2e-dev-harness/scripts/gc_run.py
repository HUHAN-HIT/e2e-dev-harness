#!/usr/bin/env python3
"""Artifact lifecycle retention policy for harness run directories."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from common import posix, read_json_object


ACTIVE_LIFECYCLES = {
    "CREATED",
    "CLARIFIED",
    "SERVICE_DESIGN_REQUIRED",
    "PLANNED",
    "RED_READY",
    "WAITING_DISPATCH",
    "IMPLEMENTED",
    "REVIEWED",
    "REWORK_REQUIRED",
}
TERMINAL_LIFECYCLES = {"VERIFIED", "ARCHIVED"}


def _resolve_inside_repo(repo: Path, value: Path) -> Path:
    repo_root = repo.resolve()
    resolved = (value if value.is_absolute() else repo_root / value).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as error:
        raise ValueError(f"GC path resolves outside repository: {value}") from error
    return resolved


def _run_mtime(run_dir: Path) -> float:
    latest = run_dir.stat().st_mtime
    for path in run_dir.rglob("*"):
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return latest


def _lifecycle(run_dir: Path) -> str:
    state = read_json_object(run_dir / "run-state.json")
    return str(state.get("lifecycle", "")).strip().upper()


def _is_pinned(run_dir: Path) -> bool:
    return (run_dir / ".gc-pin").exists() or (run_dir / "gc-pin.json").exists()


def discover_runs(agent_runs_dir: Path) -> list[dict]:
    if not agent_runs_dir.exists():
        return []
    runs: list[dict] = []
    for run_dir in sorted(path for path in agent_runs_dir.iterdir() if path.is_dir()):
        modified_at = _run_mtime(run_dir)
        runs.append(
            {
                "run_id": run_dir.name,
                "path": run_dir,
                "lifecycle": _lifecycle(run_dir),
                "modified_at_epoch": modified_at,
                "age_days": max(0, int((time.time() - modified_at) // 86_400)),
                "pinned": _is_pinned(run_dir),
            }
        )
    return runs


def classify_runs(runs: list[dict], keep_latest: int, max_age_days: int) -> list[dict]:
    latest_pool = [
        item
        for item in runs
        if str(item.get("lifecycle", "")) in TERMINAL_LIFECYCLES and not item.get("pinned")
    ]
    latest = {
        item["run_id"]
        for item in sorted(latest_pool, key=lambda run: run["modified_at_epoch"], reverse=True)[: max(0, keep_latest)]
    }
    classified: list[dict] = []
    for item in runs:
        result = dict(item)
        lifecycle = str(result.get("lifecycle", ""))
        if result["run_id"] in latest:
            decision = "keep_latest"
        elif result.get("pinned"):
            decision = "pinned"
        elif lifecycle in ACTIVE_LIFECYCLES or lifecycle not in TERMINAL_LIFECYCLES:
            decision = "active_lifecycle"
        elif int(result.get("age_days", 0)) < max_age_days:
            decision = "within_retention_window"
        else:
            decision = "would_delete"
        result["decision"] = decision
        classified.append(result)
    return classified


def run(
    repo: Path,
    agent_runs: Path = Path("docs/agent-runs"),
    keep_latest: int = 5,
    max_age_days: int = 30,
    keep_results_latest: int = 20,
    execute: bool = False,
) -> dict:
    if keep_latest < 0:
        raise ValueError("keep-latest must be non-negative.")
    if max_age_days < 0:
        raise ValueError("max-age-days must be non-negative.")
    if keep_results_latest < 0:
        raise ValueError("keep-results-latest must be non-negative.")
    repo = repo.resolve()
    agent_runs_dir = _resolve_inside_repo(repo, agent_runs)
    classified = classify_runs(discover_runs(agent_runs_dir), keep_latest, max_age_days)
    deleted: list[str] = []
    for item in classified:
        if item.get("decision") != "would_delete" or not execute:
            continue
        target = Path(item["path"]).resolve()
        target.relative_to(repo)
        shutil.rmtree(target)
        item["decision"] = "deleted"
        deleted.append(posix(target.relative_to(repo)))
    result_prune = prune_coordinator_results(repo, classified, keep_results_latest, execute)
    result_candidates = result_prune["candidates"]
    result_deletes = result_prune["deleted"]
    serializable = []
    for item in classified:
        copy = dict(item)
        copy["path"] = posix(Path(copy["path"]).relative_to(repo))
        serializable.append(copy)
    candidates = [item for item in serializable if item["decision"] in {"would_delete", "deleted"}]
    return {
        "schema": "e2e-dev-harness.gc-run.v1",
        "ready": True,
        "workflow_stage": "GC",
        "dry_run": not execute,
        "repo": str(repo),
        "agent_runs_dir": posix(agent_runs_dir.relative_to(repo)),
        "keep_latest": keep_latest,
        "max_age_days": max_age_days,
        "keep_results_latest": keep_results_latest,
        "run_count": len(serializable),
        "delete_candidate_count": len(candidates),
        "deleted_count": len(deleted),
        "deleted": deleted,
        "result_delete_candidate_count": len(result_candidates),
        "would_delete_results": [] if execute else result_candidates,
        "deleted_result_count": len(result_deletes),
        "deleted_results": result_deletes,
        "runs": serializable,
    }


def prune_coordinator_results(repo: Path, runs: list[dict], keep_latest: int, execute: bool) -> dict:
    candidates: list[str] = []
    deleted: list[str] = []
    for item in runs:
        if item.get("decision") == "deleted":
            continue
        results_dir = Path(item["path"]) / "coordinator-results"
        if not results_dir.exists():
            continue
        result_files = sorted(
            [path for path in results_dir.glob("*.json") if path.is_file()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in result_files[max(0, keep_latest):]:
            resolved = path.resolve()
            resolved.relative_to(repo)
            display_path = posix(resolved.relative_to(repo))
            candidates.append(display_path)
            if execute:
                resolved.unlink()
                deleted.append(display_path)
    return {"candidates": candidates, "deleted": deleted}
