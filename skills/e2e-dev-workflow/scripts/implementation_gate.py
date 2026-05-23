#!/usr/bin/env python3
"""Hook-like gates before planning or implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import clarification_gate  # noqa: E402
import coverage_gate  # noqa: E402
import memory_capture  # noqa: E402


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def find_kg_status_file(repo: Path, explicit: Path | None) -> Path:
    if explicit:
        return explicit if explicit.is_absolute() else repo / explicit
    candidates = [
        repo / "knowledge-graph" / "knowledge-graph-refresh.json",
        repo / "graphify-out" / "knowledge-graph-refresh.json",
        repo / "graphify-out" / "kg-status.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    agent_run_evidence = repo / "docs" / "agent-runs"
    if agent_run_evidence.exists():
        matches = sorted(
            agent_run_evidence.glob("*/evidence/knowledge-graph-refresh.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if matches:
            return matches[0]
    return candidates[0]


def validate_gate(
    repo: Path,
    design_doc: Path | None,
    kg_status_file: Path | None,
    phase: str,
    red_test_evidence: Path | None,
    coverage_matrix: Path | None = None,
    unit_test_evidence: Path | None = None,
    business_review: Path | None = None,
    memory_updates: Path | None = None,
) -> dict:
    repo = repo.resolve()
    blocked_reasons: list[str] = []
    warnings: list[str] = []

    design_result = None
    if design_doc:
        design_path = design_doc if design_doc.is_absolute() else repo / design_doc
        if not design_path.exists():
            blocked_reasons.append(f"Design document not found: {design_path}")
        else:
            design_result = clarification_gate.validate(design_path)
            if not design_result["ready_for_implementation"]:
                blocked_reasons.append("Clarification gate is not ready.")
    else:
        warnings.append("No design document supplied; clarification readiness was not checked.")
        if phase == "completion":
            blocked_reasons.append("Completion phase requires a design document via --design-doc for acceptance coverage checking.")

    kg_path = find_kg_status_file(repo, kg_status_file)
    kg_status = read_json(kg_path) if kg_path.exists() else None
    if not kg_status:
        blocked_reasons.append(f"Knowledge graph status file not found or unreadable: {kg_path}")
    elif not kg_status.get("selected_tools"):
        warnings.append("Knowledge graph status exists, but no graph tools were selected.")

    red_test_result = None
    if phase == "implementation":
        if not red_test_evidence:
            blocked_reasons.append("Implementation phase requires --red-test-evidence.")
        else:
            evidence_path = red_test_evidence if red_test_evidence.is_absolute() else repo / red_test_evidence
            if not evidence_path.exists() or not evidence_path.read_text(encoding="utf-8", errors="replace").strip():
                blocked_reasons.append(f"Red test evidence is missing or empty: {evidence_path}")
            else:
                red_test_result = str(evidence_path)

    coverage_result = None
    memory_result = None
    if phase == "completion":
        if not red_test_evidence:
            blocked_reasons.append("Completion phase requires --red-test-evidence.")
        else:
            evidence_path = red_test_evidence if red_test_evidence.is_absolute() else repo / red_test_evidence
            if not evidence_path.exists() or not evidence_path.read_text(encoding="utf-8", errors="replace").strip():
                blocked_reasons.append(f"Red test evidence is missing or empty: {evidence_path}")
            else:
                red_test_result = str(evidence_path)
        coverage_result = coverage_gate.validate(repo, coverage_matrix, unit_test_evidence, business_review, design_doc)
        if not coverage_result["ready"]:
            blocked_reasons.extend(coverage_result["blocked_reasons"])
        if memory_updates:
            memory_path = memory_updates if memory_updates.is_absolute() else repo / memory_updates
            memory_result = memory_capture.validate_proposed_updates(memory_path, repo)
            if not memory_result["ready"]:
                blocked_reasons.extend(memory_result["blocked_reasons"])

    return {
        "repo": str(repo),
        "phase": phase,
        "ready": not blocked_reasons,
        "blocked_reasons": blocked_reasons,
        "warnings": warnings,
        "design": design_result,
        "knowledge_graph_status_file": str(kg_path),
        "knowledge_graph_status_loaded": bool(kg_status),
        "red_test_evidence": red_test_result,
        "coverage": coverage_result,
        "memory_updates": memory_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--design-doc", type=Path)
    parser.add_argument("--kg-status-file", type=Path)
    parser.add_argument("--phase", choices=["planning", "implementation", "completion"], default="planning")
    parser.add_argument("--red-test-evidence", type=Path)
    parser.add_argument("--coverage-matrix", type=Path)
    parser.add_argument("--unit-test-evidence", type=Path)
    parser.add_argument("--business-review", type=Path)
    parser.add_argument("--memory-updates", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate_gate(
        args.repo,
        args.design_doc,
        args.kg_status_file,
        args.phase,
        args.red_test_evidence,
        args.coverage_matrix,
        args.unit_test_evidence,
        args.business_review,
        args.memory_updates,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Implementation gate: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
