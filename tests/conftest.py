"""Shared test fixtures for e2e-dev-harness self-tests."""

from __future__ import annotations

import json
import hashlib
import re
import shutil
import textwrap
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def tmp_path(request) -> Path:
    """Use a repo-independent Windows temp root; some desktops deny pytest's default temp root."""
    base = ROOT / ".test-tmp"
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.nodeid)[-120:]
    path = base / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def write_command_evidence(
    path: Path, command: str = "mvn test", exit_code: int = 0
) -> None:
    path.write_text(
        json.dumps(
            {
                "command": command,
                "exit_code": exit_code,
                "stdout_tail": (
                    "BUILD SUCCESS"
                    if exit_code == 0
                    else "BUILD FAILURE expected failing test"
                ),
                "stderr_tail": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def verified_workflow_result() -> dict:
    return {
        "workflow": {
            "strict": True,
            "phase": "completion",
            "run_gate": True,
            "skip_maven": False,
            "skip_spring_static_check": False,
            "dependency_scan_mode": "auto",
            "write_dependency_report": True,
            "require_semantic_reviews": True,
            "require_requirements_archive": True,
            "harness": True,
            "state": "docs/agent-runs/run/run-state.json",
        },
        "prepare": {
            "blocked": False,
            "agent_instructions": {"blocked": False},
            "superpowers": {"blocked": False, "enabled": True},
            "memory": {"blocked": False},
            "orchestration": {"blocked": False},
            "knowledge_graph": {"selected_tools": ["gitnexus"]},
            "cross_service_dependencies": {
                "enabled": True,
                "mode": "auto",
                "ready": True,
                "report_paths": {"json": "knowledge-graph/cross-service-dependencies.json"},
                "unresolved_questions": [],
            },
        },
        "clarification": {"ready_for_implementation": True},
        "implementation_gate": {
            "phase": "completion",
            "ready": True,
            "blocked_reasons": [],
            "red_test_evidence": "docs/agent-runs/run/evidence/red-test.txt",
            "tdd": {
                "ready": True,
                "red_evidence": "docs/agent-runs/run/evidence/red-test.txt",
                "green_commands": [{"command": "mvn test", "exit_code": 0}],
            },
            "semantic_reviews": {
                "ready": True,
                "covered_phases": ["design", "test", "implementation"],
                "items": [
                    {
                        "phase": "design",
                        "developer_agent": "developer-agent",
                        "reviewer_agent": "design-reviewer",
                        "independence": "independent-agent",
                    },
                    {
                        "phase": "test",
                        "developer_agent": "developer-agent",
                        "reviewer_agent": "test-reviewer",
                        "independence": "independent-agent",
                    },
                    {
                        "phase": "implementation",
                        "developer_agent": "developer-agent",
                        "reviewer_agent": "implementation-reviewer",
                        "independence": "independent-agent",
                    },
                ],
            },
            "requirements_archive": {
                "ready": True,
                "blocked_reasons": [],
                "path": "docs/agent-runs/run/requirements-archive.md",
            },
        },
        "maven": {"skipped": False, "exit_code": 0, "command": "mvn test"},
    }


REVIEW_CHECKLIST = {
    "design": ["ac-completeness", "dependency-impact", "security-sensitive-paths"],
    "test": ["happy-and-failure-paths", "contract-coverage", "security-negative-paths"],
    "implementation": [
        "ac-code-path-trace",
        "implementation-completeness",
        "security-negative-paths",
        "project-pattern-consistency",
    ],
}


def write_service_review(
    repo: Path,
    service: str,
    phase: str,
    developer_agent: str = "developer-agent-1",
) -> Path:
    review_name = {
        "test": "R2-test-review.md",
        "implementation": "R3-implementation-review.md",
    }[phase]
    request_name = {
        "test": "R2-test-review-request.md",
        "implementation": "R3-implementation-review-request.md",
    }[phase]
    reviewer_agent = f"reviewer-agent-{service}-{phase}"
    reviewer_session = f"review-session-{service}-{phase}"
    service_base = repo / "docs" / "agent-runs" / "run" / "service-plans" / service
    request = service_base / "review-requests" / request_name
    review = service_base / "reviews" / review_name
    invocation = service_base / "review-invocations" / f"{phase}-reviewer-invocation.json"
    request.parent.mkdir(parents=True, exist_ok=True)
    review.parent.mkdir(parents=True, exist_ok=True)
    invocation.parent.mkdir(parents=True, exist_ok=True)
    request_rel = str(request.relative_to(repo)).replace("\\", "/")
    review_rel = str(review.relative_to(repo)).replace("\\", "/")
    invocation_rel = str(invocation.relative_to(repo)).replace("\\", "/")
    request.write_text(
        textwrap.dedent(
            f"""
            # {service} {phase.title()} Review Request

            - Phase: {phase}
            - Reviewer Role: independent semantic reviewer
            - Context Package: request-scoped; no inherited developer chat context
            - Allowed Inputs: design, tests, implementation refs, dependency report, service plan
            - Forbidden: inherited developer chat context; production-code edits; self-review
            - Output: {review_rel}
            - Developer Agent: {developer_agent}
            - Reviewer Agent: {reviewer_agent}
            - Reviewer Invocation: {invocation_rel}
            """
        ).strip(),
        encoding="utf-8",
    )
    request_hash = hashlib.sha256(request.read_bytes()).hexdigest()
    checklist = "\n".join(f"- [x] {item}: checked." for item in REVIEW_CHECKLIST.get(phase, []))
    review.write_text(
        textwrap.dedent(
            f"""
            # {service} {phase.title()} Review

            - Phase: {phase}
            - Reviewer: semantic-reviewer
            - Review Request: {request_rel}
            - Developer Agent: {developer_agent}
            - Reviewer Agent: {reviewer_agent}
            - Reviewer Session: {reviewer_session}
            - Reviewer Invocation: {invocation_rel}
            - Request Hash: {request_hash}
            - Independence: independent-agent
            - Context Boundary: request-scoped; no inherited developer chat context
            - No Code Changes: confirmed
            - Scope: {service}
            - Inputs Reviewed: design doc; tests; implementation files; service plan
            - Findings: None
            - Required Rework: None
            - Status: approved

            ## Required Review Checklist

            {checklist}

            ## Code Path Trace

            - AC-1: Controller -> Service -> Repository/Client/Sender -> response.
            """
        ).strip(),
        encoding="utf-8",
    )
    invocation.write_text(
        json.dumps(
            {
                "runtime": "claude-code",
                "invocation_type": "subagent",
                "developer_agent": developer_agent,
                "developer_session": f"developer-session-{service}",
                "reviewer_agent": reviewer_agent,
                "reviewer_session": reviewer_session,
                "context_pack": request_rel,
                "review_request": request_rel,
                "output": review_rel,
                "fork_context": False,
                "context_policy": "request-scoped; no-inherited-developer-chat-context",
                "status": "completed",
            }
        ),
        encoding="utf-8",
    )
    return review
