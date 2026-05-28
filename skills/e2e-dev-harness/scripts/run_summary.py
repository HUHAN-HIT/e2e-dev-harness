#!/usr/bin/env python3
"""Create a compact summary for an e2e-dev-harness run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def resolve(repo: Path, value: str | None) -> Path | None:
    if not value:
        return None
    repo_root = repo.resolve()
    path = Path(value)
    resolved = (path if path.is_absolute() else repo_root / path).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        return None
    return resolved


def status_counts(artifacts: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in artifacts:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def required_missing(repo: Path, artifacts: list[dict]) -> list[str]:
    missing: list[str] = []
    for item in artifacts:
        if not item.get("required_by_completion"):
            continue
        item_path = str(item.get("path") or "")
        if item.get("kind") == "pattern":
            if item_path:
                missing.append(item_path)
            continue
        resolved = resolve(repo, item_path)
        if item_path and resolved and not resolved.exists():
            missing.append(item_path)
    return missing


def review_artifacts(artifacts: list[dict]) -> dict[str, str]:
    required = {
        "R1": "design_review",
        "R2": "test_review",
        "R3": "implementation_review",
    }
    found: dict[str, str] = {}
    for label, artifact_type in required.items():
        status = "missing"
        for item in artifacts:
            if item.get("type") == artifact_type:
                status = str(item.get("status") or "planned")
                break
        found[label] = status
    return found


def artifact_path(artifacts: list[dict], artifact_type: str) -> str:
    for item in artifacts:
        if item.get("type") == artifact_type and item.get("path"):
            return str(item["path"])
    return ""


def next_actions(summary: dict) -> list[str]:
    actions: list[str] = []
    if summary["required_missing_count"]:
        actions.append("Create or refresh missing completion artifacts.")
    if summary["blocked_count"]:
        actions.append("Resolve harness verification blockers.")
    if any(status != "present" for status in summary["semantic_reviews"].values()):
        actions.append("Run independent R1/R2/R3 semantic reviews.")
    if summary.get("strict_guard") != "present" and summary.get("strict_completion"):
        actions.append("Run strict workflow guard and save its status artifact.")
    if not actions and summary.get("ready") is True:
        actions.append("Run is ready for archival or downstream reporting.")
    return actions


def build_summary(repo: Path, state_path: Path, verify_result: dict | None = None) -> dict:
    repo = repo.resolve()
    resolved_state = state_path if state_path.is_absolute() else repo / state_path
    state_data = load_json(resolved_state)
    registry_path = resolve(repo, state_data.get("artifact_registry"))
    registry_data = load_json(registry_path)
    artifacts = [item for item in registry_data.get("artifacts", []) if isinstance(item, dict)]
    trace_path = resolve(repo, artifact_path(artifacts, "execution_trace")) or (resolved_state.parent / "execution-trace.json")
    trace_data = load_json(trace_path)
    verify = verify_result or {}
    blocked = verify.get("blocked_reasons", []) if isinstance(verify.get("blocked_reasons", []), list) else []
    warnings = verify.get("warnings", []) if isinstance(verify.get("warnings", []), list) else []
    workflow = verify.get("workflow") if isinstance(verify.get("workflow"), dict) else {}
    strict_completion = bool(workflow.get("strict") and workflow.get("phase") == "completion")
    if strict_completion and not isinstance(verify.get("workflow_guard"), dict):
        blocked = list(blocked) + ["Strict Guard phase is missing; run e2e_dev_harness.py guard or verify --strict-workflow and save the result."]
    missing = required_missing(repo, artifacts)
    summary = {
        "schema": "e2e-dev-harness.run-summary.v1",
        "repo": str(repo),
        "run_id": state_data.get("run_id") or registry_data.get("run_id") or "",
        "lifecycle": state_data.get("lifecycle") or "",
        "selected_mode": state_data.get("selected_mode") or registry_data.get("selected_mode") or "",
        "services": state_data.get("services") or registry_data.get("services") or [],
        "ready": verify.get("ready"),
        "blocked_count": len(blocked),
        "warning_count": len(warnings),
        "artifact_count": len(artifacts),
        "artifact_status_counts": status_counts(artifacts),
        "required_missing_count": len(missing),
        "required_missing": missing,
        "semantic_reviews": review_artifacts(artifacts),
        "strict_completion": strict_completion,
        "strict_guard": "present" if isinstance(verify.get("workflow_guard"), dict) else "missing",
        "blocked_reasons": blocked,
        "warnings": warnings,
        "run_state": str(resolved_state),
        "artifact_registry": str(registry_path) if registry_path else "",
        "execution_trace": trace_data.get("summary", {}) if isinstance(trace_data.get("summary"), dict) else {},
    }
    summary["next_actions"] = next_actions(summary)
    return summary


def markdown(summary: dict) -> str:
    ready = summary.get("ready")
    status = "UNKNOWN" if ready is None else ("READY" if ready else "BLOCKED")
    services = ", ".join(summary.get("services") or []) or "none"
    lines = [
        f"# Run Summary: {summary.get('run_id') or 'unknown'}",
        "",
        f"- Status: {status}",
        f"- Lifecycle: {summary.get('lifecycle') or 'unknown'}",
        f"- Mode: {summary.get('selected_mode') or 'unknown'}",
        f"- Services: {services}",
        f"- Artifacts: {summary.get('artifact_count', 0)}",
        f"- Required missing: {summary.get('required_missing_count', 0)}",
        f"- Blockers: {summary.get('blocked_count', 0)}",
        f"- Warnings: {summary.get('warning_count', 0)}",
        f"- Trace elapsed ms: {summary.get('execution_trace', {}).get('elapsed_ms_total', 0)}",
        "",
        "## Semantic Reviews",
    ]
    for label, review_status in summary.get("semantic_reviews", {}).items():
        lines.append(f"- {label}: {review_status}")
    if summary.get("strict_completion"):
        lines.extend(["", "## Strict Guard"])
        lines.append(f"- Status: {summary.get('strict_guard')}")
    lines.extend(["", "## Next Actions"])
    for action in summary.get("next_actions", []):
        lines.append(f"- {action}")
    if summary.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons"])
        for reason in summary["blocked_reasons"]:
            lines.append(f"- {reason}")
    return "\n".join(lines) + "\n"


def write_outputs(summary: dict, json_path: Path | None = None, markdown_path: Path | None = None) -> None:
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown(summary), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--verify-result", type=Path)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    out_json = args.out_json if not args.out_json or args.out_json.is_absolute() else repo / args.out_json
    out_md = args.out_md if not args.out_md or args.out_md.is_absolute() else repo / args.out_md
    verify_result_path = (
        args.verify_result
        if not args.verify_result or args.verify_result.is_absolute()
        else repo / args.verify_result
    )
    summary = build_summary(repo, args.state, load_json(verify_result_path))
    write_outputs(summary, out_json, out_md)
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(markdown(summary), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
