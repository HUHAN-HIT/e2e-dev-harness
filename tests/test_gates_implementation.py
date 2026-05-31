"""Implementation gate: the largest gate with design, code, and evidence checks."""
from __future__ import annotations

import sys
import hashlib
import json
import tempfile
import textwrap
import unittest

from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import implementation_gate  # noqa: E402
import kg_refresh  # noqa: E402
import service_design_gate  # noqa: E402
import context_pack  # noqa: E402
import harness_verify  # noqa: E402
import artifact_registry  # noqa: E402
import run_state  # noqa: E402
from conftest import write_command_evidence, REVIEW_CHECKLIST, write_service_review  # noqa: E402
import e2e_dev_harness  # noqa: E402
import test_impact_plan  # noqa: E402


class ImplementationGateTests(unittest.TestCase):
    REVIEW_CHECKLIST = REVIEW_CHECKLIST

    def default_review_checklist(self, phase: str) -> str:
        return "\n".join(f"- [x] {item}: checked." for item in self.REVIEW_CHECKLIST.get(phase, []))

    def write_semantic_reviews(self, repo: Path, phases: tuple[str, ...] = ("design", "test", "implementation")) -> Path:
        review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
        request_dir = repo / "docs" / "agent-runs" / "run" / "review-requests"
        invocation_dir = repo / "docs" / "agent-runs" / "run" / "review-invocations"
        review_dir.mkdir(parents=True, exist_ok=True)
        request_dir.mkdir(parents=True, exist_ok=True)
        invocation_dir.mkdir(parents=True, exist_ok=True)
        for phase, review_name, request_name in (
            ("design", "R1-design-review.md", "R1-design-review-request.md"),
            ("test", "R2-test-review.md", "R2-test-review-request.md"),
            ("implementation", "R3-implementation-review.md", "R3-implementation-review-request.md"),
        ):
            if phase not in phases:
                continue
            request_path = request_dir / request_name
            invocation_path = invocation_dir / f"{phase}-reviewer-invocation.json"
            request_path.write_text(
                textwrap.dedent(
                    f"""
                    # {phase.title()} Review Request

                    - Phase: {phase}
                    - Reviewer Role: independent semantic reviewer
                    - Context Package: request-scoped; no inherited developer chat context
                    - Allowed Inputs: design, tests, implementation refs, dependency report
                    - Forbidden: inherited developer chat context; production-code edits; self-review
                    - Output: docs/agent-runs/run/reviews/{review_name}
                    - Developer Agent: developer-agent-1
                    - Reviewer Agent: reviewer-agent-{phase}
                    - Reviewer Invocation: docs/agent-runs/run/review-invocations/{phase}-reviewer-invocation.json
                    """
                ).strip(),
                encoding="utf-8",
            )
            invocation_path.write_text(
                json.dumps(
                    {
                        "runtime": "claude-code",
                        "invocation_type": "subagent",
                        "developer_agent": "developer-agent-1",
                        "developer_session": "developer-session-1",
                        "reviewer_agent": f"reviewer-agent-{phase}",
                        "reviewer_session": f"reviewer-session-{phase}",
                        "context_pack": f"docs/agent-runs/run/review-requests/{request_name}",
                        "review_request": f"docs/agent-runs/run/review-requests/{request_name}",
                        "output": f"docs/agent-runs/run/reviews/{review_name}",
                        "fork_context": False,
                        "context_policy": "request-scoped; no-inherited-developer-chat-context",
                        "status": "completed",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            request_hash = hashlib.sha256(request_path.read_bytes()).hexdigest()
            checklist = self.default_review_checklist(phase)
            code_path_trace = ""
            if phase == "implementation":
                code_path_trace = textwrap.dedent(
                    """

                    ## Code Path Trace

                    - AC-1: Controller -> ApplicationService -> Repository/Client/Sender -> response or event.
                    - AC-2: Controller -> ApplicationService -> Validator/Repository -> error or state update.
                    - AC-3: Controller -> ApplicationService -> Repository/Client/Sender -> verified behavior.
                    - AC-4: Controller -> ApplicationService -> Repository/Client/Sender -> verified behavior.
                    - AC-5: Controller -> ApplicationService -> Repository/Client/Sender -> verified behavior.
                    """
                )
            (review_dir / review_name).write_text(
                textwrap.dedent(
                    f"""
                    # {phase.title()} Review

                    - Phase: {phase}
                    - Reviewer: semantic-reviewer
                    - Review Request: docs/agent-runs/run/review-requests/{request_name}
                    - Developer Agent: developer-agent-1
                    - Reviewer Agent: reviewer-agent-{phase}
                    - Reviewer Session: reviewer-session-{phase}
                    - Reviewer Invocation: docs/agent-runs/run/review-invocations/{phase}-reviewer-invocation.json
                    - Request Hash: {request_hash}
                    - Independence: independent-agent
                    - Context Boundary: request-scoped; no inherited developer chat context
                    - No Code Changes: confirmed
                    - Scope: all-services
                    - Inputs Reviewed: requirements; use cases; tests; implementation refs
                    - Findings: None
                    - Required Rework: None
                    - Status: approved

                    ## Required Review Checklist

                    {checklist}
                    {code_path_trace}
                    """
                ).strip(),
                encoding="utf-8",
            )
        return review_dir

    def test_planning_gate_requires_knowledge_graph_status(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - sample-service

            ## Use Cases
            - Create quote.

            ## Acceptance Criteria
            - Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")

            result = implementation_gate.validate_gate(repo, design, None, "planning", None)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Knowledge graph status" in reason for reason in result["blocked_reasons"]))

    def test_kg_refresh_detects_existing_gitnexus_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            meta = repo / ".gitnexus" / "meta.json"
            meta.parent.mkdir(parents=True)
            meta.write_text(
                json.dumps(
                    {
                        "repoPath": str(repo),
                        "indexedAt": "2026-05-31T00:00:00Z",
                        "stats": {"nodes": 12, "edges": 34, "processes": 5},
                        "capabilities": {"graph": {"status": "available"}},
                    }
                ),
                encoding="utf-8",
            )

            result = kg_refresh.detect(repo)

        self.assertTrue(result["gitnexus_index"]["exists"])
        self.assertTrue(result["gitnexus_index"]["repo_path_matches"])
        self.assertEqual(12, result["gitnexus_index"]["nodes"])
        self.assertEqual("available", result["gitnexus_index"]["graph_status"])

    def test_gate_blocks_stale_skipped_kg_status_when_gitnexus_index_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            meta = repo / ".gitnexus" / "meta.json"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            meta.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            meta.write_text(
                json.dumps(
                    {
                        "repoPath": str(repo),
                        "stats": {"nodes": 12, "edges": 34, "processes": 5},
                        "capabilities": {"graph": {"status": "available"}},
                    }
                ),
                encoding="utf-8",
            )
            kg.write_text(
                json.dumps({"status": "skipped", "reason": "no knowledge graph configured"}),
                encoding="utf-8",
            )

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(repo=repo, phase="planning", kg_status_file=kg)
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("status is skipped" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any(".gitnexus/meta.json exists" in reason for reason in result["blocked_reasons"]))

    def test_gate_prefers_current_run_kg_status_over_stale_root_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            root_kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            run_kg = repo / "docs" / "agent-runs" / "run" / "evidence" / "knowledge-graph-refresh.json"
            root_kg.parent.mkdir(parents=True)
            run_kg.parent.mkdir(parents=True)
            root_kg.write_text(
                json.dumps({"status": "skipped", "reason": "no knowledge graph configured"}),
                encoding="utf-8",
            )
            run_kg.write_text(json.dumps({"selected_tools": ["gitnexus"]}), encoding="utf-8")
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("docs/agent-runs/run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(
                    repo=repo,
                    phase="planning",
                    run_state=Path("docs/agent-runs/run/run-state.json"),
                    require_semantic_reviews=False,
                )
            )

        self.assertEqual(str(run_kg), result["knowledge_graph_status_file"])
        self.assertFalse(any("status is skipped" in reason for reason in result["blocked_reasons"]))

    def test_implementation_gate_requires_run_state_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(repo=repo, phase="implementation")
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("--run-state" in reason for reason in result["blocked_reasons"]))

    def test_critical_implementation_gate_requires_dependency_report_before_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "payment-risk.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Payment Risk

                    ## Goal
                    Add payment risk control.

                    ## Scope
                    - services/payment-service

                    ## Use Cases
                    - Block risky payment.

                    ## Acceptance Criteria
                    - AC-1 Risky payment is rejected.

                    ## Test Design
                    - Red test first.

                    ## Open Questions
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            kg.parent.mkdir(parents=True)
            kg.write_text(json.dumps({"selected_tools": ["scanner"]}), encoding="utf-8")
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single-review", ["services/payment-service"], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(
                    repo=repo,
                    phase="implementation",
                    design_doc=Path("docs/design/payment-risk.md"),
                    run_state=Path("docs/agent-runs/run/run-state.json"),
                )
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("dependency discovery evidence" in reason for reason in result["blocked_reasons"]))

    def test_implementation_gate_allows_explicit_no_harness_state_only_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            approval = repo / "approval.md"
            approval.write_text("Approval: user-approved\n", encoding="utf-8")

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(
                    repo=repo,
                    phase="implementation",
                    no_harness_state=True,
                    harness_state_approval=approval,
                )
            )

        self.assertFalse(result["ready"])
        self.assertFalse(any("--run-state" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("bypassed" in warning for warning in result["warnings"]))

    def test_implementation_gate_auto_tdd_becomes_strict_for_messaging_design(self) -> None:
        markdown = textwrap.dedent(
            """
            # Refund Notification

            ## Goal
            - Publish refund MQ notification.

            ## Scope
            - services/refund-service

            ## Use Cases
            - Refund succeeds and emits a topic payload.

            ## Acceptance Criteria
            - AC-1 DMQ topic refund.completed is sent with payload fields.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None

            ## Impact Summary
            | interface | affected consumer | evidence | AC | test obligation | risk |
            | --- | --- | --- | --- | --- | --- |
            | refund.completed topic | downstream consumers | Raw Evidence: docs/agent-runs/run/evidence/impact.json | AC-1 | producer test | high |
            - Source: GitNexus impact + dependency scanner

            ## Change Logic
            - Current behavior: refund completes without message.
            - Target behavior: refund emits DMQ event.
            - Runtime path: RefundService -> RefundMessageSender -> topic.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "refund.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            red.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")

            result = implementation_gate.validate_gate(repo, design, kg, "implementation", red)

        self.assertFalse(result["ready"])
        self.assertEqual("critical", result["workflow_tier"]["tier"])
        self.assertEqual("strict", result["tdd"]["effective_mode"])
        self.assertTrue(
            any("strict evidence must be JSON" in reason for reason in result["blocked_reasons"]),
            result["blocked_reasons"],
        )

    def test_gate_request_dataclass_matches_legacy_validate_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            request = implementation_gate.GateRequest(repo=repo, phase="planning")

            result = implementation_gate.validate_gate_request(request)
            legacy = implementation_gate.validate_gate(repo, None, None, "planning", None)

        self.assertEqual(legacy["ready"], result["ready"])
        self.assertEqual(legacy["blocked_reasons"], result["blocked_reasons"])
        self.assertEqual(legacy["phase"], result["phase"])

    def test_implementation_gate_passes_review_profile_to_reviewer_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            kg.parent.mkdir(parents=True)
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            profile = repo / "review-profiles" / "strict.json"
            profile.parent.mkdir(parents=True)
            profile.write_text('{"required_checklist":{"design":["ac-completeness"]}}\n', encoding="utf-8")
            reviewer_result = {
                "ready": True,
                "blocked_reasons": [],
                "warnings": [],
                "covered_phases": ["design"],
                "items": [],
            }
            with patch.object(implementation_gate.reviewer_gate, "validate", return_value=reviewer_result) as validate:
                result = implementation_gate.validate_gate(
                    repo,
                    None,
                    kg,
                    "planning",
                    None,
                    review_profile=profile,
                )

        self.assertTrue(result["ready"])
        self.assertEqual(profile, validate.call_args.args[4])

    def test_planning_gate_blocks_without_r1_design_review(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - sample-service

            ## Use Cases
            - Create quote.

            ## Acceptance Criteria
            - Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")

            result = implementation_gate.validate_gate(repo, design, kg, "planning", None)

        self.assertFalse(result["ready"])
        self.assertTrue(any("semantic review" in reason.lower() or "design" in reason.lower() for reason in result["blocked_reasons"]))

    def test_implementation_gate_blocks_without_r2_test_review(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - sample-service

            ## Use Cases
            - Create quote.

            ## Acceptance Criteria
            - Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            approval = repo / "approval.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            red.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            approval.write_text("Approval: user-approved\n", encoding="utf-8")
            review_dir = self.write_semantic_reviews(repo, phases=("design",))

            result = implementation_gate.validate_gate(
                repo,
                design,
                kg,
                "implementation",
                red,
                review_dirs=[review_dir],
                no_harness_state=True,
                harness_state_approval=approval,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("test" in reason.lower() for reason in result["blocked_reasons"]))

    def test_completion_gate_requires_coverage_and_unit_evidence(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - sample-service

            ## Use Cases
            - Create quote.

            ## Acceptance Criteria
            - Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Create quote | services/sample-service | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "business.md"
            approval = repo / "approval.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            approval.write_text("Approval: user-approved\n", encoding="utf-8")
            review_dir = self.write_semantic_reviews(repo)

            result = implementation_gate.validate_gate(
                repo,
                design,
                kg,
                "completion",
                red,
                matrix,
                unit,
                review,
                review_dirs=[review_dir],
                no_harness_state=True,
                harness_state_approval=approval,
            )

        self.assertTrue(result["ready"])
        self.assertEqual(1, result["coverage"]["coverage_rows"])
        self.assertTrue(result["spring_static_check"]["ready"])
        self.assertTrue(result["semantic_reviews"]["ready"])

    def test_completion_gate_validates_requirements_archive_when_supplied(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - sample-service

            ## Use Cases
            - Create quote.

            ## Acceptance Criteria
            - Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Create quote | services/sample-service | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "business.md"
            approval = repo / "approval.md"
            archive = repo / "docs" / "agent-runs" / "run" / "requirements-archive.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            archive.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            write_command_evidence(red, "mvn test -Dtest=PaymentCallbackTest", exit_code=1)
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            approval.write_text("Approval: user-approved\n", encoding="utf-8")
            archive.write_text("# Requirements Archive\n\n## Original Request\nBuild quote creation.\n", encoding="utf-8")
            review_dir = self.write_semantic_reviews(repo)

            result = implementation_gate.validate_gate(
                repo,
                design,
                kg,
                "completion",
                red,
                matrix,
                unit,
                review,
                review_dirs=[review_dir],
                requirements_archive=archive,
            )

        self.assertFalse(result["ready"])
        self.assertIsNotNone(result["requirements_archive"])
        self.assertTrue(any("requirements archive" in reason.lower() for reason in result["blocked_reasons"]))

    def test_completion_gate_requires_archive_when_explicitly_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            kg.parent.mkdir(parents=True)
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")

            result = implementation_gate.validate_gate(
                repo,
                None,
                kg,
                "completion",
                None,
                require_requirements_archive=True,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("--requirements-archive" in reason for reason in result["blocked_reasons"]))

    def test_completion_gate_auto_discovers_required_archive_from_agent_run(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - sample-service

            ## Use Cases
            - Create quote.

            ## Acceptance Criteria
            - Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Create quote | services/sample-service | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        archive_doc = textwrap.dedent(
            """
            # Requirements Archive

            ## Original Request
            Build quote creation.

            ## Final Clarified Requirement
            Return a quote for valid input.

            ## Scope And Non-Goals
            Scope: services/sample-service. Non-goals: billing.

            ## Acceptance Criteria Status
            | id | requirement | status | evidence |
            | --- | --- | --- | --- |
            | AC-1 | Quote is returned | verified | docs/agent-runs/run/evidence/coverage-matrix.md |

            ## Use Case Coverage
            UC-1 covers AC-1.

            ## Impacted Services APIs And Contracts
            services/sample-service; no contract change.

            ## Implementation Evidence
            docs/agent-runs/run/evidence/implementation-manifest.md

            ## Test Evidence
            docs/agent-runs/run/evidence/green-test.txt

            ## Review And Rework Summary
            R1/R2/R3 approved; no open rework.

            ## Deferred And Residual Risks
            None.

            ## Promoted Memory Entries
            None.

            ## Follow Up Opportunities
            None.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            run = repo / "docs" / "agent-runs" / "run"
            red = run / "evidence" / "red-test.txt"
            matrix = run / "evidence" / "coverage-matrix.md"
            unit = run / "evidence" / "green-test.txt"
            review = run / "evidence" / "business-review.md"
            archive = run / "requirements-archive.md"
            approval = repo / "approval.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            red.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            write_command_evidence(red, "mvn test -Dtest=CallbackTest", exit_code=1)
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            archive.write_text(archive_doc, encoding="utf-8")
            approval.write_text("Approval: user-approved\n", encoding="utf-8")
            review_dir = self.write_semantic_reviews(repo)

            result = implementation_gate.validate_gate(
                repo,
                design,
                kg,
                "completion",
                red,
                matrix,
                unit,
                review,
                review_dirs=[review_dir],
                require_requirements_archive=True,
                no_harness_state=True,
                harness_state_approval=approval,
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(result["requirements_archive"]["path"].replace("\\", "/").endswith("docs/agent-runs/run/requirements-archive.md"))
        self.assertEqual("auto", result["requirements_archive"]["source"])

    def test_unified_gate_requires_archive_for_strict_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            gate_result = {"ready": False, "blocked_reasons": ["missing archive"], "warnings": []}
            args = SimpleNamespace(
                repo=repo,
                design_doc=None,
                kg_status_file=None,
                phase="completion",
                red_test_evidence=None,
                coverage_matrix=None,
                unit_test_evidence=None,
                business_review=None,
                memory_updates=None,
                requirements_archive=None,
                require_requirements_archive=False,
                skip_spring_static_check=False,
                rework_dir=None,
                dependency_report=None,
                implementation_manifest=None,
                review_dir=None,
                handoff_dir=None,
                contract_dir=None,
                require_contracts=False,
                require_semantic_reviews=False,
                review_profile=None,
                strict_workflow=True,
                status_file=None,
            )

            with patch.object(e2e_dev_harness.implementation_gate, "validate_gate_request", return_value=gate_result) as validate:
                code, result = e2e_dev_harness.gate(args)

        self.assertEqual(2, code)
        self.assertEqual(gate_result, result)
        self.assertTrue(validate.call_args.args[0].require_requirements_archive)

    def test_completion_gate_blocks_missing_semantic_reviews_when_required(self) -> None:
        design_text = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - services/sample-service

            ## Use Cases
            - Create quote success and failure paths.

            ## Acceptance Criteria
            - AC-1 Quote is returned.

            ## Test Design
            - QuoteServiceTest covers success and failure paths.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Create quote success and failure paths | services/sample-service | QuoteServiceTest success/failure | QuoteService | reviewed success/failure | verified |
            """
        ).strip()
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | services/sample-service | services/sample-service/src/main/java/com/example/QuoteService.java | service | AC-1 explicit-requirement | yes | QuoteServiceTest | verified | done |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source = repo / "services" / "sample-service" / "src" / "main" / "java" / "com" / "example" / "QuoteService.java"
            source.parent.mkdir(parents=True)
            source.write_text("package com.example; class QuoteService {}\n", encoding="utf-8")
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "docs" / "agent-runs" / "run" / "evidence" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage-matrix.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "green-test.txt"
            business = repo / "docs" / "agent-runs" / "run" / "evidence" / "business-review.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            for path in (design, kg, red, matrix, unit, business, manifest_path):
                path.parent.mkdir(parents=True, exist_ok=True)
            review_dir.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Expected red test failed.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit)
            business.write_text("Business logic reviewed for success and failure.\n", encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")

            result = implementation_gate.validate_gate(
                repo,
                design,
                kg,
                "completion",
                red,
                matrix,
                unit,
                business,
                skip_spring_static_check=True,
                implementation_manifest=manifest_path,
                review_dirs=[review_dir],
                require_semantic_reviews=True,
            )

        self.assertFalse(result["ready"])
        self.assertIn("semantic_reviews", result)
        self.assertTrue(any("review" in reason.lower() for reason in result["blocked_reasons"]))

    def test_completion_gate_blocks_missing_required_manifest_for_multi_module_design(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Add VNPay.

            ## Affected services/modules
            - jeepay-core: constants and params
            - jeepay-service: config service
            - jeepay-payment: payment flow

            ## Use Cases
            - Merchant creates a VNPay QR order.

            ## Acceptance Criteria
            - AC-1 VnpayPaymentService returns a VNPay URL.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | VNPay URL is returned | Create QR order | jeepay-payment | VnpayPaymentServiceTest | VnpayPaymentService | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "vnpay.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl jeepay-payment -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")

            result = implementation_gate.validate_gate(
                repo,
                design,
                kg,
                "completion",
                red,
                matrix,
                unit,
                review,
                skip_spring_static_check=True,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Implementation manifest" in reason for reason in result["blocked_reasons"]))

    def test_completion_gate_blocks_incomplete_implementation_manifest(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Add VNPay.

            ## Affected services/modules
            - jeepay-core: constants and params
            - jeepay-service: config service
            - jeepay-payment: payment flow

            ## Use Cases
            - Merchant creates a VNPay QR order.

            ## Acceptance Criteria
            - AC-1 VnpayPaymentService returns a VNPay URL.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | VNPay URL is returned | Create QR order | jeepay-payment | VnpayPaymentServiceTest | VnpayPaymentService | reviewed | covered |
            """
        ).strip()
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | jeepay-core | jeepay-core/src/main/java/com/example/VnpayNormalMchParams.java | params | explicit-requirement | yes | VnpayNormalMchParamsTest | verified | done |
            | IM-2 | jeepay-payment | jeepay-payment/src/main/java/com/example/VnpayPaymentService.java | payment-service | explicit-requirement | yes | VnpayPaymentServiceTest | verified | done |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            for path in (
                "jeepay-core/src/main/java/com/example/VnpayNormalMchParams.java",
                "jeepay-payment/src/main/java/com/example/VnpayPaymentService.java",
            ):
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("class Placeholder {}\n", encoding="utf-8")
            design = repo / "docs" / "design" / "vnpay.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            approval = repo / "approval.md"
            approval = repo / "approval.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl jeepay-payment -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")

            result = implementation_gate.validate_gate(
                repo,
                design,
                kg,
                "completion",
                red,
                matrix,
                unit,
                review,
                skip_spring_static_check=True,
                implementation_manifest=manifest_path,
            )

        self.assertFalse(result["ready"])
        self.assertFalse(result["implementation_manifest"]["ready"])
        self.assertIn("jeepay-service", " ".join(result["blocked_reasons"]))

    def test_completion_gate_requires_design_doc_for_acceptance_coverage(self) -> None:
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Create quote | services/sample-service | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "business.md"
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")

            result = implementation_gate.validate_gate(repo, None, kg, "completion", red, matrix, unit, review)

        self.assertFalse(result["ready"])
        self.assertTrue(any("design document" in reason.lower() for reason in result["blocked_reasons"]))

    def test_completion_gate_blocks_unhandled_memory_updates_when_supplied(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - sample-service

            ## Use Cases
            - Create quote.

            ## Acceptance Criteria
            - Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Create quote | services/sample-service | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        proposed = textwrap.dedent(
            """
            # Proposed Memory Updates

            ### M-1

            - Type: decision
            - Source: design
            - Confidence: observed
            - Text: Quote timeout remains 3 seconds.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "business.md"
            memory_updates = repo / "docs" / "agent-runs" / "proposed-memory-updates.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            memory_updates.write_text(proposed, encoding="utf-8")

            result = implementation_gate.validate_gate(
                repo,
                design,
                kg,
                "completion",
                red,
                matrix,
                unit,
                review,
                memory_updates,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("memory update" in reason.lower() for reason in result["blocked_reasons"]))

    def test_completion_gate_blocks_open_rework_items(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - sample-service

            ## Use Cases
            - Create quote.

            ## Acceptance Criteria
            - Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Create quote | services/sample-service | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        rework = textwrap.dedent(
            """
            # Rework Item

            - Source: coverage-reviewer
            - Related AC: AC-1
            - Affected Services: services/sample-service
            - Problem Type: missing-code
            - Return Phase: tdd-implement
            - Required Red Test: QuoteServiceTest returns quote for AC-1
            - Evidence: Coverage reviewer found no code path for AC-1.
            - Exit Criteria: AC-1 coverage matrix row is verified.
            - Status: open
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            rework_file = repo / "docs" / "agent-runs" / "run" / "rework" / "rework-001.md"
            approval = repo / "approval.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            rework_file.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            rework_file.write_text(rework, encoding="utf-8")

            result = implementation_gate.validate_gate(repo, design, kg, "completion", red, matrix, unit, review)

        self.assertFalse(result["ready"])
        self.assertTrue(any("rework" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertEqual(1, result["rework"]["open_count"])

    def test_completion_gate_allows_verified_rework_items(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - sample-service

            ## Use Cases
            - Create quote.

            ## Acceptance Criteria
            - Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Create quote | services/sample-service | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        rework = textwrap.dedent(
            """
            # Rework Item

            - Source: coverage-reviewer
            - Related AC: AC-1
            - Affected Services: services/sample-service
            - Problem Type: missing-code
            - Return Phase: tdd-implement
            - Required Red Test: QuoteServiceTest returns quote for AC-1
            - Evidence: Coverage reviewer found no code path for AC-1.
            - Exit Criteria: Completion gate passes after code refs are added.
            - Status: verified
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            rework_file = repo / "docs" / "agent-runs" / "run" / "rework" / "rework-001.md"
            approval = repo / "approval.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            rework_file.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            rework_file.write_text(rework, encoding="utf-8")
            approval.write_text("Approval: user-approved\n", encoding="utf-8")
            review_dir = self.write_semantic_reviews(repo)

            result = implementation_gate.validate_gate(
                repo,
                design,
                kg,
                "completion",
                red,
                matrix,
                unit,
                review,
                review_dirs=[review_dir],
                no_harness_state=True,
                harness_state_approval=approval,
            )

        self.assertTrue(result["ready"])
        self.assertEqual(0, result["rework"]["open_count"])

    def test_completion_gate_blocks_deferred_rework_without_approval(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - sample-service

            ## Use Cases
            - Create quote.

            ## Acceptance Criteria
            - Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Create quote | services/sample-service | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        rework = textwrap.dedent(
            """
            # Rework Item

            - Source: user-review
            - Related AC: AC-1
            - Affected Services: services/sample-service
            - Problem Type: business-logic-risk
            - Return Phase: use-case-design
            - Required Red Test: QuoteServiceTest documents current risk
            - Evidence: Reviewer accepted deferring the edge case later.
            - Exit Criteria: Deferred item has explicit approval.
            - Status: deferred
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            rework_file = repo / "docs" / "agent-runs" / "run" / "rework" / "rework-001.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            rework_file.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            rework_file.write_text(rework, encoding="utf-8")

            result = implementation_gate.validate_gate(repo, design, kg, "completion", red, matrix, unit, review)

        self.assertFalse(result["ready"])
        self.assertTrue(any("approval" in reason.lower() for reason in result["blocked_reasons"]))

    def test_completion_gate_requires_dependency_report_for_cross_service_design(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Notify billing service when a quote is created.

            ## Scope
            - services/quote-service
            - services/billing-service

            ## Use Cases
            - quote-service publishes a DMQ topic consumed by billing-service.

            ## Acceptance Criteria
            - AC-1 Billing service consumes the quote.created topic.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Billing consumes topic | DMQ flow | services/quote-service, services/billing-service | QuoteTopicTest | QuotePublisher, QuoteListener | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            write_command_evidence(red, "mvn test -Dtest=CallbackTest", exit_code=1)
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")

            result = implementation_gate.validate_gate(
                repo,
                design,
                kg,
                "completion",
                red,
                matrix,
                unit,
                review,
                skip_spring_static_check=True,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("dependency report" in reason.lower() for reason in result["blocked_reasons"]))

    def test_completion_gate_blocks_unresolved_dependency_report(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Call billing service when a quote is created.

            ## Scope
            - services/quote-service
            - services/billing-service

            ## Use Cases
            - quote-service calls billing-service over HTTP.

            ## Acceptance Criteria
            - AC-1 Billing service receives the callback.

            ## Change Logic
            - Current behavior: quote creation does not call billing.
            - Target behavior: quote creation invokes the billing callback.
            - Runtime path: QuoteController -> QuoteService -> BillingClient -> BillingController.
            - State/data effect: sends callback request and updates billing callback status.

            ## Impact Summary
            - Source: GitNexus impact + dependency scanner
            - Raw Evidence: docs/agent-runs/run/evidence/impact-analysis.json

            | type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
            | --- | --- | --- | --- | --- | --- |
            | HTTP | quote-service -> billing-service callback | services/quote-service, services/billing-service | AC-1 | CallbackTest; contract ACK | high |

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Billing receives callback | HTTP flow | services/quote-service, services/billing-service | CallbackTest | BillingClient, BillingController | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            dependency_report = repo / "knowledge-graph" / "cross-service-dependencies.json"
            approval = repo / "approval.md"
            approval = repo / "approval.md"
            approval = repo / "approval.md"
            approval = repo / "approval.md"
            for path in (
                "services/quote-service/src/main/java/com/example/BillingClient.java",
                "services/billing-service/src/main/java/com/example/BillingController.java",
            ):
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("class Placeholder {}\n", encoding="utf-8")
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            write_command_evidence(red, "mvn test -Dtest=CallbackTest", exit_code=1)
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            dependency_report.write_text(
                json.dumps({"ready": False, "unresolved_questions": ["Confirm billing URL target."]}),
                encoding="utf-8",
            )

            result = implementation_gate.validate_gate(
                repo,
                design,
                kg,
                "completion",
                red,
                matrix,
                unit,
                review,
                dependency_report=dependency_report,
                skip_spring_static_check=True,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Confirm billing URL target" in reason for reason in result["blocked_reasons"]))

    def test_completion_gate_allows_verified_dependency_report(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Call billing service when a quote is created.

            ## Scope
            - services/quote-service
            - services/billing-service

            ## Use Cases
            - quote-service calls billing-service over HTTP.

            ## Acceptance Criteria
            - AC-1 Billing service receives the callback.

            ## Change Logic
            - Current behavior: quote creation does not call billing.
            - Target behavior: quote creation invokes the billing callback.
            - Runtime path: QuoteController -> QuoteService -> BillingClient -> BillingController.
            - State/data effect: sends callback request and updates billing callback status.

            ## Impact Summary
            - Source: GitNexus impact + dependency scanner
            - Raw Evidence: docs/agent-runs/run/evidence/impact-analysis.json

            | type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
            | --- | --- | --- | --- | --- | --- |
            | HTTP | quote-service -> billing-service callback | services/quote-service, services/billing-service | AC-1 | CallbackTest; contract ACK | high |

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Billing receives callback | HTTP flow | services/quote-service, services/billing-service | CallbackTest | BillingClient, BillingController | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            dependency_report = repo / "knowledge-graph" / "cross-service-dependencies.json"
            approval = repo / "approval.md"
            for path in (
                "services/quote-service/src/main/java/com/example/BillingClient.java",
                "services/billing-service/src/main/java/com/example/BillingController.java",
            ):
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("class Placeholder {}\n", encoding="utf-8")
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            write_command_evidence(red, "mvn test -Dtest=CallbackTest", exit_code=1)
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            manifest_path.write_text(
                textwrap.dedent(
                    """
                    | id | module | artifact | artifact_type | source | required | tests | status | evidence |
                    | --- | --- | --- | --- | --- | --- | --- | --- | --- |
                    | IM-1 | services/quote-service | services/quote-service/src/main/java/com/example/BillingClient.java | client | AC-1 dependency-report | yes | CallbackTest | verified | done |
                    | IM-2 | services/billing-service | services/billing-service/src/main/java/com/example/BillingController.java | controller | AC-1 dependency-report | yes | CallbackTest | verified | done |
                    """
                ).strip(),
                encoding="utf-8",
            )
            dependency_report.write_text(
                json.dumps(
                    {
                        "ready": True,
                        "tool_priority": ["gitnexus", "deterministic-scan"],
                        "gitnexus": {"primary": True, "available": True, "verified": True},
                        "dependencies": [{"kind": "http"}],
                        "unresolved_questions": [],
                    }
                ),
                encoding="utf-8",
            )
            approval.write_text("Approval: user-approved\n", encoding="utf-8")
            review_dir = self.write_semantic_reviews(repo)

            result = implementation_gate.validate_gate(
                repo,
                design,
                kg,
                "completion",
                red,
                matrix,
                unit,
                review,
                dependency_report=dependency_report,
                implementation_manifest=manifest_path,
                review_dirs=[review_dir],
                skip_spring_static_check=True,
                no_harness_state=True,
                harness_state_approval=approval,
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(result["dependency_report"]["ready"])

    def test_completion_gate_blocks_task_drift_changed_files(self) -> None:
        design_text = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - services/sample-service

            ## Use Cases
            - Return a quote.

            ## Acceptance Criteria
            - AC-1 Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Quote success and failure | services/sample-service | QuoteServiceTest success/failure | QuoteService#create | reviewed | verified |
            """
        ).strip()
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | services/sample-service | services/sample-service/src/main/java/com/example/QuoteService.java | service | AC-1 | yes | QuoteServiceTest | verified | done |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source = repo / "services/sample-service/src/main/java/com/example/QuoteService.java"
            source.parent.mkdir(parents=True)
            source.write_text("class QuoteService {}\n", encoding="utf-8")
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.json"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            changed = repo / "docs" / "agent-runs" / "run" / "evidence" / "changed-files.txt"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            write_command_evidence(red, "mvn test -Dtest=CallbackTest", exit_code=1)
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit)
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")
            changed.write_text(
                "services/ledger-service/src/main/java/com/example/LedgerService.java\n",
                encoding="utf-8",
            )

            with patch.object(implementation_gate.reviewer_gate, "validate", return_value={"ready": True, "blocked_reasons": [], "warnings": []}):
                result = implementation_gate.validate_gate(
                    repo,
                    design,
                    kg,
                    "completion",
                    red,
                    matrix,
                    unit,
                    review,
                    implementation_manifest=manifest_path,
                    changed_files=changed,
                    skip_spring_static_check=True,
                    require_semantic_reviews=False,
                )

        self.assertFalse(result["ready"])
        self.assertTrue(any("outside declared task scope" in reason for reason in result["blocked_reasons"]))
        self.assertEqual("plan", result["task_alignment"]["correction_actions"][0]["return_phase"])

    def test_completion_gate_blocks_unsatisfied_test_impact_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.json"
            plan = repo / "docs" / "agent-runs" / "run" / "evidence" / "test-impact-plan.json"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            unit.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Goal
                    - Return a quote.

                    ## Scope
                    - services/sample-service

                    ## Use Cases
                    - Return a quote.

                    ## Acceptance Criteria
                    - AC-1 Quote is returned.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            write_command_evidence(unit, "mvn test")
            plan.write_text(
                json.dumps(
                    {
                        "schema": test_impact_plan.SCHEMA,
                        "status": "ready",
                        "commands": [
                            {
                                "id": "TST-001",
                                "command": "mvn -pl services/sample-service -am test",
                                "required": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            ready_result = {"ready": True, "blocked_reasons": [], "warnings": []}
            with patch.object(implementation_gate.tdd_evidence, "validate", return_value=ready_result), \
                patch.object(implementation_gate.coverage_gate, "validate", return_value=ready_result), \
                patch.object(implementation_gate.implementation_manifest_gate, "validate", return_value=ready_result), \
                patch.object(implementation_gate.task_alignment_guard, "validate", return_value=ready_result), \
                patch.object(implementation_gate.cross_service_dependency_scan, "validate_dependency_report", return_value=ready_result), \
                patch.object(implementation_gate.reviewer_gate, "validate", return_value=ready_result), \
                patch.object(implementation_gate.rework_gate, "validate", return_value=ready_result):
                result = implementation_gate.validate_gate(
                    repo,
                    design,
                    kg,
                    "completion",
                    None,
                    None,
                    unit,
                    None,
                    test_impact_plan=plan,
                    skip_spring_static_check=True,
                )

        self.assertFalse(result["ready"])
        self.assertFalse(result["test_impact_plan"]["ready"])
        self.assertTrue(any("Required test impact command" in reason for reason in result["blocked_reasons"]))

    def test_end_to_end_harness_plan_gate_completion_flow(self) -> None:
        design_text = textwrap.dedent(
            """
            # Quote

            ## Goal
            - Return a quote.

            ## Scope
            - services/sample-service

            ## Use Cases
            - Return a quote.

            ## Acceptance Criteria
            - AC-1 Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Quote success and failure | services/sample-service | QuoteServiceTest success/failure | QuoteService#create | reviewed | verified |
            """
        ).strip()
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | services/sample-service | services/sample-service/src/main/java/com/example/QuoteService.java | service | AC-1 | yes | QuoteServiceTest | verified | done |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "pom.xml").write_text(
                textwrap.dedent(
                    """
                    <project>
                      <modules>
                        <module>services/sample-service</module>
                      </modules>
                    </project>
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            service = repo / "services" / "sample-service"
            service.mkdir(parents=True)
            (service / "pom.xml").write_text("<project />\n", encoding="utf-8")
            source = service / "src" / "main" / "java" / "com" / "example" / "QuoteService.java"
            source.parent.mkdir(parents=True)
            source.write_text("class QuoteService {}\n", encoding="utf-8")
            design = repo / "docs" / "design" / "quote.md"
            design.parent.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")
            plan_args = SimpleNamespace(
                repo=repo,
                mode="single-review",
                design_doc=design,
                agent_run_dir="docs/agent-runs/run",
                run_date="2026-05-23",
                path=None,
                service=["services/sample-service"],
                service_scope="affected",
                dependency_report=None,
                workflow_tier="standard",
                create_archive=True,
                write_exec_plan=None,
                status_file=None,
            )

            plan_code, plan_result = e2e_dev_harness.plan(plan_args)
            artifacts = plan_result["handoff_artifacts"]
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / artifacts["red_test_evidence"]
            matrix = repo / artifacts["coverage_matrix"]
            unit = repo / artifacts["green_test_evidence"]
            review = repo / artifacts["business_review"]
            manifest_path = repo / artifacts["implementation_manifest"]
            changed = repo / "docs" / "agent-runs" / "run" / "evidence" / "changed-files.txt"
            kg.parent.mkdir(parents=True)
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.parent.mkdir(parents=True, exist_ok=True)
            write_command_evidence(red, "mvn test -Dtest=CallbackTest", exit_code=1)
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")
            changed.write_text("services/sample-service/src/main/java/com/example/QuoteService.java\n", encoding="utf-8")
            test_plan_path = repo / artifacts["test_impact_plan"]
            test_plan_path.write_text(
                json.dumps(
                    test_impact_plan.build_plan(
                        repo,
                        ["services/sample-service/src/main/java/com/example/QuoteService.java"],
                    ),
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            review_dir = self.write_semantic_reviews(repo)
            service_review_helper = None  # using conftest.write_service_review
            write_service_review(repo, "sample-service", "test")
            service_r3 = write_service_review(repo, "sample-service", "implementation")
            service_r3.write_text(
                service_r3.read_text(encoding="utf-8")
                + "\n\n## Code Path Trace\n\n- AC-1: Controller -> QuoteService#create -> response.\n",
                encoding="utf-8",
            )
            implementation_args = SimpleNamespace(
                repo=repo,
                design_doc=design,
                kg_status_file=kg,
                phase="implementation",
                red_test_evidence=red,
                coverage_matrix=None,
                unit_test_evidence=None,
                business_review=None,
                memory_updates=None,
                requirements_archive=None,
                require_requirements_archive=False,
                dependency_report=None,
                implementation_manifest=None,
                changed_files=None,
                test_impact_plan=None,
                base_ref=None,
                rework_dir=None,
                review_dir=[review_dir],
                review_profile=None,
                handoff_dir=None,
                contract_dir=None,
                require_contracts=False,
                require_handoffs=False,
                require_semantic_reviews=False,
                skip_spring_static_check=True,
                run_state=repo / artifacts["run_state"],
                status_file=None,
            )
            completion_values = vars(implementation_args).copy()
            completion_values.update(
                {
                    "phase": "completion",
                    "coverage_matrix": matrix,
                    "unit_test_evidence": unit,
                    "business_review": review,
                    "implementation_manifest": manifest_path,
                    "changed_files": changed,
                }
            )
            completion_args = SimpleNamespace(**completion_values)

            implementation_code, implementation_result = e2e_dev_harness.gate(implementation_args)
            completion_code, completion_result = e2e_dev_harness.gate(completion_args)

        self.assertEqual(0, plan_code, plan_result)
        self.assertEqual(0, implementation_code, implementation_result)
        self.assertEqual("IMPLEMENTED", implementation_result["run_state_transition"]["lifecycle"])
        self.assertEqual(0, completion_code, completion_result)
        self.assertTrue(completion_result["task_alignment"]["ready"], completion_result["task_alignment"]["blocked_reasons"])




if __name__ == "__main__":
    unittest.main()
