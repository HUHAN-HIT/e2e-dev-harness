from __future__ import annotations

import io
import importlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import clarification_gate  # noqa: E402
import agent_instructions  # noqa: E402
import ac_progress_gate  # noqa: E402
import agent_scheduler  # noqa: E402
import artifact_registry  # noqa: E402
import checkpoint_gate  # noqa: E402
import command_evidence  # noqa: E402
import context_pack  # noqa: E402
import coverage_gate  # noqa: E402
import cross_service_dependency_scan  # noqa: E402
import dispatcher  # noqa: E402
import e2e_dev_harness  # noqa: E402
import handoff_gate  # noqa: E402
import harness_policy  # noqa: E402
import harness_verify  # noqa: E402
import contract_gate  # noqa: E402
import execution_trace  # noqa: E402
import implementation_gate  # noqa: E402
import implementation_manifest  # noqa: E402
import install_hooks  # noqa: E402
import harness_stop_guard  # noqa: E402
import kg_refresh  # noqa: E402
import memory_capture  # noqa: E402
import orchestration_plan  # noqa: E402
import auto_transition  # noqa: E402
import phase_guard  # noqa: E402
import run_summary  # noqa: E402
import run_state  # noqa: E402
import session_checkpoint  # noqa: E402
import requirements_archive  # noqa: E402
import service_design_gate  # noqa: E402
import superpowers_probe  # noqa: E402
import task_tier  # noqa: E402
import task_alignment_guard  # noqa: E402
import test_impact_plan  # noqa: E402
import tdd_evidence  # noqa: E402
import reviewer_gate  # noqa: E402
import rework_gate  # noqa: E402
import workflow_guard  # noqa: E402
from common import split_command  # noqa: E402


def implementation_gate_payload(red_path: Path) -> dict:
    return {
        "phase": "implementation",
        "ready": True,
        "knowledge_graph_status_loaded": True,
        "tdd": {"ready": True, "red_evidence": str(red_path)},
        "semantic_reviews": {"ready": True, "covered_phases": ["design", "test"]},
    }


def write_command_evidence(path: Path, command: str = "mvn test", exit_code: int = 0) -> None:
    path.write_text(
        json.dumps(
            {
                "command": command,
                "exit_code": exit_code,
                "stdout_tail": "BUILD SUCCESS" if exit_code == 0 else "BUILD FAILURE expected failing test",
                "stderr_tail": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def write_role_template(repo: Path, path: Path) -> None:
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(
        textwrap.dedent(
            """
            # Role

            ## Role Boundary
            Own exactly one scheduled task.

            ## Allowed Inputs
            Use only the context pack inputs.

            ## Forbidden
            Do not inherit coordinator chat context.

            ## Required Outputs
            Write only scheduled outputs.

            ## Done When
            Return evidence paths for scheduled outputs.
            """
        ).strip(),
        encoding="utf-8",
    )


def write_ready_handoff(repo: Path, path: Path, agent_id: str = "requirements-agent") -> None:
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    evidence = full.parents[1] / "evidence" / "requirements-summary.md"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("Requirements clarification evidence.\n", encoding="utf-8")
    evidence_ref = evidence.relative_to(repo).as_posix()
    evidence_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
    full.write_text(
        textwrap.dedent(
            f"""
            ---
            agent: requirements-clarifier
            agent_id: {agent_id}
            status: ready
            inputs:
              - user request
            outputs:
              - {evidence_ref}
            input_hashes:
              - user-request sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
            output_hashes:
              - {evidence_ref} sha256:{evidence_hash}
            consumed_by:
              - code-developer
            open_questions: None
            ---

            ## Summary
            Requirements are clarified for dispatch.

            ## Facts Used
            User request and service scope were reviewed.

            ## Decisions Made
            The downstream task may use the scheduled context pack.

            ## Open Questions
            None

            ## Downstream Assumptions
            The implementation agent will stay inside scheduled outputs.

            ## Verification Evidence
            Ready marker hash matches this handoff file.
            """
        ).strip(),
        encoding="utf-8",
    )
    marker = full.with_suffix(".ready.json")
    marker.write_text(
        json.dumps(
            {
                "path": full.name,
                "sha256": hashlib.sha256(full.read_bytes()).hexdigest(),
                "producer_agent": agent_id,
                "status": "ready",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def mark_dispatch_running(repo: Path, state_path: Path, task_id: str, agent: str) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    dispatch = {
        "status": "worker_running",
        "runtime": "codex",
        "current_task_id": task_id,
        "current_agent": agent,
        "worker_handle": f"worker-{task_id}",
        "worker_session": f"worker-session-{task_id}",
    }
    state["dispatch"] = dispatch
    state.setdefault("dispatches", {})[task_id] = dispatch
    run_state.write_state(repo, state_path, state)


def complete_dispatched_task(repo: Path, schedule_path: Path, state_path: Path, task_id: str, agent: str, evidence: list[str]) -> dict:
    mark_dispatch_running(repo, state_path, task_id, agent)
    return dispatcher.dispatch_complete(repo, schedule_path, state_path, task_id, agent, evidence)


def write_implemented_state(repo: Path, state_path: Path, state: dict) -> None:
    state["lifecycle"] = "PLANNED"
    run_state.write_state(repo, state_path, state)
    evidence = state_path.parent / "evidence" / "implementation-gate.json"
    red = state_path.parent / "evidence" / "red-test.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    red.write_text("expected failing test\n", encoding="utf-8")
    evidence.write_text(json.dumps(implementation_gate_payload(red)), encoding="utf-8")
    result = run_state.transition_state(
        repo,
        state_path,
        "IMPLEMENTED",
        gate="implementation",
        gate_status="passed",
        evidence=evidence,
    )
    if not result["ready"]:
        raise AssertionError(result["blocked_reasons"])


class ClarificationGateTests(unittest.TestCase):
    def test_resolved_open_questions_without_none_marker_are_clear(self) -> None:
        clear, unresolved = clarification_gate.open_questions_clear(
            "All API behavior is covered by the acceptance criteria."
        )

        self.assertTrue(clear)
        self.assertEqual([], unresolved)

    def test_ambiguous_open_questions_without_resolution_marker_are_blocking(self) -> None:
        clear, unresolved = clarification_gate.open_questions_clear("Retry policy")

        self.assertFalse(clear)
        self.assertEqual(["Retry policy"], unresolved)

    def test_unresolved_open_questions_are_blocking(self) -> None:
        clear, unresolved = clarification_gate.open_questions_clear(
            "- TODO confirm retry policy\n- TBD timeout value"
        )

        self.assertFalse(clear)
        self.assertEqual(2, len(unresolved))

    def test_non_goals_heading_does_not_satisfy_goal_requirement(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Non-Goals
            - No public API change.

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
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path)

        self.assertIn("goal", result["missing_sections"])
        self.assertFalse(result["ready_for_implementation"])

    def test_empty_required_section_blocks_implementation(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal

            ## Scope
            - sample-service

            ## Use Cases
            - Create quote.

            ## Acceptance Criteria
            - AC-1 Quote is returned.

            ## Test Design
            - QuoteServiceTest covers success and failure paths.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path)

        self.assertFalse(result["ready_for_implementation"])
        self.assertIn("goal", result["empty_sections"])

    def test_require_intent_blocks_missing_restated_intent(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return checkout quotes.

            ## Scope
            - services/checkout-service

            ## Use Cases
            - Customer requests a checkout quote.

            ## Acceptance Criteria
            - AC-1 Checkout quote is returned.

            ## Test Design
            - CheckoutServiceTest covers quote creation.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path, require_intent=True)

        self.assertFalse(result["ready_for_implementation"])
        self.assertIn("restated_intent", result["missing_sections"])

    def test_require_intent_accepts_restated_intent(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Restated Intent
            - The user wants checkout quotes to be returned without changing payment capture.

            ## Goal
            - Return checkout quotes.

            ## Scope
            - services/checkout-service

            ## Use Cases
            - Customer requests a checkout quote.

            ## Acceptance Criteria
            - AC-1 Checkout quote is returned.

            ## Test Design
            - CheckoutServiceTest covers quote creation.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path, require_intent=True)

        self.assertTrue(result["ready_for_implementation"], result)

    def test_mq_requirement_requires_cross_layer_sender_call_chain(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Publish a payment callback event.

            ## Scope
            - services/payment-service

            ## Use Cases
            - Payment succeeds and publishes a DMQ notification.

            ## Acceptance Criteria
            - AC-1 Publish DMQ callback notification after payment succeeds.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path)

        self.assertFalse(result["ready_for_implementation"])
        self.assertTrue(any("sender" in reason.lower() or "call chain" in reason.lower() for reason in result["integration_gaps"]))

    def test_mq_requirement_allows_explicit_sender_call_chain(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Publish a payment callback event.

            ## Scope
            - services/payment-service

            ## Use Cases
            - Payment succeeds and publishes a DMQ notification.

            ## Acceptance Criteria
            - AC-1 Publish DMQ callback notification after payment succeeds.

            ## Integration Call Chain
            - PaymentController -> PaymentService -> PaymentCallbackDmqSender.send(topic, tag, payload).
            - Sender injection: PaymentService constructor injects PaymentCallbackDmqSender.

            ## Change Logic
            - Current behavior: payment success has no callback notification.
            - Target behavior: payment success publishes a DMQ callback.
            - Runtime path: PaymentController -> PaymentService -> PaymentCallbackDmqSender.send(topic, tag, payload).
            - State/data effect: emits payload fields for payment id, status, and callback timestamp.

            ## Impact Summary
            - Source: GitNexus impact + dependency scanner
            - Raw Evidence: docs/agent-runs/run/evidence/impact-analysis.json

            | type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
            | --- | --- | --- | --- | --- | --- |
            | MQ | topic=payment_callback, tag=success | settlement-service | AC-1 | sender payload test; consumer ACK | high |

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path)

        self.assertTrue(result["ready_for_implementation"], result)
        self.assertEqual([], result["integration_gaps"])

    def test_interface_requirement_requires_bounded_impact_summary(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Add a refund callback API.

            ## Scope
            - services/payment-service

            ## Use Cases
            - Merchant calls HTTP refund callback endpoint.

            ## Acceptance Criteria
            - AC-1 POST /api/refunds/callback returns accepted status.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path)

        self.assertFalse(result["ready_for_implementation"])
        self.assertTrue(any("Impact Summary" in reason for reason in result["impact_gaps"]))

    def test_interface_requirement_requires_change_logic(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Add a refund callback API.

            ## Scope
            - services/payment-service

            ## Use Cases
            - Merchant calls HTTP refund callback endpoint.

            ## Acceptance Criteria
            - AC-1 POST /api/refunds/callback returns accepted status.

            ## Impact Summary
            - Source: GitNexus impact + dependency scanner
            - Raw Evidence: docs/agent-runs/run/evidence/impact-analysis.json

            | type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
            | --- | --- | --- | --- | --- | --- |
            | HTTP | POST /api/refunds/callback | merchant-admin | AC-1 | controller contract test | medium |

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path)

        self.assertFalse(result["ready_for_implementation"])
        self.assertTrue(any("Change Logic" in reason for reason in result["change_logic_gaps"]))

    def test_impact_summary_requires_raw_evidence_reference_and_interface_rows(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Add a refund callback API.

            ## Scope
            - services/payment-service

            ## Use Cases
            - Merchant calls HTTP refund callback endpoint.

            ## Acceptance Criteria
            - AC-1 POST /api/refunds/callback returns accepted status.

            ## Impact Summary
            - Source: GitNexus impact

            | type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
            | --- | --- | --- | --- | --- | --- |
            | HTTP | POST /api/refunds/callback | merchant-admin | AC-1 | controller contract test | medium |

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path)

        self.assertFalse(result["ready_for_implementation"])
        self.assertTrue(any("Raw Evidence" in reason for reason in result["impact_gaps"]))

    def test_impact_summary_allows_gitnexus_evidence_and_affected_interfaces(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Add a refund callback API.

            ## Scope
            - services/payment-service

            ## Use Cases
            - Merchant calls HTTP refund callback endpoint.

            ## Acceptance Criteria
            - AC-1 POST /api/refunds/callback returns accepted status.

            ## Change Logic
            - Current behavior: no public refund callback endpoint exists.
            - Target behavior: POST /api/refunds/callback accepts merchant refund callback requests.
            - Runtime path: RefundCallbackController -> RefundCallbackService -> RefundRepository.
            - State/data effect: persists refund status field and response body.

            ## Impact Summary
            - Source: GitNexus impact + dependency scanner
            - Raw Evidence: docs/agent-runs/run/evidence/impact-analysis.json

            | type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
            | --- | --- | --- | --- | --- | --- |
            | HTTP | POST /api/refunds/callback | merchant-admin | AC-1 | controller contract test | medium |

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path)

        self.assertTrue(result["ready_for_implementation"], result)
        self.assertEqual([], result["impact_gaps"])

    def test_impact_summary_blocks_large_raw_gitnexus_dump(self) -> None:
        rows = "\n".join(
            f"| HTTP | GET /api/orders/{index} | caller-{index} | AC-1 | contract test | low |"
            for index in range(1, 15)
        )
        rows = rows.replace("\n", "\n            ")
        markdown = textwrap.dedent(
            f"""
            # Feature

            ## Goal
            - Add a refund callback API.

            ## Scope
            - services/payment-service

            ## Use Cases
            - Merchant calls HTTP refund callback endpoint.

            ## Acceptance Criteria
            - AC-1 POST /api/refunds/callback returns accepted status.

            ## Impact Summary
            - Source: GitNexus impact
            - Raw Evidence: docs/agent-runs/run/evidence/impact-analysis.json

            | type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
            | --- | --- | --- | --- | --- | --- |
            {rows}

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path)

        self.assertFalse(result["ready_for_implementation"])
        self.assertTrue(any("bounded" in reason.lower() for reason in result["impact_gaps"]))


class CommandSplitTests(unittest.TestCase):
    def test_simple_graph_command_splits_without_shell(self) -> None:
        self.assertEqual(["graphify", "update", "."], split_command("graphify update ."))

    def test_shell_control_operators_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            split_command("graphify update . && echo unsafe")


class CommandEvidenceTests(unittest.TestCase):
    def test_command_evidence_captures_exit_code_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = command_evidence.run_command(Path(tmp), f"{sys.executable} -c \"print('ok')\"", timeout_seconds=30)

        self.assertEqual(0, result["exit_code"])
        self.assertEqual("e2e-dev-harness.command-evidence.v1", result["schema"])
        self.assertIn("ok", result["stdout_tail"])
        self.assertEqual(64, len(result["stdout_sha256"]))

    def test_command_evidence_rejects_shell_control_operators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = command_evidence.run_command(Path(tmp), "python -V && echo unsafe", timeout_seconds=30)

        self.assertEqual(2, result["exit_code"])
        self.assertIn("Shell control operators", result["stderr_tail"])


class TddEvidenceTests(unittest.TestCase):
    def test_basic_tdd_accepts_lightweight_red_failure_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            red = repo / "red.txt"
            red.write_text("Red test failed for expected reason in QuoteServiceTest.\n", encoding="utf-8")

            result = tdd_evidence.validate(repo, red, mode="basic")

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("basic", result["effective_mode"])

    def test_strict_tdd_blocks_red_command_that_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            red = repo / "red.json"
            write_command_evidence(red, "mvn -pl services/a -am test", exit_code=0)

            result = tdd_evidence.validate(repo, red, mode="strict")

        self.assertFalse(result["ready"])
        self.assertTrue(any("unexpectedly passed" in reason for reason in result["blocked_reasons"]))

    def test_strict_tdd_completion_requires_green_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            red = repo / "red.json"
            green = repo / "green.json"
            write_command_evidence(red, "mvn -pl services/a -am test", exit_code=1)
            write_command_evidence(green, "mvn -pl services/a -am test", exit_code=0)

            result = tdd_evidence.validate(repo, red, green, phase="completion", mode="strict")

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(1, result["red_commands"][0]["exit_code"])
        self.assertEqual(0, result["green_commands"][0]["exit_code"])

    def test_auto_tdd_uses_strict_for_critical_tier(self) -> None:
        self.assertEqual("strict", tdd_evidence.resolve_mode("auto", "critical"))
        self.assertEqual("basic", tdd_evidence.resolve_mode("auto", "standard"))


class CheckpointGateTests(unittest.TestCase):
    def test_checkpoint_gate_blocks_missing_required_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = checkpoint_gate.validate(repo, None, ["clarify"], "required")

        self.assertFalse(result["ready"])
        self.assertTrue(any("clarify" in reason for reason in result["blocked_reasons"]))

    def test_checkpoint_gate_accepts_approved_markdown_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            confirmation = repo / "docs" / "agent-runs" / "run" / "confirmations" / "clarify.md"
            confirmation.parent.mkdir(parents=True)
            confirmation.write_text(
                textwrap.dedent(
                    """
                    # Clarify Confirmation

                    - Phase: clarify
                    - Status: approved
                    - Confirmed By: user
                    - Decision: continue
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = checkpoint_gate.validate(repo, [confirmation.parent], ["clarify"], "required")

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["clarify"], [item["phase"] for item in result["confirmations"]])

    def test_checkpoint_gate_advisory_downgrades_missing_confirmation_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = checkpoint_gate.validate(Path(tmp), None, ["clarify"], "advisory")

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(any("clarify" in warning for warning in result["warnings"]))


class PlanSchedulingDecisionTests(unittest.TestCase):
    def test_plan_result_contains_scheduling_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            service = repo / "services" / "order-service"
            (service / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
            (service / "pom.xml").write_text("<project />\n", encoding="utf-8")
            (service / "src" / "main" / "java" / "com" / "example" / "AppConfig.java").write_text(
                "@Configuration\npublic class AppConfig {}\n",
                encoding="utf-8",
            )
            (repo / "pom.xml").write_text(
                textwrap.dedent(
                    """
                    <project xmlns="http://maven.apache.org/POM/4.0.0">
                      <modelVersion>4.0.0</modelVersion>
                      <modules>
                        <module>services/order-service</module>
                      </modules>
                    </project>
                    """
                ).strip(),
                encoding="utf-8",
            )
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True, exist_ok=True)
            design.write_text(
                "\n".join(
                    [
                        "# Feature",
                        "",
                        "## Scope",
                        "- services/order-service",
                        "",
                        "## Acceptance Criteria",
                        "- AC-1: Validate order.",
                        "- AC-2: Persist audit.",
                    ]
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                repo=repo,
                mode="single-review",
                design_doc=design,
                agent_run_dir=None,
                run_date=None,
                service_scope="affected",
                service=["services/order-service"],
                path=None,
                dependency_report=None,
                create_archive=False,
                write_exec_plan=None,
                status_file=None,
            )

            code, result = e2e_dev_harness.plan(args)

        self.assertEqual(0, code)
        self.assertEqual("split-single", result["scheduling_decision"]["execution_model"])
        self.assertEqual(
            result["scheduling_decision"],
            result["agent_schedule"]["scheduling_decision"],
        )


class KnowledgeGraphRefreshTests(unittest.TestCase):
    def test_detect_finds_maven_service_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "pom.xml").write_text(
                textwrap.dedent(
                    """
                    <project xmlns="http://maven.apache.org/POM/4.0.0">
                      <modelVersion>4.0.0</modelVersion>
                      <modules>
                        <module>services/order-service</module>
                      </modules>
                    </project>
                    """
                ).strip(),
                encoding="utf-8",
            )
            service = repo / "services" / "order-service"
            (service / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
            (service / "pom.xml").write_text("<project />", encoding="utf-8")
            (service / "src" / "main" / "java" / "com" / "example" / "AppConfig.java").write_text(
                "@Configuration\npublic class AppConfig {}\n",
                encoding="utf-8",
            )

            result = kg_refresh.detect(repo)

        self.assertEqual(["services/order-service"], result["service_candidates"])
        self.assertIn("gitnexus", kg_refresh.choose_tools("auto", result))

    def test_run_command_rejects_shell_control_operators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = kg_refresh.run_command("graphify update . && echo unsafe", Path(tmp))

        self.assertEqual(2, result["exit_code"])
        self.assertIn("Shell control operators", result["stderr_tail"])

    def test_run_command_reports_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            kg_refresh.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["gitnexus", "analyze", "."], 600, output="partial"),
        ):
            result = kg_refresh.run_command("gitnexus analyze .", Path(tmp))

        self.assertEqual(124, result["exit_code"])
        self.assertIn("timed out", result["stderr_tail"])


class AgentInstructionScopeTests(unittest.TestCase):
    def test_harness_environment_variables_override_legacy_workflow_names(self) -> None:
        with patch.dict(
            os.environ,
            {
                "E2E_DEV_WORKFLOW_AGENT_INSTRUCTIONS_MODE": "off",
                "E2E_DEV_HARNESS_AGENT_INSTRUCTIONS_MODE": "strict",
                "E2E_DEV_WORKFLOW_AGENT_MODE": "single",
                "E2E_DEV_HARNESS_AGENT_MODE": "multi",
                "E2E_DEV_WORKFLOW_MEMORY_MODE": "off",
                "E2E_DEV_HARNESS_MEMORY_MODE": "auto",
                "E2E_DEV_WORKFLOW_SUPERPOWERS_MODE": "off",
                "E2E_DEV_HARNESS_SUPERPOWERS_MODE": "strict",
            },
            clear=False,
        ):
            self.assertEqual(
                "strict",
                agent_instructions.env_default(
                    "E2E_DEV_HARNESS_AGENT_INSTRUCTIONS_MODE",
                    "E2E_DEV_WORKFLOW_AGENT_INSTRUCTIONS_MODE",
                    "auto",
                ),
            )
            self.assertEqual("multi", orchestration_plan.env_default("E2E_DEV_HARNESS_AGENT_MODE", "E2E_DEV_WORKFLOW_AGENT_MODE", "auto"))
            self.assertEqual("auto", memory_capture.env_default("E2E_DEV_HARNESS_MEMORY_MODE", "E2E_DEV_WORKFLOW_MEMORY_MODE", "strict"))
            self.assertEqual("strict", superpowers_probe.env_default("E2E_DEV_HARNESS_SUPERPOWERS_MODE", "E2E_DEV_WORKFLOW_SUPERPOWERS_MODE", "auto"))

    def test_legacy_workflow_environment_variables_remain_supported(self) -> None:
        with patch.dict(os.environ, {"E2E_DEV_WORKFLOW_AGENT_MODE": "single-review"}, clear=False):
            os.environ.pop("E2E_DEV_HARNESS_AGENT_MODE", None)

            result = orchestration_plan.env_default("E2E_DEV_HARNESS_AGENT_MODE", "E2E_DEV_WORKFLOW_AGENT_MODE", "auto")

        self.assertEqual("single-review", result)

    def test_unknown_scope_loads_root_only_and_discovers_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "AGENT.md").write_text("# Root\n", encoding="utf-8")
            for service in ("a", "b", "c"):
                service_dir = repo / "services" / service
                (service_dir / "src").mkdir(parents=True)
                (service_dir / "AGENT.md").write_text(f"# Service {service}\n", encoding="utf-8")

            result = agent_instructions.scan(
                repo,
                include_content=True,
                max_chars=12000,
                paths=None,
                scope="auto",
            )

        self.assertEqual(["AGENT.md"], result["load_order"])
        self.assertEqual(["AGENT.md"], list(result["instruction_contents"]))
        self.assertEqual(
            ["services/a", "services/b", "services/c"],
            [item["service_dir"] for item in result["discovered_service_agent_files"]],
        )
        self.assertEqual([], result["service_agent_files"])
        self.assertEqual("discovery", result["resolved_scope"])

    def test_path_scoped_scan_loads_only_affected_service_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "AGENT.md").write_text("# Root\n", encoding="utf-8")
            for service in ("a", "b"):
                service_dir = repo / "services" / service
                (service_dir / "src").mkdir(parents=True)
                (service_dir / "AGENT.md").write_text(f"# Service {service}\n", encoding="utf-8")

            result = agent_instructions.scan(
                repo,
                include_content=False,
                max_chars=12000,
                paths=["services/a/src/Main.java"],
                scope="auto",
            )

        self.assertEqual(["AGENT.md", "services/a/AGENT.md"], result["load_order"])
        self.assertEqual(["services/a"], [item["service_dir"] for item in result["service_agent_files"]])
        self.assertEqual("affected", result["resolved_scope"])

    def test_all_scope_keeps_legacy_full_service_loading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "AGENT.md").write_text("# Root\n", encoding="utf-8")
            for service in ("a", "b"):
                service_dir = repo / "services" / service
                (service_dir / "src").mkdir(parents=True)
                (service_dir / "AGENT.md").write_text(f"# Service {service}\n", encoding="utf-8")

            result = agent_instructions.scan(
                repo,
                include_content=False,
                max_chars=12000,
                paths=None,
                scope="all",
            )

        self.assertEqual(["AGENT.md", "services/a/AGENT.md", "services/b/AGENT.md"], result["load_order"])
        self.assertEqual(["services/a", "services/b"], [item["service_dir"] for item in result["service_agent_files"]])
        self.assertEqual("all", result["resolved_scope"])

    def test_strict_affected_scope_blocks_unknown_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "AGENT.md").write_text("# Root\n", encoding="utf-8")
            service_dir = repo / "services" / "a"
            (service_dir / "src").mkdir(parents=True)
            (service_dir / "AGENT.md").write_text("# Service A\n", encoding="utf-8")

            result = agent_instructions.scan(
                repo,
                include_content=False,
                max_chars=12000,
                paths=None,
                scope="affected",
                services=["missing-service"],
            )

        self.assertEqual(["missing-service"], result["unresolved_requested_services"])
        self.assertIn("missing-service", result["missing"]["requested_services"])


class CoverageGateTests(unittest.TestCase):
    def test_coverage_gate_requires_complete_mapping(self) -> None:
        markdown = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote returned | Create quote | services/a | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            matrix = repo / "coverage.md"
            unit = repo / "unit.txt"
            review = repo / "business.md"
            matrix.write_text(markdown, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/a -am test")
            review.write_text("Business logic reviewed against AC-1.\n", encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review)

        self.assertTrue(result["ready"])
        self.assertEqual(1, result["coverage_rows"])
        self.assertEqual(0, result["unit_test_commands"][0]["exit_code"])

    def test_coverage_gate_blocks_text_only_unit_evidence(self) -> None:
        markdown = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote returned | Create quote | services/a | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            matrix = repo / "coverage.md"
            unit = repo / "unit.txt"
            review = repo / "business.md"
            matrix.write_text(markdown, encoding="utf-8")
            unit.write_text("mvn -pl services/a -am test: PASS\n", encoding="utf-8")
            review.write_text("Business logic reviewed against AC-1.\n", encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review)

        self.assertFalse(result["ready"])
        self.assertTrue(any("structured JSON" in reason for reason in result["blocked_reasons"]))

    def test_coverage_gate_blocks_missing_code_refs(self) -> None:
        markdown = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote returned | Create quote | services/a | QuoteTest |  | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            matrix = repo / "coverage.md"
            unit = repo / "unit.txt"
            review = repo / "business.md"
            matrix.write_text(markdown, encoding="utf-8")
            write_command_evidence(unit)
            review.write_text("Reviewed.\n", encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review)

        self.assertFalse(result["ready"])
        self.assertTrue(any("code_refs" in reason for reason in result["blocked_reasons"]))

    def test_coverage_gate_blocks_generic_completion_evidence(self) -> None:
        markdown = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote returned | Create quote | services/a | done | implemented | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            matrix = repo / "coverage.md"
            unit = repo / "unit.txt"
            review = repo / "business.md"
            matrix.write_text(markdown, encoding="utf-8")
            write_command_evidence(unit)
            review.write_text("Reviewed.\n", encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review)

        self.assertFalse(result["ready"])
        self.assertTrue(any("concrete test reference" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertTrue(any("concrete code reference" in reason.lower() for reason in result["blocked_reasons"]))

    def test_coverage_gate_accepts_utf8_bom_evidence(self) -> None:
        markdown = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote returned | Create quote | services/a | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            matrix = repo / "coverage.md"
            unit = repo / "unit.txt"
            review = repo / "business.md"
            matrix.write_text(markdown, encoding="utf-8-sig")
            write_command_evidence(unit, "mvn -pl services/a -am test")
            unit.write_text(unit.read_text(encoding="utf-8"), encoding="utf-8-sig")
            review.write_text("Business logic reviewed against AC-1.\n", encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review)

        self.assertTrue(result["ready"])
        self.assertEqual(1, result["coverage_rows"])
        self.assertEqual(0, result["unit_test_commands"][0]["exit_code"])

    def test_coverage_gate_accepts_implemented_status(self) -> None:
        markdown = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Create quote | services/quote-service | QuoteServiceTest | QuoteService | reviewed | implemented |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            matrix = repo / "coverage.md"
            unit = repo / "unit.txt"
            review = repo / "business.md"
            matrix.write_text(markdown, encoding="utf-8")
            write_command_evidence(unit)
            review.write_text("Business logic reviewed against AC-1.\n", encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review)

        self.assertTrue(result["ready"])


class AcProgressGateTests(unittest.TestCase):
    def test_ac_progress_blocks_r3_when_assigned_ac_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            matrix = repo / "docs" / "agent-runs" / "run" / "coverage.md"
            manifest = repo / "docs" / "agent-runs" / "run" / "manifest.md"
            unit = repo / "docs" / "agent-runs" / "run" / "unit.json"
            matrix.parent.mkdir(parents=True)
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Acceptance Criteria
                    - AC-1 Quote is returned.
                    - AC-2 Quote failure is rejected.
                    """
                ).strip(),
                encoding="utf-8",
            )
            matrix.write_text(
                textwrap.dedent(
                    """
                    | id | acceptance | use_case | service | tests | code_refs | business_review | status |
                    | --- | --- | --- | --- | --- | --- | --- | --- |
                    | AC-1 | Quote is returned | success | services/a | QuoteServiceTest | QuoteService | reviewed | verified |
                    """
                ).strip(),
                encoding="utf-8",
            )
            manifest.write_text(
                textwrap.dedent(
                    """
                    | id | module | artifact | artifact_type | source | required | tests | status | evidence |
                    | --- | --- | --- | --- | --- | --- | --- | --- | --- |
                    | IM-1 | services/a | services/a/QuoteService.java | service | AC-1 | yes | QuoteServiceTest | verified | done |
                    """
                ).strip(),
                encoding="utf-8",
            )
            write_command_evidence(unit)

            result = ac_progress_gate.validate(repo, design, None, matrix, manifest, unit)

        self.assertFalse(result["ready"])
        self.assertEqual(["AC-2"], result["missing_coverage"])
        self.assertEqual(["AC-2"], result["missing_manifest"])
        self.assertTrue(any("code-developer TDD" in warning for warning in result["warnings"]))

    def test_ac_progress_allows_r3_when_all_service_slice_acs_are_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            service_design = repo / "docs" / "agent-runs" / "run" / "service-designs" / "quote-service.md"
            matrix = repo / "docs" / "agent-runs" / "run" / "service-plans" / "quote-service" / "coverage.md"
            manifest = repo / "docs" / "agent-runs" / "run" / "service-plans" / "quote-service" / "manifest.md"
            unit = repo / "docs" / "agent-runs" / "run" / "service-plans" / "quote-service" / "unit.json"
            service_design.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            service_design.write_text(
                textwrap.dedent(
                    """
                    # Service Design Slice

                    ## Mapped Acceptance Criteria
                    | AC | global requirement | service responsibility | local tests |
                    | --- | --- | --- | --- |
                    | AC-1 | Quote is returned | success path | QuoteServiceTest |
                    | AC-2 | Quote failure is rejected | failure path | QuoteFailureTest |
                    """
                ).strip(),
                encoding="utf-8",
            )
            matrix.write_text(
                textwrap.dedent(
                    """
                    | id | acceptance | use_case | service | tests | code_refs | business_review | status |
                    | --- | --- | --- | --- | --- | --- | --- | --- |
                    | AC-1 | Quote is returned | success | services/a | QuoteServiceTest | QuoteService | reviewed | verified |
                    | AC-2 | Quote failure is rejected | failure | services/a | QuoteFailureTest | QuoteService | reviewed | verified |
                    """
                ).strip(),
                encoding="utf-8",
            )
            manifest.write_text(
                textwrap.dedent(
                    """
                    | id | module | artifact | artifact_type | source | required | tests | status | evidence |
                    | --- | --- | --- | --- | --- | --- | --- | --- | --- |
                    | IM-1 | services/a | services/a/QuoteService.java | service | AC-1 | yes | QuoteServiceTest | verified | done |
                    | IM-2 | services/a | services/a/QuoteService.java | service | AC-2 | yes | QuoteFailureTest | verified | done |
                    """
                ).strip(),
                encoding="utf-8",
            )
            write_command_evidence(unit, "mvn -pl services/a -am test")

            result = ac_progress_gate.validate(repo, None, service_design, matrix, manifest, unit)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["AC-1", "AC-2"], result["completed_acceptance_ids"])


class TestImpactPlanTests(unittest.TestCase):
    def test_build_plan_uses_affected_maven_service_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            module = repo / "services" / "refund-service"
            module.mkdir(parents=True)
            (module / "pom.xml").write_text("<project />\n", encoding="utf-8")
            changed = ["services/refund-service/src/main/java/com/example/RefundService.java"]

            result = test_impact_plan.build_plan(repo, changed)

        self.assertEqual("e2e-dev-harness.test-impact-plan.v1", result["schema"])
        self.assertEqual("ready", result["status"])
        self.assertEqual(["mvn -pl services/refund-service -am test"], [item["command"] for item in result["commands"]])

    def test_validate_blocks_missing_required_command_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            plan = repo / "docs" / "agent-runs" / "run" / "evidence" / "test-impact-plan.json"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.json"
            plan.parent.mkdir(parents=True)
            plan.write_text(
                json.dumps(
                    {
                        "schema": test_impact_plan.SCHEMA,
                        "status": "ready",
                        "commands": [
                            {
                                "id": "TST-001",
                                "command": "mvn -pl services/refund-service -am test",
                                "required": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            write_command_evidence(unit, "mvn test")

            result = test_impact_plan.validate(repo, plan, unit)

        self.assertFalse(result["ready"])
        self.assertTrue(any("was not found" in reason for reason in result["blocked_reasons"]))

    def test_validate_accepts_matching_required_command_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            plan = repo / "docs" / "agent-runs" / "run" / "evidence" / "test-impact-plan.json"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.json"
            plan.parent.mkdir(parents=True)
            plan.write_text(
                json.dumps(
                    {
                        "schema": test_impact_plan.SCHEMA,
                        "status": "ready",
                        "commands": [
                            {
                                "id": "TST-001",
                                "command": "mvn -pl services/refund-service -am test",
                                "required": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            write_command_evidence(unit, "mvn -pl services/refund-service -am test")

            result = test_impact_plan.validate(repo, plan, unit)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["mvn -pl services/refund-service -am test"], result["matched_commands"])

    def test_validate_blocks_starter_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            plan = repo / "test-impact-plan.json"
            plan.write_text(
                json.dumps({"schema": test_impact_plan.SCHEMA, "status": "template", "commands": []}),
                encoding="utf-8",
            )

            result = test_impact_plan.validate(repo, plan, None)

        self.assertFalse(result["ready"])
        self.assertTrue(any("starter template" in reason for reason in result["blocked_reasons"]))


class ImplementationManifestTests(unittest.TestCase):
    def test_manifest_blocks_missing_required_artifact(self) -> None:
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | jeepay-service | jeepay-service/src/main/java/com/example/VnpayPaymentConfigService.java | config-service | explicit-requirement | yes | VnpayPaymentConfigServiceTest | verified | required by task |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(manifest, encoding="utf-8")

            result = implementation_manifest.validate(repo, manifest_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("does not exist" in reason for reason in result["blocked_reasons"]))

    def test_manifest_requires_all_design_modules(self) -> None:
        design = textwrap.dedent(
            """
            # VNPay

            ## Affected services/modules
            - jeepay-core: constants and params
            - jeepay-service: channel config service
            - jeepay-payment: payment, notice, refund services
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
            design_path = repo / "docs" / "design" / "vnpay.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            design_path.parent.mkdir(parents=True)
            manifest_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")

            result = implementation_manifest.validate(repo, manifest_path, design_path)

        self.assertFalse(result["ready"])
        self.assertIn("jeepay-service", " ".join(result["blocked_reasons"]))

    def test_manifest_blocks_required_artifact_section_class_not_listed(self) -> None:
        design = textwrap.dedent(
            """
            # VNPay

            ## Required Artifacts
            - AC-1 VnpayQrOrderRS is returned for QR orders.
            """
        ).strip()
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | jeepay-payment | jeepay-payment/src/main/java/com/example/VnpayPaymentService.java | payment-service | explicit-requirement | yes | VnpayPaymentServiceTest | verified | done |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = repo / "jeepay-payment/src/main/java/com/example/VnpayPaymentService.java"
            target.parent.mkdir(parents=True)
            target.write_text("class Placeholder {}\n", encoding="utf-8")
            design_path = repo / "docs" / "design" / "vnpay.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            design_path.parent.mkdir(parents=True)
            manifest_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")

            result = implementation_manifest.validate(repo, manifest_path, design_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("VnpayQrOrderRS" in reason for reason in result["blocked_reasons"]))

    def test_manifest_ignores_reference_class_outside_required_artifact_sections(self) -> None:
        design = textwrap.dedent(
            """
            # Checkout

            ## Acceptance Criteria
            - AC-1 Checkout result is returned.

            ## Notes
            - Legacy OrderService is a reference only and must not be reimplemented.
            """
        ).strip()
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | checkout-service | checkout-service/src/main/java/com/example/CheckoutService.java | service | explicit-requirement | yes | CheckoutServiceTest | verified | done |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = repo / "checkout-service/src/main/java/com/example/CheckoutService.java"
            target.parent.mkdir(parents=True)
            target.write_text("class Placeholder {}\n", encoding="utf-8")
            design_path = repo / "docs" / "design" / "checkout.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            design_path.parent.mkdir(parents=True)
            manifest_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")

            result = implementation_manifest.validate(repo, manifest_path, design_path)

        self.assertTrue(result["ready"])
        self.assertNotIn("OrderService", result["design_artifacts"])

    def test_manifest_allows_verified_existing_artifacts(self) -> None:
        design = textwrap.dedent(
            """
            # VNPay

            ## Affected services/modules
            - jeepay-core: constants and params
            - jeepay-payment: payment service

            ## Acceptance Criteria
            - AC-1 VnpayPaymentService returns the VNPay URL.
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
            design_path = repo / "docs" / "design" / "vnpay.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            design_path.parent.mkdir(parents=True)
            manifest_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")

            result = implementation_manifest.validate(repo, manifest_path, design_path)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(2, result["required_rows"])


class TaskAlignmentGuardTests(unittest.TestCase):
    def write_alignment_artifacts(self, repo: Path) -> tuple[Path, Path, Path]:
        design = textwrap.dedent(
            """
            # Checkout

            ## Goal
            - Return checkout quotes.

            ## Scope
            - services/checkout-service

            ## Acceptance Criteria
            - AC-1 Checkout quote is returned.
            - AC-2 Invalid amount is rejected.
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote returned | Create checkout success and failure | services/checkout-service | CheckoutServiceTest success/failure | CheckoutService#create | reviewed | verified |
            | AC-2 | Invalid amount rejected | Reject checkout invalid amount success and failure | services/checkout-service | CheckoutServiceTest invalid amount failure | CheckoutValidator#reject | reviewed | verified |
            """
        ).strip()
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | services/checkout-service | services/checkout-service/src/main/java/com/example/CheckoutService.java | service | AC-1 | yes | CheckoutServiceTest | verified | code path |
            | AC-2 | services/checkout-service | services/checkout-service/src/main/java/com/example/CheckoutValidator.java | validator | AC-2 | yes | CheckoutServiceTest | verified | code path |
            """
        ).strip()
        design_path = repo / "docs" / "design" / "checkout.md"
        coverage_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage-matrix.md"
        manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
        for path, text in ((design_path, design), (coverage_path, coverage), (manifest_path, manifest)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return design_path, coverage_path, manifest_path

    def test_git_diff_timeout_is_reported_as_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            task_alignment_guard.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["git", "diff"], 600),
        ):
            files, warnings = task_alignment_guard.changed_files_from_git(Path(tmp), "main")

        self.assertEqual([], files)
        self.assertTrue(any("timed out" in warning for warning in warnings))

    def test_task_alignment_blocks_changed_files_outside_declared_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design_path, coverage_path, manifest_path = self.write_alignment_artifacts(repo)
            changed = repo / "docs" / "agent-runs" / "run" / "evidence" / "changed-files.txt"
            changed.write_text(
                "\n".join(
                    [
                        "services/checkout-service/src/main/java/com/example/CheckoutService.java",
                        "services/ledger-service/src/main/java/com/example/LedgerService.java",
                    ]
                ),
                encoding="utf-8",
            )

            result = task_alignment_guard.validate(repo, design_path, manifest_path, coverage_path, changed)

        self.assertFalse(result["ready"])
        self.assertIn("services/ledger-service/src/main/java/com/example/LedgerService.java", result["scope_drift_files"])
        self.assertEqual("plan", result["correction_actions"][0]["return_phase"])

    def test_task_alignment_blocks_missing_ac_and_points_to_tdd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design_path, coverage_path, manifest_path = self.write_alignment_artifacts(repo)
            coverage_path.write_text(
                textwrap.dedent(
                    """
                    | id | acceptance | use_case | service | tests | code_refs | business_review | status |
                    | --- | --- | --- | --- | --- | --- | --- | --- |
                    | AC-1 | Quote returned | Create checkout success and failure | services/checkout-service | CheckoutServiceTest success/failure | CheckoutService#create | reviewed | verified |
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = task_alignment_guard.validate(repo, design_path, manifest_path, coverage_path)

        self.assertFalse(result["ready"])
        self.assertIn("AC-2", result["missing_coverage_acceptance_ids"])
        self.assertTrue(any(action["return_phase"] == "tdd-red" for action in result["correction_actions"]))

    def test_task_alignment_allows_declared_scope_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design_path, coverage_path, manifest_path = self.write_alignment_artifacts(repo)
            changed = repo / "docs" / "agent-runs" / "run" / "evidence" / "changed-files.txt"
            changed.write_text(
                "\n".join(
                    [
                        "services/checkout-service/src/main/java/com/example/CheckoutService.java",
                        "services/checkout-service/src/test/java/com/example/CheckoutServiceTest.java",
                    ]
                ),
                encoding="utf-8",
            )

            result = task_alignment_guard.validate(repo, design_path, manifest_path, coverage_path, changed)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual([], result["correction_actions"])

    def test_task_alignment_blocks_undeclared_acceptance_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design_path, coverage_path, manifest_path = self.write_alignment_artifacts(repo)
            manifest_path.write_text(
                textwrap.dedent(
                    """
                    | id | module | artifact | artifact_type | source | required | tests | status | evidence |
                    | --- | --- | --- | --- | --- | --- | --- | --- | --- |
                    | AC-3 | services/checkout-service | services/checkout-service/src/main/java/com/example/CheckoutBonusService.java | service | AC-3 | yes | CheckoutBonusTest | verified | code path |
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = task_alignment_guard.validate(repo, design_path, manifest_path, coverage_path)

        self.assertFalse(result["ready"])
        self.assertIn("AC-3", result["deviation"]["undeclared_acceptance_ids"])
        self.assertTrue(any(action["return_phase"] == "clarify" for action in result["correction_actions"]))

    def test_task_alignment_blocks_interface_file_without_impact_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design_path, coverage_path, manifest_path = self.write_alignment_artifacts(repo)
            changed = repo / "docs" / "agent-runs" / "run" / "evidence" / "changed-files.txt"
            changed.parent.mkdir(parents=True, exist_ok=True)
            changed.write_text(
                "services/checkout-service/src/main/java/com/example/CheckoutController.java\n",
                encoding="utf-8",
            )

            result = task_alignment_guard.validate(repo, design_path, manifest_path, coverage_path, changed)

        self.assertFalse(result["ready"])
        self.assertIn(
            "services/checkout-service/src/main/java/com/example/CheckoutController.java",
            result["deviation"]["undeclared_interface_files"],
        )


class CrossServiceDependencyScanTests(unittest.TestCase):
    def test_run_command_reports_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            cross_service_dependency_scan.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["gitnexus", "impact", "QuoteService"], 600, output="partial"),
        ):
            result = cross_service_dependency_scan.run_command(["gitnexus", "impact", "QuoteService"], Path(tmp))

        self.assertEqual(124, result["exit_code"])
        self.assertIn("timed out", result["stderr_tail"])

    def test_http_configured_url_matches_controller_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            caller = repo / "services" / "quote-service"
            provider = repo / "services" / "inventory-service"
            (caller / "src" / "main" / "resources").mkdir(parents=True)
            (caller / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
            (provider / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
            (caller / "pom.xml").write_text("<project />", encoding="utf-8")
            (provider / "pom.xml").write_text("<project />", encoding="utf-8")
            (caller / "src" / "main" / "resources" / "application.properties").write_text(
                "inventory.base-url=http://inventory-service/api\n",
                encoding="utf-8",
            )
            (caller / "src" / "main" / "java" / "com" / "example" / "InventoryClient.java").write_text(
                textwrap.dedent(
                    """
                    package com.example;

                    import org.springframework.beans.factory.annotation.Value;
                    import org.springframework.web.client.RestTemplate;

                    class InventoryClient {
                        @Value("${inventory.base-url}")
                        private String inventoryBaseUrl;

                        void createQuote() {
                            new RestTemplate().postForObject(inventoryBaseUrl + "/quotes", "{}", String.class);
                        }
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )
            (provider / "src" / "main" / "java" / "com" / "example" / "InventoryController.java").write_text(
                textwrap.dedent(
                    """
                    package com.example;

                    import org.springframework.web.bind.annotation.PostMapping;
                    import org.springframework.web.bind.annotation.RequestMapping;
                    import org.springframework.web.bind.annotation.RestController;

                    @RestController
                    @RequestMapping("/api")
                    class InventoryController {
                        @PostMapping("/quotes")
                        String createQuote() {
                            return "ok";
                        }
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = cross_service_dependency_scan.scan(repo, gitnexus_mode="off", write_reports=False)

        self.assertTrue(result["ready"])
        dependency = result["dependencies"][0]
        self.assertEqual("http", dependency["kind"])
        self.assertEqual("services/quote-service", dependency["source_service"])
        self.assertEqual("services/inventory-service", dependency["target_service"])
        self.assertEqual("/api/quotes", dependency["target_route"])
        self.assertIn("java_parser", result)
        self.assertIn(result["java_parser"]["backend"], {"regex-fallback", "tree-sitter"})
        self.assertEqual(
            result["java_parser"]["backend"] == "tree-sitter",
            result["java_parser"]["ast_parser_active"],
        )

    def test_scan_can_require_active_tree_sitter_ast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            cross_service_dependency_scan,
            "java_parser_backend",
            return_value={
                "backend": "regex-fallback",
                "tree_sitter_available": False,
                "ast_parser_active": False,
                "warning": "tree-sitter unavailable",
            },
        ):
            repo = Path(tmp)
            result = cross_service_dependency_scan.scan(
                repo,
                write_reports=False,
                gitnexus_mode="off",
                require_tree_sitter_ast=True,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("tree-sitter AST" in reason for reason in result["blocked_reasons"]))

    def test_scan_writes_reports_without_globals_indirection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            service = repo / "services" / "quote-service"
            service.mkdir(parents=True)
            (service / "pom.xml").write_text("<project />", encoding="utf-8")
            output_dir = repo / "knowledge-graph"

            result = cross_service_dependency_scan.scan(
                repo,
                gitnexus_mode="off",
                write_reports=True,
                output_dir=output_dir,
            )

            self.assertTrue(Path(result["report_paths"]["json"]).exists())
            self.assertTrue(Path(result["report_paths"]["markdown"]).exists())

    def test_http_unresolved_placeholder_becomes_open_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            caller = repo / "services" / "quote-service"
            (caller / "src" / "main" / "resources").mkdir(parents=True)
            (caller / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
            (caller / "pom.xml").write_text("<project />", encoding="utf-8")
            (caller / "src" / "main" / "resources" / "application.yml").write_text(
                "inventory:\n  base-url: ${INVENTORY_BASE_URL}\n",
                encoding="utf-8",
            )
            (caller / "src" / "main" / "java" / "com" / "example" / "InventoryClient.java").write_text(
                'class InventoryClient { void call() { webClient.get().uri(inventoryBaseUrl + "/quotes"); } }',
                encoding="utf-8",
            )

            result = cross_service_dependency_scan.scan(repo, gitnexus_mode="off", write_reports=False)

        self.assertFalse(result["ready"])
        self.assertTrue(any("INVENTORY_BASE_URL" in question for question in result["unresolved_questions"]))

    def test_dmq_topic_matches_producer_and_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            producer = repo / "services" / "quote-service"
            consumer = repo / "services" / "billing-service"
            for service in (producer, consumer):
                (service / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
                (service / "pom.xml").write_text("<project />", encoding="utf-8")
            topic_source = textwrap.dedent(
                """
                package com.example;
                final class Topics {
                    static final String QUOTE_CREATED = "quote.created";
                }
                """
            ).strip()
            (producer / "src" / "main" / "java" / "com" / "example" / "Topics.java").write_text(topic_source, encoding="utf-8")
            (producer / "src" / "main" / "java" / "com" / "example" / "QuotePublisher.java").write_text(
                "class QuotePublisher { void publish() { dmqTemplate.publish(Topics.QUOTE_CREATED, \"created\", payload); } }",
                encoding="utf-8",
            )
            (consumer / "src" / "main" / "java" / "com" / "example" / "QuoteListener.java").write_text(
                textwrap.dedent(
                    """
                    class QuoteListener {
                        @DmqListener(topic = "quote.created", tag = "created", group = "billing")
                        void onQuote(Object payload) {}
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = cross_service_dependency_scan.scan(repo, gitnexus_mode="off", write_reports=False)

        self.assertTrue(result["ready"])
        dependency = next(edge for edge in result["dependencies"] if edge["kind"] == "dmq")
        self.assertEqual("services/quote-service", dependency["source_service"])
        self.assertEqual("services/billing-service", dependency["target_service"])
        self.assertEqual("quote.created", dependency["topic"])
        self.assertEqual("created", dependency["tag"])

    def test_dmq_topic_tag_mismatch_requires_clarification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            producer = repo / "services" / "quote-service"
            consumer = repo / "services" / "billing-service"
            for service in (producer, consumer):
                (service / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
                (service / "pom.xml").write_text("<project />", encoding="utf-8")
            (producer / "src" / "main" / "java" / "com" / "example" / "QuotePublisher.java").write_text(
                'class QuotePublisher { void publish() { dmqTemplate.publish("quote.created", "created", payload); } }',
                encoding="utf-8",
            )
            (consumer / "src" / "main" / "java" / "com" / "example" / "QuoteListener.java").write_text(
                'class QuoteListener { @DmqListener(topic = "quote.created", tag = "paid", group = "billing") void onQuote(Object payload) {} }',
                encoding="utf-8",
            )

            result = cross_service_dependency_scan.scan(repo, gitnexus_mode="off", write_reports=False)

        self.assertFalse(result["ready"])
        dependency = next(edge for edge in result["dependencies"] if edge["kind"] == "dmq")
        self.assertEqual("ambiguous", dependency["confidence"])
        self.assertTrue(any("tag" in question.lower() for question in result["unresolved_questions"]))

    def test_gitnexus_evidence_runs_context_and_impact_for_symbol_seeds_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            producer = repo / "services" / "quote-service"
            consumer = repo / "services" / "billing-service"
            for service in (producer, consumer):
                (service / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
                (service / "pom.xml").write_text("<project />", encoding="utf-8")
            (producer / "src" / "main" / "java" / "com" / "example" / "QuotePublisher.java").write_text(
                'class QuotePublisher { void publish() { dmqTemplate.publish("quote.created", payload); } }',
                encoding="utf-8",
            )
            (consumer / "src" / "main" / "java" / "com" / "example" / "QuoteListener.java").write_text(
                'class QuoteListener { @DmqListener(topic = "quote.created", group = "billing") void onQuote(Object payload) {} }',
                encoding="utf-8",
            )
            calls: list[list[str]] = []

            def fake_runner(command: list[str], cwd: Path) -> dict:
                calls.append(command)
                return {"command": " ".join(command), "exit_code": 0, "stdout_tail": "ok", "stderr_tail": ""}

            result = cross_service_dependency_scan.scan(
                repo,
                gitnexus_mode="strict",
                write_reports=False,
                command_runner=fake_runner,
                gitnexus_available=True,
            )

        repo_arg = str(repo.resolve())
        context_calls = [command for command in calls if command[:2] == ["gitnexus", "context"]]
        impact_calls = [command for command in calls if command[:2] == ["gitnexus", "impact"]]
        self.assertTrue(context_calls)
        self.assertTrue(impact_calls)
        for command in context_calls + impact_calls:
            self.assertIn("--repo", command)
            self.assertEqual(repo_arg, command[command.index("--repo") + 1])
            self.assertNotIn("services/quote-service", command)
            self.assertNotIn("services/billing-service", command)
        self.assertTrue(all("/" not in command[2] for command in context_calls))
        self.assertEqual(["QuotePublisher.publish", "QuoteListener.onQuote"], result["gitnexus"]["symbol_seeds"])
        self.assertTrue(result["gitnexus"]["evidence"])

    def test_gitnexus_evidence_can_scope_symbol_seeds_to_affected_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            dependencies = [
                {
                    "source_service": "services/order-service",
                    "target_service": "services/payment-service",
                    "source_symbol": "OrderClient.reserve",
                    "target_symbol": "PaymentController.post",
                },
                {
                    "source_service": "services/catalog-service",
                    "target_service": "services/search-service",
                    "source_symbol": "CatalogClient.sync",
                    "target_symbol": "SearchController.post",
                },
            ]
            calls: list[list[str]] = []

            def fake_runner(command: list[str], cwd: Path) -> dict:
                calls.append(command)
                return {"command": " ".join(command), "exit_code": 0, "stdout_tail": "ok", "stderr_tail": ""}

            result, warnings = cross_service_dependency_scan.gitnexus_evidence(
                repo,
                dependencies,
                "strict",
                command_runner=fake_runner,
                gitnexus_available=True,
                affected_services=["services/payment-service"],
            )

        self.assertEqual([], warnings)
        self.assertEqual(["OrderClient.reserve", "PaymentController.post"], result["symbol_seeds"])
        self.assertFalse(any("CatalogClient.sync" in command for command in [" ".join(call) for call in calls]))

    def test_gitnexus_unavailable_marks_evidence_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            service = repo / "services" / "quote-service"
            (service / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
            (service / "pom.xml").write_text("<project />", encoding="utf-8")
            (service / "src" / "main" / "java" / "com" / "example" / "QuotePublisher.java").write_text(
                'class QuotePublisher { void publish() { dmqTemplate.publish("quote.created", payload); } }',
                encoding="utf-8",
            )

            result = cross_service_dependency_scan.scan(
                repo,
                gitnexus_mode="strict",
                write_reports=False,
                gitnexus_available=False,
            )

        self.assertFalse(result["gitnexus"]["available"])
        self.assertFalse(result["gitnexus"]["verified"])
        self.assertTrue(any("GitNexus" in warning for warning in result["warnings"]))

    def test_dependency_report_blocks_low_confidence_edges_without_questions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            report = repo / "knowledge-graph" / "cross-service-dependencies.json"
            report.parent.mkdir(parents=True)
            report.write_text(
                json.dumps(
                    {
                        "ready": True,
                        "dependencies": [
                            {
                                "kind": "dmq",
                                "source_service": "services/a",
                                "target_service": "services/b",
                                "topic": "quote.created",
                                "confidence": "ambiguous",
                            }
                        ],
                        "unresolved_questions": [],
                    }
                ),
                encoding="utf-8",
            )

            result = cross_service_dependency_scan.validate_dependency_report(repo, report)

        self.assertFalse(result["ready"])
        self.assertTrue(any("low-confidence" in reason.lower() for reason in result["blocked_reasons"]))


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


class WorkflowGuardTests(unittest.TestCase):
    def test_guard_blocks_missing_prepare_status(self) -> None:
        result = workflow_guard.validate_verify_result(
            {"maven": {"skipped": False, "exit_code": 0}},
            strict=True,
            require_completion=True,
        )

        self.assertFalse(result["ready"])
        self.assertTrue(any("prepare" in reason.lower() for reason in result["blocked_reasons"]))

    def test_guard_blocks_dependency_scan_disabled_in_strict_mode(self) -> None:
        verify_result = verified_workflow_result()
        verify_result["prepare"]["cross_service_dependencies"] = {"enabled": False, "mode": "off"}
        verify_result["workflow"]["dependency_scan_mode"] = "off"

        result = workflow_guard.validate_verify_result(verify_result, strict=True, require_completion=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("dependency scan" in reason.lower() for reason in result["blocked_reasons"]))

    def test_guard_blocks_skipped_maven_in_strict_mode(self) -> None:
        verify_result = verified_workflow_result()
        verify_result["workflow"]["skip_maven"] = True
        verify_result["maven"] = {"skipped": True}

        result = workflow_guard.validate_verify_result(verify_result, strict=True, require_completion=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("maven" in reason.lower() for reason in result["blocked_reasons"]))

    def test_guard_blocks_missing_completion_gate_in_completion_mode(self) -> None:
        verify_result = verified_workflow_result()
        verify_result["implementation_gate"] = None

        result = workflow_guard.validate_verify_result(verify_result, strict=True, require_completion=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("completion gate" in reason.lower() for reason in result["blocked_reasons"]))

    def test_guard_blocks_plan_without_harness_state_in_strict_completion(self) -> None:
        verify_result = verified_workflow_result()
        verify_result["workflow"]["harness"] = False
        verify_result["workflow"]["state"] = ""

        result = workflow_guard.validate_verify_result(verify_result, strict=True, require_completion=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("plan phase skipped" in reason.lower() for reason in result["blocked_reasons"]))

    def test_guard_phase_coverage_reports_skipped_reviews_and_gates(self) -> None:
        verify_result = verified_workflow_result()
        verify_result["implementation_gate"]["semantic_reviews"]["covered_phases"] = ["design"]
        verify_result["implementation_gate"]["phase"] = "implementation"
        verify_result["implementation_gate"]["ready"] = False

        result = workflow_guard.validate_verify_result(verify_result, strict=True, require_completion=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("r2 review phase skipped" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertTrue(any("r3 review phase skipped" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertTrue(any("completion gate" in reason.lower() for reason in result["blocked_reasons"]))

    def test_phase_coverage_can_require_strict_guard_for_final_summary(self) -> None:
        verify_result = verified_workflow_result()

        result = workflow_guard.validate_phase_coverage(
            verify_result,
            completion_required=True,
            require_strict_guard=True,
        )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Strict Guard" in reason for reason in result["blocked_reasons"]))

    def test_guard_blocks_missing_independent_semantic_reviews_in_strict_completion(self) -> None:
        verify_result = verified_workflow_result()
        verify_result["workflow"]["require_semantic_reviews"] = False
        verify_result["implementation_gate"]["semantic_reviews"] = None

        result = workflow_guard.validate_verify_result(verify_result, strict=True, require_completion=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("semantic review" in reason.lower() for reason in result["blocked_reasons"]))

    def test_guard_blocks_missing_requirements_archive_in_strict_completion(self) -> None:
        verify_result = verified_workflow_result()
        verify_result["workflow"]["require_requirements_archive"] = False
        verify_result["implementation_gate"]["requirements_archive"] = None

        result = workflow_guard.validate_verify_result(verify_result, strict=True, require_completion=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("requirements archive" in reason.lower() for reason in result["blocked_reasons"]))

    def test_guard_allows_complete_verified_workflow_result(self) -> None:
        result = workflow_guard.validate_verify_result(
            verified_workflow_result(),
            strict=True,
            require_completion=True,
        )

        self.assertTrue(result["ready"])
        self.assertEqual([], result["blocked_reasons"])

    def test_guard_validates_verify_status_file_for_hook_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            status = repo / "docs" / "agent-runs" / "run" / "verify.json"
            status.parent.mkdir(parents=True)
            status.write_text(json.dumps(verified_workflow_result()), encoding="utf-8")

            result = workflow_guard.validate_status_file(
                repo,
                status,
                strict=True,
                require_completion=True,
            )

        self.assertTrue(result["ready"])
        self.assertEqual(str(status), result["verify_status"])

    def test_guard_blocks_missing_verify_status_file_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            status = repo / "missing-verify.json"

            result = workflow_guard.validate_status_file(
                repo,
                status,
                strict=True,
                require_completion=True,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("not found" in reason.lower() for reason in result["blocked_reasons"]))


class HandoffGateTests(unittest.TestCase):
    def write_ready_marker(
        self,
        handoff: Path,
        producer_agent: str = "developer-agent-1",
        status: str = "ready",
        sha256: str | None = None,
    ) -> None:
        marker = handoff.with_suffix(".ready.json")
        marker.write_text(
            json.dumps(
                {
                    "path": str(handoff.name),
                    "sha256": sha256 or hashlib.sha256(handoff.read_bytes()).hexdigest(),
                    "producer_agent": producer_agent,
                    "status": status,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def test_handoff_gate_blocks_draft_template_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            (handoff_dir / "04-code-developer.md").write_text(
                e2e_dev_harness.handoff_text("code-developer"),
                encoding="utf-8",
            )

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("draft" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertTrue(any("agent id" in reason.lower() for reason in result["blocked_reasons"]))

    def test_handoff_gate_blocks_partial_file_before_downstream_consumption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            (handoff_dir / "04-code-developer.md.partial").write_text("half written", encoding="utf-8")

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("partial" in reason.lower() for reason in result["blocked_reasons"]))

    def test_handoff_gate_can_require_non_empty_handoff_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)

            result = handoff_gate.validate(repo, [handoff_dir], require_files=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("handoff artifacts are missing" in reason.lower() for reason in result["blocked_reasons"]))

    def test_handoff_gate_allows_ready_handoff_with_hashes_and_no_open_questions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("Implementation manifest evidence.\n", encoding="utf-8")
            evidence_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
            handoff = handoff_dir / "04-code-developer.md"
            handoff.write_text(
                textwrap.dedent(
                    f"""
                    ---
                    agent: code-developer
                    agent_id: developer-agent-1
                    status: ready
                    inputs:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md
                    outputs:
                      - docs/agent-runs/run/evidence/implementation-manifest.md
                    input_hashes:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/implementation-manifest.md sha256:{evidence_hash}
                    blocked_by: []
                    consumed_by:
                      - coverage-reviewer
                    open_questions: None
                    service_scope: services/order-service
                    memory_updates_proposed: []
                    ---

                    # Agent Handoff

                    ## Summary

                    Implemented order-service refund flow.

                    ## Facts Used

                    Consumed the test handoff and service plan.

                    ## Decisions Made

                    Reused the existing service-layer pattern.

                    ## Open Questions

                    None

                    ## Downstream Assumptions

                    Coverage reviewer may rely on the implementation manifest.

                    ## Verification Evidence

                    mvn -pl services/order-service -am test passed.
                    """
                ).strip(),
                encoding="utf-8",
            )
            self.write_ready_marker(handoff)

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(1, len(result["items"]))

    def test_handoff_gate_blocks_ready_handoff_with_empty_body_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            handoff = handoff_dir / "04-code-developer.md"
            handoff.write_text(
                textwrap.dedent(
                    """
                    ---
                    agent: code-developer
                    agent_id: developer-agent-1
                    status: ready
                    inputs:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md
                    outputs:
                      - docs/agent-runs/run/evidence/implementation-manifest.md
                    input_hashes:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/implementation-manifest.md sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                    consumed_by:
                      - coverage-reviewer
                    open_questions: None
                    ---

                    # Agent Handoff

                    ## Summary

                    ## Facts Used

                    ## Decisions Made

                    ## Open Questions

                    None

                    ## Downstream Assumptions

                    ## Verification Evidence
                    """
                ).strip(),
                encoding="utf-8",
            )
            self.write_ready_marker(handoff)

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("Summary" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("Verification Evidence" in reason for reason in result["blocked_reasons"]))

    def test_handoff_gate_blocks_missing_ready_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            handoff = handoff_dir / "04-code-developer.md"
            handoff.write_text(
                textwrap.dedent(
                    """
                    ---
                    agent: code-developer
                    agent_id: developer-agent-1
                    status: ready
                    inputs:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md
                    outputs:
                      - docs/agent-runs/run/evidence/implementation-manifest.md
                    input_hashes:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/implementation-manifest.md sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                    consumed_by:
                      - coverage-reviewer
                    open_questions: None
                    ---

                    # Agent Handoff

                    ## Open Questions

                    None
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("ready marker" in reason.lower() for reason in result["blocked_reasons"]))

    def test_handoff_gate_blocks_stale_ready_marker_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            handoff = handoff_dir / "04-code-developer.md"
            handoff.write_text(
                textwrap.dedent(
                    """
                    ---
                    agent: code-developer
                    agent_id: developer-agent-1
                    status: ready
                    inputs:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md
                    outputs:
                      - docs/agent-runs/run/evidence/implementation-manifest.md
                    input_hashes:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/implementation-manifest.md sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                    consumed_by:
                      - coverage-reviewer
                    open_questions: None
                    ---

                    # Agent Handoff

                    ## Open Questions

                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            self.write_ready_marker(handoff, sha256="0" * 64)

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("sha256" in reason.lower() for reason in result["blocked_reasons"]))

    def test_handoff_gate_blocks_ready_marker_path_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            handoff = handoff_dir / "04-code-developer.md"
            handoff.write_text(
                textwrap.dedent(
                    """
                    ---
                    agent: code-developer
                    agent_id: developer-agent-1
                    status: ready
                    inputs:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md
                    outputs:
                      - docs/agent-runs/run/evidence/implementation-manifest.md
                    input_hashes:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/implementation-manifest.md sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                    consumed_by:
                      - coverage-reviewer
                    open_questions: None
                    ---

                    # Agent Handoff

                    ## Open Questions

                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            marker = handoff.with_suffix(".ready.json")
            marker.write_text(
                json.dumps(
                    {
                        "path": "other.md",
                        "sha256": hashlib.sha256(handoff.read_bytes()).hexdigest(),
                        "producer_agent": "developer-agent-1",
                        "status": "ready",
                    }
                ),
                encoding="utf-8",
            )

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("path" in reason.lower() for reason in result["blocked_reasons"]))


class ContractGateTests(unittest.TestCase):
    def contract_doc(
        self,
        kind: str = "http",
        status: str = "verified",
        producer_ack: str = "ACK: quote-service owner approved",
        consumer_ack: str = "ACK: billing-service owner approved",
        contract_tests: str = "QuoteBillingContractTest",
    ) -> str:
        transport_field = "- Endpoint: POST /billing/callback" if kind == "http" else "- Topic: quote.created\n- Tag: paid\n- Group: billing"
        return textwrap.dedent(
            f"""
            # quote-to-billing

            - Contract ID: quote-to-billing
            - Kind: {kind}
            - Producer Service: services/quote-service
            - Consumer Services: services/billing-service
            {transport_field}
            - Payload Schema: QuoteCreatedEvent(orderId, amount)
            - Compatibility Rule: backward-compatible additive fields only
            - Producer ACK: {producer_ack}
            - Consumer ACK: {consumer_ack}
            - Contract Tests: {contract_tests}
            - Status: {status}
            """
        ).strip()

    def test_contract_gate_blocks_missing_consumer_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            contract_dir = repo / "docs" / "agent-runs" / "run" / "contracts"
            contract_dir.mkdir(parents=True)
            (contract_dir / "quote-to-billing.md").write_text(
                self.contract_doc(consumer_ack=""),
                encoding="utf-8",
            )

            result = contract_gate.validate(repo, [contract_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("consumer ack" in reason.lower() for reason in result["blocked_reasons"]))

    def test_contract_gate_blocks_missing_contract_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            contract_dir = repo / "docs" / "agent-runs" / "run" / "contracts"
            contract_dir.mkdir(parents=True)
            (contract_dir / "quote-to-billing.md").write_text(
                self.contract_doc(contract_tests="None"),
                encoding="utf-8",
            )

            result = contract_gate.validate(repo, [contract_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("contract tests" in reason.lower() for reason in result["blocked_reasons"]))

    def test_contract_gate_allows_verified_http_contract_with_bidirectional_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            contract_dir = repo / "docs" / "agent-runs" / "run" / "contracts"
            contract_dir.mkdir(parents=True)
            (contract_dir / "quote-to-billing.md").write_text(self.contract_doc(), encoding="utf-8")

            result = contract_gate.validate(repo, [contract_dir])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["services/billing-service"], result["items"][0]["consumer_services"])

    def test_contract_gate_allows_verified_dmq_contract_with_topic_tag_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            contract_dir = repo / "docs" / "agent-runs" / "run" / "contracts"
            contract_dir.mkdir(parents=True)
            (contract_dir / "quote-created.md").write_text(self.contract_doc(kind="dmq"), encoding="utf-8")

            result = contract_gate.validate(repo, [contract_dir])

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_archive_handoff_template_contains_machine_checkable_communication_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

            e2e_dev_harness.create_handoff_files(repo, artifacts)

            text = (repo / artifacts["implementation_plan"]).read_text(encoding="utf-8")

        self.assertIn("agent_id:", text)
        self.assertIn("input_hashes:", text)
        self.assertIn("output_hashes:", text)
        self.assertIn("consumed_by:", text)
        self.assertIn("open_questions:", text)
        self.assertIn("Summarize implementation scope", text)
        self.assertIn("This is a draft starter handoff", text)

    def test_role_handoff_templates_contain_actionable_role_guidance(self) -> None:
        requirements = e2e_dev_harness.handoff_text("requirements-clarifier")
        use_cases = e2e_dev_harness.handoff_text("use-case-designer")
        tests = e2e_dev_harness.handoff_text("test-case-developer")
        code = e2e_dev_harness.handoff_text("code-developer")

        self.assertIn("Restate the user intent", requirements)
        self.assertIn("happy paths, failure paths", use_cases)
        self.assertIn("red-test intent", tests)
        self.assertIn("changed runtime path", code)

    def test_review_request_template_names_default_profile_and_checklist(self) -> None:
        text = e2e_dev_harness.review_request_template(
            "implementation",
            "R3 implementation semantic review request",
            "docs/agent-runs/run/reviews/R3-implementation-review.md",
        )

        self.assertIn("Review Profile: skills/e2e-dev-harness/review-profiles/default.json", text)
        self.assertIn("Code Path Trace", text)
        self.assertIn("ac-code-path-trace", text)
        self.assertIn("security-negative-paths", text)
        self.assertIn("project-pattern-consistency", text)


class ReworkGateTests(unittest.TestCase):
    def test_rework_gate_requires_required_fields(self) -> None:
        item = textwrap.dedent(
            """
            # Rework Item

            - Source: coverage-reviewer
            - Related AC: AC-2
            - Affected Services: services/sample-service
            - Problem Type: missing-code
            - Return Phase: tdd-implement
            - Evidence: AC-2 has no implementation.
            - Exit Criteria: Completion gate passes.
            - Status: open
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            rework_dir = repo / "docs" / "agent-runs" / "run" / "rework"
            rework_dir.mkdir(parents=True)
            (rework_dir / "rework-001.md").write_text(item, encoding="utf-8")

            result = rework_gate.validate(repo, [rework_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("Required Red Test" in reason for reason in result["blocked_reasons"]))

    def test_rework_gate_routes_missing_code_to_tdd_implement(self) -> None:
        item = textwrap.dedent(
            """
            # Rework Item

            - Source: coverage-reviewer
            - Related AC: AC-2
            - Affected Services: services/sample-service
            - Problem Type: missing-code
            - Return Phase: tdd-implement
            - Required Red Test: QuoteServiceTest covers AC-2 failure case
            - Evidence: AC-2 has no code refs.
            - Exit Criteria: AC-2 coverage row is verified.
            - Status: open
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            rework_dir = repo / "docs" / "agent-runs" / "run" / "rework"
            rework_dir.mkdir(parents=True)
            (rework_dir / "rework-001.md").write_text(item, encoding="utf-8")

            result = rework_gate.validate(repo, [rework_dir])

        self.assertEqual("tdd-implement", result["items"][0]["expected_return_phase"])
        self.assertEqual("tdd-implement", result["items"][0]["return_phase"])


class ReviewerGateTests(unittest.TestCase):
    PROFILE_CHECKLIST = {
        "design": ["ac-completeness", "dependency-impact", "security-sensitive-paths"],
        "test": ["happy-and-failure-paths", "contract-coverage", "security-negative-paths"],
        "implementation": [
            "ac-code-path-trace",
            "implementation-completeness",
            "security-negative-paths",
            "project-pattern-consistency",
        ],
    }

    def profile_checklist(self, phase: str) -> str:
        items = self.PROFILE_CHECKLIST.get(phase, [])
        if not items:
            return ""
        return "## Required Review Checklist\n\n" + "\n".join(f"- [x] {item}: checked." for item in items)

    def review_doc(
        self,
        phase: str,
        status: str = "approved",
        findings: str = "None",
        required_rework: str = "None",
        checklist: str = "",
        request: str | None = None,
        developer_agent: str = "developer-agent-1",
        reviewer_agent: str = "reviewer-agent-1",
        independence: str = "independent-agent",
        request_hash: str = "",
        reviewer_session: str = "review-session-1",
        reviewer_invocation: str | None = None,
    ) -> str:
        request = request or f"docs/agent-runs/run/review-requests/{phase}-review-request.md"
        reviewer_invocation = reviewer_invocation or f"docs/agent-runs/run/review-invocations/{phase}-reviewer-invocation.json"
        request_hash_line = f"- Request Hash: {request_hash}\n" if request_hash else ""
        return textwrap.dedent(
            f"""
            # {phase.title()} Review

            - Phase: {phase}
            - Reviewer: semantic-reviewer
            - Review Request: {request}
            - Developer Agent: {developer_agent}
            - Reviewer Agent: {reviewer_agent}
            - Reviewer Session: {reviewer_session}
            - Reviewer Invocation: {reviewer_invocation}
            {request_hash_line.rstrip()}
            - Independence: {independence}
            - Context Boundary: request-scoped; no inherited developer chat context
            - No Code Changes: confirmed
            - Scope: services/payment-service
            - Inputs Reviewed: design doc; tests; implementation files
            - Findings: {findings}
            - Required Rework: {required_rework}
            - Status: {status}

            {checklist}
            """
        ).strip()

    def write_request(
        self,
        repo: Path,
        phase: str,
        request_name: str | None = None,
        output_name: str | None = None,
        request_phase: str | None = None,
        developer_agent: str = "developer-agent-1",
        reviewer_agent: str = "reviewer-agent-1",
        reviewer_session: str = "review-session-1",
    ) -> str:
        request_name = request_name or f"{phase}-review-request.md"
        output_name = output_name or {
            "design": "R1-design-review.md",
            "test": "R2-test-review.md",
            "implementation": "R3-implementation-review.md",
        }.get(phase, f"{phase}-review.md")
        request = repo / "docs" / "agent-runs" / "run" / "review-requests" / request_name
        invocation = repo / "docs" / "agent-runs" / "run" / "review-invocations" / f"{phase}-reviewer-invocation.json"
        invocation.parent.mkdir(parents=True, exist_ok=True)
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text(
            textwrap.dedent(
                f"""
                # {phase.title()} Review Request

                - Phase: {request_phase or phase}
                - Reviewer Role: independent semantic reviewer
                - Context Package: request-scoped; no inherited developer chat context
                - Allowed Inputs: design, tests, implementation refs, dependency report
                - Forbidden: inherited developer chat context; production-code edits; self-review
                - Output: docs/agent-runs/run/reviews/{output_name}
                - Developer Agent: {developer_agent}
                - Reviewer Agent: {reviewer_agent}
                - Reviewer Invocation: docs/agent-runs/run/review-invocations/{phase}-reviewer-invocation.json
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
                    "developer_session": "developer-session-1",
                    "reviewer_agent": reviewer_agent,
                    "reviewer_session": reviewer_session,
                    "context_pack": f"docs/agent-runs/run/review-requests/{request_name}",
                    "review_request": f"docs/agent-runs/run/review-requests/{request_name}",
                    "output": f"docs/agent-runs/run/reviews/{output_name}",
                    "fork_context": False,
                    "context_policy": "request-scoped; no-inherited-developer-chat-context",
                    "status": "completed",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(request.relative_to(repo)).replace("\\", "/")

    def request_hash(self, repo: Path, request: str) -> str:
        return hashlib.sha256((repo / request).read_bytes()).hexdigest()

    def write_service_review(
        self,
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
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        review.write_text(
            self.review_doc(
                phase,
                checklist=self.profile_checklist(phase),
                request=request_rel,
                request_hash=hashlib.sha256(request.read_bytes()).hexdigest(),
                developer_agent=developer_agent,
                reviewer_agent=reviewer_agent,
                reviewer_session=reviewer_session,
                reviewer_invocation=invocation_rel,
            ).replace("- Scope: services/payment-service", f"- Scope: {service}"),
            encoding="utf-8",
        )
        return review

    def test_reviewer_gate_requires_all_phase_reviews_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "design")
            (review_dir / "R1-design-review.md").write_text(
                self.review_doc("design", request=request, request_hash=self.request_hash(repo, request)),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["design", "test", "implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("test" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertTrue(any("implementation" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_allows_approved_phase_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            for name, phase in (
                ("R1-design-review.md", "design"),
                ("R2-test-review.md", "test"),
                ("R3-implementation-review.md", "implementation"),
            ):
                request = self.write_request(repo, phase)
                (review_dir / name).write_text(
                    self.review_doc(phase, request=request, request_hash=self.request_hash(repo, request)),
                    encoding="utf-8",
                )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["design", "test", "implementation"])

        self.assertTrue(result["ready"])
        self.assertEqual(["design", "implementation", "test"], sorted(result["covered_phases"]))

    def test_reviewer_gate_blocks_open_review_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    status="blocked",
                    findings="Missing VnpayQrOrderRS.",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("blocked" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_findings_without_rework_or_blocking_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    findings="Missing negative authorization test.",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("findings" in reason.lower() and "rework" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_uses_profile_required_checklist_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            profile = repo / "review-profiles" / "strict.json"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                json.dumps(
                    {
                        "required_checklist": {
                            "implementation": [
                                {
                                    "id": "security-negative-paths",
                                    "title": "Security negative paths",
                                    "required": True,
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    checklist="## Review Checklist\n\n- [x] project-pattern-consistency: checked",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(
                repo,
                [review_dir],
                require_phases=["implementation"],
                review_profile=profile,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("security-negative-paths" in reason for reason in result["blocked_reasons"]))

    def test_reviewer_gate_resolves_bundled_default_review_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    checklist=textwrap.dedent(
                        """
                        ## Review Checklist

                        - [x] ac-code-path-trace: checked
                        - [x] implementation-completeness: checked
                        - [x] security-negative-paths: checked
                        - [x] project-pattern-consistency: checked
                        """
                    ).strip(),
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(
                repo,
                [review_dir],
                require_phases=["implementation"],
                review_profile=Path("skills/e2e-dev-harness/review-profiles/default.json"),
        )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(result["review_profile"].replace("\\", "/").endswith("skills/e2e-dev-harness/review-profiles/default.json"))

    def test_reviewer_gate_auto_discovers_project_review_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            profile = repo / ".e2e" / "review-profile.json"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                json.dumps(
                    {
                        "required_checklist": {
                            "implementation": [
                                {
                                    "id": "project-specific-risk",
                                    "title": "Project-specific risk",
                                    "description": "Reviewer must check the project-specific edge case.",
                                    "severity": "blocker",
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    checklist="## Review Checklist\n\n- [x] project-pattern-consistency: checked",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertEqual("project", result["review_profile_source"])
        self.assertTrue(result["review_profile"].replace("\\", "/").endswith(".e2e/review-profile.json"))
        self.assertTrue(any("project-specific-risk" in reason for reason in result["blocked_reasons"]))

    def test_reviewer_gate_explicit_profile_overrides_project_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project_profile = repo / ".e2e" / "review-profile.json"
            project_profile.parent.mkdir(parents=True)
            project_profile.write_text(
                '{"required_checklist":{"implementation":["project-specific-risk"]}}\n',
                encoding="utf-8",
            )
            explicit_profile = repo / "docs" / "review-profiles" / "explicit.json"
            explicit_profile.parent.mkdir(parents=True)
            explicit_profile.write_text(
                '{"required_checklist":{"implementation":["project-pattern-consistency"]}}\n',
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    checklist="## Review Checklist\n\n- [x] project-pattern-consistency: checked",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(
                repo,
                [review_dir],
                require_phases=["implementation"],
                review_profile=explicit_profile,
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("explicit", result["review_profile_source"])
        self.assertTrue(result["review_profile"].replace("\\", "/").endswith("docs/review-profiles/explicit.json"))

    def test_reviewer_gate_merges_profile_extends_and_warns_for_warning_severity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            profile = repo / ".e2e" / "review-profile.json"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                json.dumps(
                    {
                        "extends": "default",
                        "required_checklist": {
                            "implementation": [
                                {
                                    "id": "project-specific-risk",
                                    "title": "Project-specific risk",
                                    "severity": "blocker",
                                },
                                {
                                    "id": "observability-note",
                                    "title": "Observability note",
                                    "description": "Reviewer should mention logs or metrics when relevant.",
                                    "severity": "warning",
                                },
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    checklist=textwrap.dedent(
                        """
                        ## Review Checklist

                        - [x] ac-code-path-trace: checked
                        - [x] implementation-completeness: checked
                        - [x] security-negative-paths: checked
                        - [x] project-pattern-consistency: checked
                        - [x] project-specific-risk: checked
                        """
                    ).strip(),
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("project", result["review_profile_source"])
        self.assertTrue(any("default.json" in path.replace("\\", "/") for path in result["review_profile_chain"]))
        self.assertTrue(any("observability-note" in warning for warning in result["warnings"]))

    def test_reviewer_gate_blocks_self_review_even_if_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    developer_agent="agent-1",
                    reviewer_agent="agent-1",
                    independence="self-review",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("independent" in reason.lower() or "same" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_requires_existing_review_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            (review_dir / "R2-test-review.md").write_text(
                self.review_doc("test", request="docs/agent-runs/run/review-requests/missing.md", request_hash="0" * 64),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["test"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("review request" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_request_phase_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation", request_phase="test")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request)),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("phase" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_request_output_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation", output_name="other-review.md")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request)),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("declared" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_placeholder_agent_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(
                repo,
                "implementation",
                developer_agent="<developer-agent-id>",
                reviewer_agent="<independent-reviewer-agent-id>",
            )
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    developer_agent="<developer-agent-id>",
                    reviewer_agent="<independent-reviewer-agent-id>",
                    reviewer_session="<reviewer-session-id>",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("placeholder" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_request_developer_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation", developer_agent="developer-agent-1")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    developer_agent="developer-agent-2",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("developer agent" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_request_reviewer_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation", reviewer_agent="reviewer-agent-1")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    reviewer_agent="reviewer-agent-2",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("reviewer agent" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_tampered_request_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash="0" * 64),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("request hash" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_invocation_forked_from_developer_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            invocation = repo / "docs" / "agent-runs" / "run" / "review-invocations" / "implementation-reviewer-invocation.json"
            data = json.loads(invocation.read_text(encoding="utf-8"))
            data["fork_context"] = True
            invocation.write_text(json.dumps(data), encoding="utf-8")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request)),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("fork_context" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_independence_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    independence="subagent",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("independence" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_missing_service_local_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            for service in ("jeepay-core", "jeepay-service"):
                (repo / "docs" / "agent-runs" / "run" / "service-plans" / service).mkdir(parents=True)
            for name, phase in (
                ("R1-design-review.md", "design"),
                ("R2-test-review.md", "test"),
                ("R3-implementation-review.md", "implementation"),
            ):
                request = self.write_request(repo, phase)
                (review_dir / name).write_text(
                    self.review_doc(phase, request=request, request_hash=self.request_hash(repo, request)),
                    encoding="utf-8",
                )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["design", "test", "implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("jeepay-core" in reason and "test" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("jeepay-service" in reason and "implementation" in reason for reason in result["blocked_reasons"]))

    def test_reviewer_gate_merges_explicit_review_dir_with_service_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            for name, phase in (
                ("R1-design-review.md", "design"),
                ("R2-test-review.md", "test"),
                ("R3-implementation-review.md", "implementation"),
            ):
                request = self.write_request(repo, phase)
                (review_dir / name).write_text(
                    self.review_doc(phase, request=request, request_hash=self.request_hash(repo, request)),
                    encoding="utf-8",
                )
            self.write_service_review(repo, "jeepay-core", "test")
            self.write_service_review(repo, "jeepay-core", "implementation")

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["design", "test", "implementation"])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertIn("jeepay-core", result["expected_services"])
        self.assertEqual(["implementation", "test"], sorted(result["covered_service_reviews"]["jeepay-core"]))

    def test_reviewer_gate_requires_r3_code_path_trace_for_each_acceptance_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants a quote returned.
                    - User confirmation: confirmed-by: user @2026-06-02

                    ## Goal
                    - Return a quote.

                    ## Scope
                    - services/sample-service

                    ## Use Cases
                    - Create quote.

                    ## Acceptance Criteria
                    - AC-1 Quote is returned.
                    - AC-2 Invalid input is rejected.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-02
                    """
                ).strip(),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request)),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], [design], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("code path trace" in reason.lower() and "AC-1" in reason for reason in result["blocked_reasons"]))

    def test_reviewer_gate_allows_r3_code_path_trace_for_each_acceptance_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants a quote returned.
                    - User confirmation: confirmed-by: user @2026-06-02

                    ## Goal
                    - Return a quote.

                    ## Scope
                    - services/sample-service

                    ## Use Cases
                    - Create quote.

                    ## Acceptance Criteria
                    - AC-1 Quote is returned.
                    - AC-2 Invalid input is rejected.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-02
                    """
                ).strip(),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            trace = textwrap.dedent(
                """
                ## Code Path Trace

                - AC-1: QuoteController -> QuoteService.create -> QuoteRepository.save -> QuoteResponse.
                - AC-2: QuoteController -> QuoteRequestValidator.rejects invalid input -> error response.
                """
            ).strip()
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request), checklist=trace),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], [design], require_phases=["implementation"])

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_reviewer_gate_blocks_messaging_ac_without_sender_path_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants a quote returned.
                    - User confirmation: confirmed-by: user @2026-06-02

                    ## Goal
                    - Publish refund callback.

                    ## Scope
                    - services/payment-service

                    ## Use Cases
                    - Refund succeeds.

                    ## Acceptance Criteria
                    - AC-1 Publish DMQ refund callback with topic, tag, group, and payload fields.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-02
                    """
                ).strip(),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            trace = textwrap.dedent(
                """
                ## Code Path Trace

                - AC-1: RefundController -> RefundService.complete -> success response.
                """
            ).strip()
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request), checklist=trace),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], [design], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("messaging path trace" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_allows_messaging_ac_with_sender_path_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Goal
                    - Publish refund callback.

                    ## Scope
                    - services/payment-service

                    ## Use Cases
                    - Refund succeeds.

                    ## Acceptance Criteria
                    - AC-1 Publish DMQ refund callback with topic, tag, group, and payload fields.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            trace = textwrap.dedent(
                """
                ## Code Path Trace

                - AC-1: RefundController -> RefundService.complete -> RefundCallbackDmqSender.send(topic, tag, group, payload) -> PaymentCallbackDmqSenderTest verifies payload fields.

                ## Messaging Path Trace

                - AC-1 sender/producer injection point: RefundService constructor injects RefundCallbackDmqSender.
                - AC-1 actual send call: RefundCallbackDmqSender.send(topic, tag, group, payload).
                - AC-1 topic/tag/group: refund.callback / success / payment-service.
                - AC-1 payload fields: refundId, status, amount, updatedAt.
                - AC-1 test evidence: PaymentCallbackDmqSenderTest verifies topic, tag, group, and payload.
                """
            ).strip()
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request), checklist=trace),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], [design], require_phases=["implementation"])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual([], result["items"][0]["missing_code_path_trace_acs"])


class RequirementsArchiveTests(unittest.TestCase):
    def archive_doc(self) -> str:
        return textwrap.dedent(
            """
            # Requirements Archive

            ## Original Request
            Build quote creation.

            ## Final Clarified Requirement
            Return a quote for valid input and reject invalid input.

            ## Scope And Non-Goals
            Scope: services/sample-service. Non-goals: billing integration.

            ## Acceptance Criteria Status
            | id | requirement | status | evidence |
            | --- | --- | --- | --- |
            | AC-1 | Quote is returned | verified | docs/agent-runs/run/evidence/coverage-matrix.md |

            ## Use Case Coverage
            UC-1 covers AC-1 happy path and validation failure.

            ## Impacted Services APIs And Contracts
            services/sample-service; no HTTP/DMQ contract change.

            ## Implementation Evidence
            docs/agent-runs/run/evidence/implementation-manifest.md

            ## Test Evidence
            docs/agent-runs/run/evidence/green-test.txt

            ## Review And Rework Summary
            R1/R2/R3 approved; no open rework.

            ## Deferred And Residual Risks
            None.

            ## Promoted Memory Entries
            M-1 promoted to memory/decisions.md.

            ## Follow Up Opportunities
            None.
            """
        ).strip()

    def test_requirements_archive_blocks_missing_required_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            archive = repo / "docs" / "agent-runs" / "run" / "requirements-archive.md"
            archive.parent.mkdir(parents=True)
            archive.write_text("# Requirements Archive\n\n## Original Request\nBuild quote creation.\n", encoding="utf-8")

            result = requirements_archive.validate(repo, archive)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Final Clarified Requirement" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("Acceptance Criteria Status" in reason for reason in result["blocked_reasons"]))

    def test_requirements_archive_allows_complete_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            archive = repo / "docs" / "agent-runs" / "run" / "requirements-archive.md"
            archive.parent.mkdir(parents=True)
            archive.write_text(self.archive_doc(), encoding="utf-8")

            result = requirements_archive.validate(repo, archive)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(12, result["section_count"])

    def test_requirements_archive_blocks_placeholders_in_required_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            archive = repo / "docs" / "agent-runs" / "run" / "requirements-archive.md"
            archive.parent.mkdir(parents=True)
            archive.write_text(self.archive_doc().replace("Return a quote for valid input", "TBD"), encoding="utf-8")

            result = requirements_archive.validate(repo, archive)

        self.assertFalse(result["ready"])
        self.assertTrue(any("placeholder" in reason.lower() for reason in result["blocked_reasons"]))

    def test_requirements_archive_discovers_archive_from_agent_run_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            archive = repo / "docs" / "agent-runs" / "run" / "requirements-archive.md"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            red.parent.mkdir(parents=True)
            archive.write_text(self.archive_doc(), encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")

            discovered = requirements_archive.discover(repo, [red])

        self.assertEqual(archive.resolve(), discovered.resolve())


class ImplementationGateTests(unittest.TestCase):
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

    def test_implementation_gate_requires_run_state_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(repo=repo, phase="implementation")
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("--run-state" in reason for reason in result["blocked_reasons"]))

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
            repo / "approval.md"
            repo / "approval.md"
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
            repo / "approval.md"
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
            repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            dependency_report = repo / "knowledge-graph" / "cross-service-dependencies.json"
            repo / "approval.md"
            repo / "approval.md"
            repo / "approval.md"
            repo / "approval.md"
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
            service_review_helper = ReviewerGateTests()
            service_review_helper.write_service_review(repo, "sample-service", "test")
            service_r3 = service_review_helper.write_service_review(repo, "sample-service", "implementation")
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


class SpringStaticCheckTests(unittest.TestCase):
    def test_constructor_injection_requires_component_or_bean(self) -> None:
        spring_static_check = importlib.import_module("spring_static_check")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source = repo / "services" / "order-service" / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (source / "OrderService.java").write_text(
                textwrap.dedent(
                    """
                    package com.example;

                    import org.springframework.stereotype.Service;

                    @Service
                    public class OrderService {
                        public OrderService(InventoryClient inventoryClient) {
                        }
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )
            (source / "InventoryClient.java").write_text(
                textwrap.dedent(
                    """
                    package com.example;

                    public class InventoryClient {
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = spring_static_check.validate(repo)

        self.assertFalse(result["ready"])
        self.assertTrue(any("InventoryClient" in reason for reason in result["blocked_reasons"]))

    def test_constructor_injection_accepts_component_dependency(self) -> None:
        spring_static_check = importlib.import_module("spring_static_check")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source = repo / "services" / "order-service" / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (source / "OrderService.java").write_text(
                textwrap.dedent(
                    """
                    package com.example;

                    import org.springframework.stereotype.Service;

                    @Service
                    public class OrderService {
                        public OrderService(InventoryClient inventoryClient) {
                        }
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )
            (source / "InventoryClient.java").write_text(
                textwrap.dedent(
                    """
                    package com.example;

                    import org.springframework.stereotype.Component;

                    @Component
                    public class InventoryClient {
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = spring_static_check.validate(repo)

        self.assertTrue(result["ready"])

    def test_constructor_injection_accepts_configuration_bean(self) -> None:
        spring_static_check = importlib.import_module("spring_static_check")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source = repo / "services" / "order-service" / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (source / "OrderService.java").write_text(
                textwrap.dedent(
                    """
                    package com.example;

                    import org.springframework.stereotype.Service;

                    @Service
                    public class OrderService {
                        public OrderService(InventoryClient inventoryClient) {
                        }
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )
            (source / "InventoryClient.java").write_text(
                textwrap.dedent(
                    """
                    package com.example;

                    public class InventoryClient {
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )
            (source / "ApplicationConfig.java").write_text(
                textwrap.dedent(
                    """
                    package com.example;

                    import org.springframework.context.annotation.Bean;
                    import org.springframework.context.annotation.Configuration;

                    @Configuration
                    public class ApplicationConfig {
                        @Bean
                        public InventoryClient inventoryClient() {
                            return new InventoryClient();
                        }
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = spring_static_check.validate(repo)

        self.assertTrue(result["ready"])

    def test_blocks_shared_simple_date_format_field_in_spring_component(self) -> None:
        spring_static_check = importlib.import_module("spring_static_check")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source = repo / "services" / "payment-service" / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (source / "VnpayPaymentService.java").write_text(
                textwrap.dedent(
                    """
                    package com.example;

                    import java.text.SimpleDateFormat;
                    import org.springframework.stereotype.Service;

                    @Service
                    public class VnpayPaymentService {
                        private final SimpleDateFormat formatter = new SimpleDateFormat("yyyyMMddHHmmss");
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = spring_static_check.validate(repo)

        self.assertFalse(result["ready"])
        self.assertTrue(any("SimpleDateFormat" in reason for reason in result["blocked_reasons"]))

    def test_blocks_mq_message_sent_through_mismatched_sender(self) -> None:
        spring_static_check = importlib.import_module("spring_static_check")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source = repo / "services" / "payment-service" / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (source / "ReconcileAutoHandler.java").write_text(
                textwrap.dedent(
                    """
                    package com.example;

                    import org.springframework.stereotype.Component;

                    @Component
                    public class ReconcileAutoHandler {
                        private final IMQSender diffFoundNotifySender;
                        private final IMQSender autoHandleResultNotifySender;

                        public ReconcileAutoHandler(IMQSender diffFoundNotifySender,
                                                    IMQSender autoHandleResultNotifySender) {
                            this.diffFoundNotifySender = diffFoundNotifySender;
                            this.autoHandleResultNotifySender = autoHandleResultNotifySender;
                        }

                        public void handle() {
                            AutoHandleResultNotifyMQ mqMsg = AutoHandleResultNotifyMQ.build();
                            diffFoundNotifySender.send(mqMsg);
                        }
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = spring_static_check.validate(repo)

        self.assertFalse(result["ready"])
        self.assertTrue(any("AutoHandleResultNotifyMQ" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("diffFoundNotifySender" in reason for reason in result["blocked_reasons"]))

    def test_allows_generic_mq_sender_for_specific_message(self) -> None:
        spring_static_check = importlib.import_module("spring_static_check")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source = repo / "services" / "payment-service" / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (source / "ReconcileAutoHandler.java").write_text(
                textwrap.dedent(
                    """
                    package com.example;

                    import org.springframework.stereotype.Component;

                    @Component
                    public class ReconcileAutoHandler {
                        public void handle(IMQSender mqSender) {
                            AutoHandleResultNotifyMQ mqMsg = AutoHandleResultNotifyMQ.build();
                            mqSender.send(mqMsg);
                        }
                    }
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = spring_static_check.validate(repo)

        self.assertTrue(result["ready"], result["blocked_reasons"])


class MemoryCaptureTests(unittest.TestCase):
    def test_validate_blocks_local_paths_and_duplicate_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            (repo / "memory" / "graph-findings.md").write_text(
                textwrap.dedent(
                    """
                    # Graph Findings Memory

                    ## Entries

                    ### M-1

                    - Type: graph-finding
                    - Source: graphify
                    - Confidence: verified
                    - Text: Duplicate fact.

                    ### M-2

                    - Type: graph-finding
                    - Source: graphify
                    - Confidence: verified
                    - Text: Duplicate fact.
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = memory_capture.validate_memory(repo)

        self.assertFalse(result["ready"])
        joined = "\n".join(result["blocked_reasons"]).lower()
        self.assertIn("duplicate", joined)

    def test_validate_blocks_dirty_memory_text_outside_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            project = repo / "memory" / "project.md"
            project.write_text(
                "# Project Memory\n\n## Notes\n\nUse local tool at D:\\tools\\secret with api_key=abc123.\n",
                encoding="utf-8",
            )

            result = memory_capture.validate_memory(repo)

        joined = "\n".join(result["blocked_reasons"]).lower()
        self.assertFalse(result["ready"])
        self.assertIn("local path", joined)
        self.assertIn("secret", joined)

    def test_append_memory_blocks_existing_duplicate_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            first = memory_capture.append_memory(repo, "decision", "design", "verified", "Quote timeout is 3 seconds.")
            second = memory_capture.append_memory(repo, "decision", "design", "verified", "Quote timeout is 3 seconds.")

        self.assertIsNotNone(first["path"])
        self.assertIsNone(second["path"])
        self.assertTrue(any("duplicate" in reason.lower() for reason in second["blocked_reasons"]))

    def test_select_filters_by_phase_and_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            service_boundaries = repo / "memory" / "service-boundaries.md"
            service_boundaries.write_text(
                textwrap.dedent(
                    """
                    # Service Boundaries Memory

                    ## Entries

                    - services/order-service owns order quotes.
                    - services/payment-service owns payment capture.
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = memory_capture.select_memory(repo, "code", "services/order-service")

        snippets = "\n".join(item["text"] for item in result["snippets"])
        self.assertIn("order-service", snippets)
        self.assertNotIn("payment-service", snippets)
        self.assertIn("memory/service-boundaries.md", result["files"])

    def test_select_filters_entries_by_obsidian_service_tags_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "services" / "order-service" / "src").mkdir(parents=True)
            (repo / "services" / "payment-service" / "src").mkdir(parents=True)
            memory_capture.init_memory(repo)
            decisions = repo / "memory" / "decisions.md"
            decisions.write_text(
                textwrap.dedent(
                    """
                    # Decisions Memory

                    ## Entries

                    ### M-1

                    - Type: decision
                    - Source: design
                    - Confidence: verified
                    - Tags: #decision #service/order-service #phase/code
                    - Links: [[services/order-service]] [[AC-1]]
                    - Text: Order service owns quote timeout behavior.

                    ### M-2

                    - Type: decision
                    - Source: design
                    - Confidence: verified
                    - Tags: #decision #service/payment-service #phase/code
                    - Links: [[services/payment-service]] [[AC-2]]
                    - Text: Payment service owns capture retries.
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = memory_capture.select_memory(repo, "code", "services/order-service")

        snippets = "\n".join(item["text"] for item in result["snippets"])
        self.assertIn("#service/order-service", snippets)
        self.assertIn("[[services/order-service]]", snippets)
        self.assertIn("quote timeout", snippets)
        self.assertNotIn("payment-service", snippets)
        self.assertNotIn("capture retries", snippets)

    def test_validate_blocks_invalid_obsidian_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            decisions = repo / "memory" / "decisions.md"
            decisions.write_text(
                textwrap.dedent(
                    """
                    # Decisions Memory

                    ## Entries

                    ### M-1

                    - Type: decision
                    - Source: design
                    - Confidence: verified
                    - Tags: #Service/Order_Service
                    - Text: Order service owns quote timeout behavior.
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = memory_capture.validate_memory(repo)

        self.assertFalse(result["ready"])
        self.assertTrue(any("tag" in reason.lower() for reason in result["blocked_reasons"]))

    def test_validate_blocks_unsafe_obsidian_link(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Links: [[https://example.com/project]]
            - Text: External project page is relevant.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("link" in reason.lower() for reason in result["blocked_reasons"]))

    def test_promote_preserves_obsidian_tags_and_links(self) -> None:
        proposed = textwrap.dedent(
            """
            # Proposed Memory Updates

            ### M-1

            - Type: decision
            - Source: user-approved
            - Confidence: approved
            - Status: accepted
            - Tags: #decision #service/sample-service #phase/code
            - Links: [[services/sample-service]] [[AC-1]]
            - Text: Sample service owns quote calculation.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "services" / "sample-service" / "src").mkdir(parents=True)
            memory_capture.init_memory(repo)
            proposed_path = repo / "docs" / "agent-runs" / "run" / "proposed-memory-updates.md"
            proposed_path.parent.mkdir(parents=True)
            proposed_path.write_text(proposed, encoding="utf-8")

            result = memory_capture.promote_memory_updates(repo, proposed_path)

            decisions = (repo / "memory" / "decisions.md").read_text(encoding="utf-8")

        self.assertEqual(1, result["promoted_count"])
        self.assertIn("- Tags: #decision #service/sample-service #phase/code", decisions)
        self.assertIn("- Links: [[services/sample-service]] [[AC-1]]", decisions)

    def test_promote_imports_only_accepted_entries(self) -> None:
        proposed = textwrap.dedent(
            """
            # Proposed Memory Updates

            ### M-1

            - Type: decision
            - Source: user-approved
            - Confidence: approved
            - Status: accepted
            - Text: Use direct Spring Framework 6 configuration.

            ### M-2

            - Type: workflow-preference
            - Source: design
            - Confidence: observed
            - Status: rejected
            - Text: Skip TDD for small changes.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            proposed_path = repo / "docs" / "agent-runs" / "run" / "proposed-memory-updates.md"
            proposed_path.parent.mkdir(parents=True)
            proposed_path.write_text(proposed, encoding="utf-8")

            result = memory_capture.promote_memory_updates(repo, proposed_path)

            decisions = (repo / "memory" / "decisions.md").read_text(encoding="utf-8")
            workflow = (repo / "memory" / "workflow-preferences.md").read_text(encoding="utf-8")

        self.assertEqual(1, result["promoted_count"])
        self.assertIn("Spring Framework 6", decisions)
        self.assertNotIn("Skip TDD", workflow)


class OrchestrationArtifactTests(unittest.TestCase):
    def test_start_creates_controlled_run_design_and_locked_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            args = SimpleNamespace(
                repo=repo,
                feature="Refund MQ",
                request="Publish refund notification after success.",
                design_doc=None,
                agent_run_dir=None,
                run_id="run",
                run_date=None,
                force=False,
                status_file=None,
            )

            code, result = e2e_dev_harness.start(args)
            design = Path(result["design_doc"])
            design_exists = design.exists()
            design_text = design.read_text(encoding="utf-8")
            state = json.loads(Path(result["run_state"]).read_text(encoding="utf-8"))
            lock = json.loads(Path(result["phase_lock"]).read_text(encoding="utf-8"))
            guard = phase_guard.validate_action(repo, "Write", [Path("services/refund/src/main/java/RefundService.java")])

        self.assertEqual(0, code)
        self.assertTrue(design_exists)
        self.assertIn("## Restated Intent", design_text)
        self.assertEqual("CREATED", state["lifecycle"])
        self.assertEqual("code-write-locked", lock["state"])
        self.assertFalse(guard["ready"])

    def test_start_records_review_policy_request_minimum_and_effective_tier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            args = SimpleNamespace(
                repo=repo,
                feature="Admin Lookup",
                request="Add one REST API endpoint in order-service for an admin lookup screen.",
                design_doc=None,
                agent_run_dir=None,
                run_id="run",
                run_date=None,
                workflow_profile="basic",
                force=False,
                status_file=None,
            )

            code, result = e2e_dev_harness.start(args)
            workflow = json.loads(Path(result["workflow_plan"]).read_text(encoding="utf-8"))
            state = json.loads(Path(result["run_state"]).read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertEqual("basic", workflow["review_policy"]["user_requested"])
        self.assertEqual("standard", workflow["review_policy"]["auto_minimum"]["tier"])
        self.assertEqual("standard", workflow["review_policy"]["effective"]["tier"])
        self.assertTrue(workflow["review_policy"]["downgrade_blocked"])
        self.assertEqual(workflow["review_policy"], state["review_policy"])

    def test_start_cli_accepts_review_tier_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            argv = [
                "e2e_dev_harness.py",
                "start",
                str(repo),
                "--feature",
                "Admin Lookup",
                "--request",
                "Add one REST API endpoint in order-service for an admin lookup screen.",
                "--run-id",
                "run",
                "--review-tier",
                "basic",
                "--json-full",
            ]

            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                code = e2e_dev_harness.main()
            workflow = json.loads((repo / "docs" / "agent-runs" / "run" / "workflow-plan.json").read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertEqual("basic", workflow["review_policy"]["user_requested"])
        self.assertEqual("standard", workflow["review_policy"]["effective"]["tier"])
        self.assertTrue(workflow["review_policy"]["downgrade_blocked"])

    def test_start_cli_compact_output_reports_review_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            argv = [
                "e2e_dev_harness.py",
                "start",
                str(repo),
                "--feature",
                "Admin Lookup",
                "--request",
                "Add one REST API endpoint in order-service for an admin lookup screen.",
                "--run-id",
                "run",
                "--review-tier",
                "basic",
            ]
            stdout = io.StringIO()

            with patch.object(sys, "argv", argv), redirect_stdout(stdout):
                code = e2e_dev_harness.main()
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, code)
        self.assertEqual("compact", payload["stdout_mode"])
        self.assertEqual("basic", payload["review_policy"]["user_requested"])
        self.assertEqual("standard", payload["review_policy"]["auto_minimum"])
        self.assertEqual("standard", payload["review_policy"]["effective"])
        self.assertTrue(payload["review_policy"]["downgrade_blocked"])

    def test_start_cli_review_tier_overrides_phase_profile_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            profile = repo / "phase-profile.json"
            profile.write_text(json.dumps({"review_policy": {"tier": "audited"}}), encoding="utf-8")
            argv = [
                "e2e_dev_harness.py",
                "start",
                str(repo),
                "--feature",
                "Label",
                "--request",
                "Update a settings label.",
                "--run-id",
                "run",
                "--phase-profile",
                str(profile),
                "--review-tier",
                "basic",
                "--json-full",
            ]

            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                code = e2e_dev_harness.main()
            workflow = json.loads((repo / "docs" / "agent-runs" / "run" / "workflow-plan.json").read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertEqual("basic", workflow["review_policy"]["user_requested"])
        self.assertEqual("basic", workflow["review_policy"]["effective"]["tier"])
        self.assertFalse(workflow["review_policy"]["downgrade_blocked"])

    def test_control_plane_repair_cli_repairs_task_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            run_dir.mkdir(parents=True)
            control_plane_path = run_dir / "control-plane.json"
            control_plane_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.control-plane.v1",
                        "run_id": "docs/agent-runs/run",
                        "lifecycle": "CREATED",
                        "gates": {},
                        "phase_lock": {
                            "schema": "e2e-dev-harness.phase-lock.v1",
                            "lifecycle": "CREATED",
                            "state": "code-write-locked",
                            "code_writes_allowed": False,
                        },
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "status": "planned",
                            }
                        ],
                        "dispatches": {},
                        "repair_transactions": [],
                        "artifacts": {},
                        "coordinator": {},
                        "projections": {},
                        "history": [],
                    }
                ),
                encoding="utf-8",
            )
            argv = [
                "e2e_dev_harness.py",
                "control-plane",
                "repair",
                str(repo),
                "--run-dir",
                "docs/agent-runs/run",
                "--scope",
                "task-contracts",
                "--json-full",
            ]
            stdout = io.StringIO()

            with patch.object(sys, "argv", argv), redirect_stdout(stdout):
                code = e2e_dev_harness.main()
            payload = json.loads(stdout.getvalue())
            repaired = json.loads(control_plane_path.read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertTrue(payload["ready"], payload.get("blocked_reasons"))
        self.assertEqual(["task-contracts"], payload["scopes"])
        self.assertEqual("design", repaired["tasks"][0]["role_group"])
        self.assertEqual("fresh-subagent", repaired["tasks"][0]["dispatch_contract"])

    def test_next_reports_clarify_after_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            start_args = SimpleNamespace(
                repo=repo,
                feature="Quote",
                request="Return a quote.",
                design_doc=None,
                agent_run_dir=None,
                run_id="run",
                run_date=None,
                force=False,
                status_file=None,
            )
            _code, start_result = e2e_dev_harness.start(start_args)
            next_args = SimpleNamespace(repo=repo, state=Path(start_result["run_state"]), status_file=None)

            code, result = e2e_dev_harness.next_step(next_args)
            checkpoint_exists = Path(result["session_checkpoint"]["checkpoint"]).exists()

        self.assertEqual(0, code)
        self.assertEqual("CREATED", result["lifecycle"])
        self.assertEqual("clarify", result["next"]["phase"])
        self.assertTrue(checkpoint_exists)

    def test_phase_guard_requires_fresh_session_checkpoint_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            write_implemented_state(repo, state_path, state)

            blocked = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
                require_session_checkpoint=True,
            )
            checkpoint = session_checkpoint.create(repo, state_path, {"phase": "implement-or-complete"})
            checkpointed_state = json.loads(state_path.read_text(encoding="utf-8"))
            checkpointed_state["dispatches"] = {
                "T07": {
                    "status": "worker_running",
                    "current_task_id": "T07",
                    "current_agent": "code-developer",
                    "worker_handle": "code-worker-1",
                }
            }
            checkpointed_state["dispatch"] = checkpointed_state["dispatches"]["T07"]
            run_state.write_state(repo, state_path, checkpointed_state)
            checkpoint = session_checkpoint.create(repo, state_path, {"phase": "implement-or-complete"})
            allowed = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
                require_session_checkpoint=True,
            )

        self.assertFalse(blocked["ready"])
        self.assertTrue(any("Session resume checkpoint" in reason for reason in blocked["blocked_reasons"]))
        self.assertTrue(checkpoint["ready"], checkpoint["blocked_reasons"])
        self.assertTrue(allowed["ready"], allowed["blocked_reasons"])

    def test_phase_guard_blocks_stale_session_checkpoint_after_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            checkpoint = session_checkpoint.create(repo, state_path, {"phase": "tdd-red"})
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
                require_session_checkpoint=True,
            )

        self.assertTrue(checkpoint["ready"], checkpoint["blocked_reasons"])
        self.assertFalse(result["ready"])
        self.assertTrue(any("stale" in reason.lower() for reason in result["blocked_reasons"]))

    def test_next_blocks_when_claude_hook_is_detected_but_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".claude").mkdir()
            start_args = SimpleNamespace(
                repo=repo,
                feature="Quote",
                request="Return a quote.",
                design_doc=None,
                agent_run_dir=None,
                run_id="run",
                run_date=None,
                force=False,
                status_file=None,
            )
            _code, start_result = e2e_dev_harness.start(start_args)
            next_args = SimpleNamespace(repo=repo, state=Path(start_result["run_state"]), status_file=None)

            code, result = e2e_dev_harness.next_step(next_args)

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertEqual("claude", result["hook_status"]["runtime"])
        self.assertTrue(any("Runtime hook is not ready" in reason for reason in result["blocked_reasons"]))

    def test_discovery_mode_has_no_agent_plan(self) -> None:
        artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        agents = orchestration_plan.agent_plan("discovery", artifacts, [])

        self.assertEqual([], agents)

    def test_single_service_plan_splits_design_test_code_and_review_roles(self) -> None:
        artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        agents = orchestration_plan.agent_plan("single", artifacts, [])
        names = [agent["name"] for agent in agents]
        code = next(agent for agent in agents if agent["name"] == "code-developer")

        self.assertNotIn("single-agent", names)
        self.assertIn("requirements-clarifier", names)
        self.assertIn("use-case-designer", names)
        self.assertIn("test-case-developer", names)
        self.assertIn("code-developer", names)
        self.assertIn("design-reviewer", names)
        self.assertIn("test-reviewer", names)
        self.assertIn("implementation-reviewer", names)
        self.assertIn(artifacts["implementation_plan"], code["outputs"])
        self.assertNotIn(artifacts["design_review"], code["outputs"])
        self.assertNotIn(artifacts["implementation_review"], code["outputs"])

    def test_select_services_discovery_does_not_use_all_candidates(self) -> None:
        facts = {"service_candidates": ["services/order-service", "services/payment-service", "services/catalog-service"]}

        selected, resolved_scope = orchestration_plan.select_services(
            facts,
            requested_services=None,
            requested_paths=None,
            service_scope="auto",
        )

        self.assertEqual([], selected)
        self.assertEqual("discovery", resolved_scope)

    def test_select_services_affected_uses_only_requested_service(self) -> None:
        facts = {"service_candidates": ["services/order-service", "services/payment-service", "services/catalog-service"]}

        selected, resolved_scope = orchestration_plan.select_services(
            facts,
            requested_services=["payment-service"],
            requested_paths=None,
            service_scope="auto",
        )

        self.assertEqual(["services/payment-service"], selected)
        self.assertEqual("affected", resolved_scope)

    def test_design_affected_modules_select_root_maven_modules(self) -> None:
        facts = {"service_candidates": ["jeepay-core", "jeepay-service", "jeepay-payment"]}
        design_text = textwrap.dedent(
            """
            # VNPay

            ## Affected services/modules
            - jeepay-core: constants and params
            - jeepay-service: channel config service
            - jeepay-payment: payment, notice, refund services
            """
        ).strip()

        selected = orchestration_plan.services_from_design(design_text, facts)

        self.assertEqual(["jeepay-core", "jeepay-service", "jeepay-payment"], selected)

    def test_design_affected_services_accepts_table_and_comma_list(self) -> None:
        facts = {"service_candidates": ["services/refund-service", "services/ledger-service", "services/notice-service"]}
        design_text = textwrap.dedent(
            """
            # Refund Reconcile

            ## 影响服务
            | 服务 | 说明 |
            | --- | --- |
            | refund-service | refund state machine |
            | ledger-service | accounting journal |

            ## Affected services
            services: notice-service
            """
        ).strip()

        selected = orchestration_plan.services_from_design(design_text, facts)

        self.assertEqual(
            ["services/refund-service", "services/ledger-service", "services/notice-service"],
            selected,
        )

    def test_orchestration_status_uses_design_modules_for_service_plans(self) -> None:
        facts = {
            "service_candidates": ["jeepay-core", "jeepay-service", "jeepay-payment"],
            "multi_service": True,
            "design_docs_or_media_count": 0,
            "spring_entrypoints": [],
        }
        design_text = textwrap.dedent(
            """
            # VNPay

            ## Goal
            - Add VNPay channel.

            ## Affected services/modules
            - jeepay-core
            - jeepay-service
            - jeepay-payment

            ### jeepay-core
            jeepay-core adds VNPay constants and params.

            ### jeepay-service
            jeepay-service registers the VNPay channel config.

            ### jeepay-payment
            jeepay-payment adds payment and refund services with notify callback handling.

            ## Use Cases
            - Merchant creates a VNPay QR payment.

            ## Acceptance Criteria
            - AC-1 VNPay order can be created.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "vnpay.md"
            design.parent.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")

            result = e2e_dev_harness.orchestration_status(
                repo,
                "auto",
                design,
                run_date="2026-05-23",
                service_scope="auto",
                facts=facts,
            )

        self.assertEqual("affected", result["resolved_service_scope"])
        self.assertEqual(["jeepay-core", "jeepay-service", "jeepay-payment"], result["selected_services"])
        self.assertTrue(result["multi_agent_decision"]["use_multi_agent"])
        self.assertIn("multiple affected services/modules", result["multi_agent_decision"]["criteria"])
        # Only the risky payment module earns its own slice; low-risk core/service collapse into merged-modules.
        self.assertIn("jeepay-payment", result["handoff_artifacts"]["service_plans"])
        self.assertIn("merged-modules", result["handoff_artifacts"]["service_plans"])
        self.assertNotIn("jeepay-service", result["handoff_artifacts"]["service_plans"])
        self.assertIn("code-developer-jeepay-payment", [agent["name"] for agent in result["agents"]])
        code_agent = next(agent for agent in result["agents"] if agent["name"] == "code-developer-jeepay-payment")
        service_paths = result["handoff_artifacts"]["service_plans"]["jeepay-payment"]
        self.assertIn(service_paths["service_design"], code_agent["inputs"])
        self.assertIn(service_paths["test_impact_plan"], code_agent["inputs"])
        self.assertEqual("e2e-dev-harness.agent-schedule.v1", result["agent_schedule"]["schema"])
        self.assertTrue(any(task["parallel_group"] == "service:jeepay-payment" for task in result["agent_schedule"]["tasks"]))

    def test_plan_archive_creates_handoffs_for_design_affected_root_modules(self) -> None:
        design_text = textwrap.dedent(
            """
            # VNPay

            ## Goal
            - Add VNPay channel.

            ## Affected services/modules
            - jeepay-core
            - jeepay-service
            - jeepay-payment

            ### jeepay-core
            jeepay-core adds VNPay constants and params.

            ### jeepay-service
            jeepay-service registers the VNPay channel config.

            ### jeepay-payment
            jeepay-payment adds payment and refund services with notify callback handling.

            ## Use Cases
            - Merchant creates a VNPay QR payment.

            ## Acceptance Criteria
            - AC-1 VNPay order can be created.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            repo.joinpath("pom.xml").write_text(
                textwrap.dedent(
                    """
                    <project xmlns="http://maven.apache.org/POM/4.0.0">
                      <modelVersion>4.0.0</modelVersion>
                      <modules>
                        <module>jeepay-core</module>
                        <module>jeepay-service</module>
                        <module>jeepay-payment</module>
                      </modules>
                    </project>
                    """
                ).strip(),
                encoding="utf-8",
            )
            for module in ("jeepay-core", "jeepay-service", "jeepay-payment"):
                module_dir = repo / module
                (module_dir / "src" / "main" / "java").mkdir(parents=True)
                (module_dir / "pom.xml").write_text("<project />", encoding="utf-8")
            design = repo / "docs" / "design" / "vnpay.md"
            design.parent.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")
            args = SimpleNamespace(
                repo=repo,
                mode="auto",
                design_doc=design,
                agent_run_dir=None,
                run_date="2026-05-23",
                service_scope="auto",
                service=None,
                path=None,
                dependency_report=None,
                create_archive=True,
                write_exec_plan=None,
                status_file=None,
            )

            code, result = e2e_dev_harness.plan(args)

            self.assertEqual(0, code)
            self.assertEqual(["jeepay-core", "jeepay-payment", "jeepay-service"], sorted(result["selected_services"]))
            self.assertTrue((repo / result["handoff_artifacts"]["design_review_request"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["test_review_request"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["implementation_review_request"]).exists())
            self.assertFalse((repo / result["handoff_artifacts"]["design_review"]).exists())
            self.assertFalse((repo / result["handoff_artifacts"]["test_review"]).exists())
            self.assertFalse((repo / result["handoff_artifacts"]["implementation_review"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["requirements_archive"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["impact_summary"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["impact_evidence"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["artifact_registry"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["agent_schedule"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["run_state"]).exists())
            registry = json.loads((repo / result["handoff_artifacts"]["artifact_registry"]).read_text(encoding="utf-8"))
            schedule = json.loads((repo / result["handoff_artifacts"]["agent_schedule"]).read_text(encoding="utf-8"))
            state = json.loads((repo / result["handoff_artifacts"]["run_state"]).read_text(encoding="utf-8"))
            self.assertEqual("e2e-dev-harness.artifact-registry.v1", registry["schema"])
            self.assertEqual("e2e-dev-harness.agent-schedule.v1", schedule["schema"])
            self.assertEqual("e2e-dev-harness.run-state.v1", state["schema"])
            self.assertEqual("SERVICE_DESIGN_REQUIRED", state["lifecycle"])
            self.assertEqual("planned", state["gates"]["service_design"])
            self.assertEqual(result["handoff_artifacts"]["artifact_registry"], state["artifact_registry"])
            # Slice goes through run-state services; the merged low-risk modules go through shared edit scopes.
            self.assertEqual(["jeepay-payment"], state["services"])
            self.assertEqual(["jeepay-core/", "jeepay-service/"], state["shared_edit_scopes"])
            self.assertTrue(any(item["type"] == "design_doc" for item in registry["artifacts"]))
            archive_text = (repo / result["handoff_artifacts"]["requirements_archive"]).read_text(encoding="utf-8")
            self.assertIn("Final Clarified Requirement", archive_text)
            self.assertIn("Acceptance Criteria Status", archive_text)
            impact_text = (repo / result["handoff_artifacts"]["impact_summary"]).read_text(encoding="utf-8")
            self.assertIn("Raw Evidence", impact_text)
            self.assertIn("affected callers/consumers", impact_text)
            # Two slices on disk: one real (payment) plus one merged slice covering core + service. Every
            # slice still gets a service-design and forced R2/R3 review requests so coverage is preserved.
            service_plans = result["handoff_artifacts"]["service_plans"]
            self.assertEqual(["jeepay-payment", "merged-modules"], list(service_plans))
            for slice_id in ("jeepay-payment", "merged-modules"):
                paths = service_plans[slice_id]
                self.assertTrue((repo / paths["service_design"]).exists())
                self.assertTrue((repo / paths["service_plan"]).exists())
                self.assertTrue((repo / paths["code_agent"]).exists())
                self.assertTrue((repo / paths["implementation_manifest"]).exists())
                self.assertTrue((repo / paths["test_impact_plan"]).exists())
                self.assertTrue((repo / paths["test_review_request"]).exists())
                self.assertTrue((repo / paths["implementation_review_request"]).exists())
                self.assertFalse((repo / paths["test_review"]).exists())
                self.assertFalse((repo / paths["implementation_review"]).exists())
            merged_design = (repo / service_plans["merged-modules"]["service_design"]).read_text(encoding="utf-8")
            self.assertIn("mvn -pl jeepay-core -am test", merged_design)
            self.assertIn("mvn -pl jeepay-service -am test", merged_design)
            self.assertTrue((repo / result["handoff_artifacts"]["service_designs_dir"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["verification_evidence"]).exists())

    def test_unmatched_requested_services_are_reported(self) -> None:
        facts = {"service_candidates": ["services/order-service"]}

        unmatched = orchestration_plan.unmatched_requested_services(facts, ["missing-service"])

        self.assertEqual(["missing-service"], unmatched)

    def test_select_services_affected_uses_only_path_service(self) -> None:
        facts = {"service_candidates": ["services/order-service", "services/payment-service", "services/catalog-service"]}

        selected, resolved_scope = orchestration_plan.select_services(
            facts,
            requested_services=None,
            requested_paths=["services/order-service/src/main/java/Order.java"],
            service_scope="auto",
        )

        self.assertEqual(["services/order-service"], selected)
        self.assertEqual("affected", resolved_scope)

    def test_select_services_all_keeps_full_service_candidates(self) -> None:
        facts = {"service_candidates": ["services/order-service", "services/payment-service"]}

        selected, resolved_scope = orchestration_plan.select_services(
            facts,
            requested_services=None,
            requested_paths=None,
            service_scope="all",
        )

        self.assertEqual(["services/order-service", "services/payment-service"], selected)
        self.assertEqual("all", resolved_scope)

    def test_mode_facts_discovery_do_not_treat_all_candidates_as_in_scope(self) -> None:
        facts = {
            "service_candidates": ["services/order-service", "services/payment-service"],
            "multi_service": True,
        }

        scoped = orchestration_plan.mode_facts_for_service_scope(facts, [], "discovery")
        selected, reasons = orchestration_plan.choose_mode("auto", scoped, "", False)

        self.assertEqual("single-review", selected)
        self.assertEqual([], scoped["service_candidates"])
        self.assertFalse(scoped["multi_service"])

    def test_artifacts_default_to_agent_run_archive(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual("docs/agent-runs/2026-05-23-checkout", result["agent_run_dir"])
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/handoffs/01-requirements-clarifier.md",
            result["requirements"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/red-test.txt",
            result["red_test_evidence"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/coverage-matrix.md",
            result["coverage_matrix"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/impact-summary.md",
            result["impact_summary"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/impact-analysis.json",
            result["impact_evidence"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/requirements-archive.md",
            result["requirements_archive"],
        )

    def test_artifacts_allow_explicit_agent_run_dir(self) -> None:
        result = orchestration_plan.artifacts("checkout", agent_run_dir="docs/agent-runs/custom")

        self.assertEqual("docs/agent-runs/custom", result["agent_run_dir"])
        self.assertEqual("docs/agent-runs/custom/exec-plan.md", result["exec_plan"])

    def test_artifacts_include_service_level_plans(self) -> None:
        result = orchestration_plan.artifacts(
            "checkout",
            run_date="2026-05-23",
            services=["services/order-service", "services/payment-service"],
        )

        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-designs/order-service.md",
            result["service_plans"]["services/order-service"]["service_design"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/order-service/implementation-plan.md",
            result["service_plans"]["services/order-service"]["service_plan"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/payment-service/code-agent.md",
            result["service_plans"]["services/payment-service"]["code_agent"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/payment-service/test-impact-plan.json",
            result["service_plans"]["services/payment-service"]["test_impact_plan"],
        )

    def test_plan_artifacts_include_rework_paths(self) -> None:
        result = orchestration_plan.artifacts(
            "checkout",
            run_date="2026-05-23",
            services=["services/order-service"],
        )

        self.assertEqual("docs/agent-runs/2026-05-23-checkout/rework", result["rework_dir"])
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/order-service",
            result["service_plans"]["services/order-service"]["rework_dir"],
        )

    def test_plan_artifacts_include_semantic_review_paths(self) -> None:
        result = orchestration_plan.artifacts(
            "checkout",
            run_date="2026-05-23",
            services=["services/order-service"],
        )

        self.assertEqual("docs/agent-runs/2026-05-23-checkout/reviews", result["reviews_dir"])
        self.assertEqual("docs/agent-runs/2026-05-23-checkout/review-requests", result["review_requests_dir"])
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/review-requests/R1-design-review-request.md",
            result["design_review_request"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/reviews/R1-design-review.md",
            result["design_review"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/order-service/review-requests/R3-implementation-review-request.md",
            result["service_plans"]["services/order-service"]["implementation_review_request"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/order-service/reviews/R3-implementation-review.md",
            result["service_plans"]["services/order-service"]["implementation_review"],
        )

    def test_plan_artifacts_include_dependency_report_path(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/cross-service-dependencies.json",
            result["dependency_report"],
        )

    def test_plan_artifacts_include_contract_paths(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual("docs/agent-runs/2026-05-23-checkout/contracts", result["contracts_dir"])
        self.assertEqual("docs/agent-runs/2026-05-23-checkout/contracts/<contract-id>.md", result["contract_pattern"])

    def test_plan_artifacts_include_run_summary_paths(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual("docs/agent-runs/2026-05-23-checkout/run-summary.json", result["run_summary"])
        self.assertEqual("docs/agent-runs/2026-05-23-checkout/run-summary.md", result["run_summary_md"])
        self.assertEqual("docs/agent-runs/2026-05-23-checkout/execution-trace.json", result["execution_trace"])

    def test_plan_artifacts_include_test_impact_and_context_pack_paths(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/test-impact-plan.json",
            result["test_impact_plan"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/context-packs/<agent-or-task>.json",
            result["context_pack_pattern"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-designs",
            result["service_designs_dir"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-designs/<service>.md",
            result["service_design_pattern"],
        )

    def test_plan_artifacts_include_implementation_manifest_path(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/implementation-manifest.md",
            result["implementation_manifest"],
        )

    def test_context_pack_builds_request_scoped_task_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            requirements = repo / "docs" / "agent-runs" / "run" / "handoffs" / "01-requirements-clarifier.md"
            requirements.parent.mkdir(parents=True)
            requirements.write_text("Requirement summary\n", encoding="utf-8")
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "service": "services/order-service",
                                "inputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/implementation-manifest.md"],
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = context_pack.build_pack(repo, schedule, service="services/order-service", max_files=2, max_chars=1000)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("request-scoped; no inherited developer chat context", result["context_policy"])
        self.assertEqual(1, result["budget"]["input_files"])

    def test_context_pack_blocks_outputs_outside_dir_graph_role_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".e2e").mkdir()
            (repo / ".e2e" / "dir-graph.yaml").write_text(
                "schema: e2e-dev-harness.dir-graph.v1\n"
                "skill_contracts:\n"
                "  - role: requirements-clarifier\n"
                "    write_scope: docs/agent-runs/<run>/handoffs\n",
                encoding="utf-8",
            )
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule.parent.mkdir(parents=True)
            schedule.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "inputs": [],
                                "outputs": ["docs/agent-runs/run/implementation-plan.md"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = context_pack.build_pack(repo, schedule, agent="requirements-clarifier")

        self.assertFalse(result["ready"])
        self.assertTrue(any("dir graph role contract" in reason for reason in result["blocked_reasons"]))

    def test_context_pack_blocks_budget_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            requirements = repo / "docs" / "agent-runs" / "run" / "handoffs" / "01-requirements-clarifier.md"
            requirements.parent.mkdir(parents=True)
            requirements.write_text("x" * 50, encoding="utf-8")
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "code-developer",
                                "phase": "implement",
                                "inputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                                "outputs": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = context_pack.build_pack(repo, schedule, agent="code-developer", max_files=2, max_chars=10)

        self.assertFalse(result["ready"])
        self.assertTrue(any("above max_chars" in reason for reason in result["blocked_reasons"]))

    def test_context_pack_surfaces_missing_input_files_without_treating_them_as_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text("# Feature\n", encoding="utf-8")
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule.parent.mkdir(parents=True)
            schedule.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "inputs": [
                                    "user request",
                                    "docs/design/feature.md",
                                    "docs/agent-runs/run/evidence/cross-service-dependencies.json",
                                ],
                                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = context_pack.build_pack(repo, schedule, agent="requirements-clarifier")

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(
            [{"path": "docs/agent-runs/run/evidence/cross-service-dependencies.json", "reason": "missing"}],
            result["missing_input_files"],
        )
        self.assertEqual("docs/design/feature.md", result["resolved_input_files"][0]["path"])
        self.assertGreater(result["resolved_input_files"][0]["bytes"], 0)

    def test_service_design_gate_requires_global_ac_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "checkout.md"
            service_dir = repo / "docs" / "agent-runs" / "run" / "service-designs"
            service_dir.mkdir(parents=True)
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    - AC-2 Payment is reserved.
                    """
                ).strip(),
                encoding="utf-8",
            )
            (service_dir / "order-service.md").write_text(
                textwrap.dedent(
                    """
                    # Service Design Slice: services/order-service

                    ## Service Scope
                    - Service/module: services/order-service
                    - Allowed edit scope:
                      - services/order-service/

                    ## Global Intent Summary
                    - Create checkout order.

                    ## Mapped Acceptance Criteria
                    | AC | global requirement | service responsibility | local tests |
                    | --- | --- | --- | --- |
                    | AC-1 | Order is created | Persist order | OrderServiceTest |

                    ## Runtime Path
                    - Controller -> OrderService -> Repository

                    ## Service-local TDD Plan
                    - First red test: OrderServiceTest
                    - Expected failure: missing order persistence
                    - Required Maven command: mvn -pl services/order-service -am test

                    ## Dependency Boundary
                    - Independent service change: yes
                    - HTTP/API dependencies: None
                    - MQ/DMQ/Kafka dependencies: None

                    ## Test Impact
                    - mvn -pl services/order-service -am test
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = service_design_gate.validate(repo, design, service_dir)

        self.assertFalse(result["ready"])
        self.assertTrue(any("AC-2" in reason for reason in result["blocked_reasons"]))

    def test_service_design_gate_allows_complete_service_slices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "checkout.md"
            service_dir = repo / "docs" / "agent-runs" / "run" / "service-designs"
            service_dir.mkdir(parents=True)
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    - AC-2 Payment is reserved.
                    """
                ).strip(),
                encoding="utf-8",
            )
            for service, ac_id, test_name in (
                ("order-service", "AC-1", "OrderServiceTest"),
                ("payment-service", "AC-2", "PaymentServiceTest"),
            ):
                (service_dir / f"{service}.md").write_text(
                    textwrap.dedent(
                        f"""
                        # Service Design Slice: services/{service}

                        ## Service Scope
                        - Service/module: services/{service}
                        - Allowed edit scope:
                          - services/{service}/

                        ## Global Intent Summary
                        - Checkout service responsibility.

                        ## Mapped Acceptance Criteria
                        | AC | global requirement | service responsibility | local tests |
                        | --- | --- | --- | --- |
                        | {ac_id} | Requirement | Local responsibility | {test_name} |

                        ## Runtime Path
                        - Controller -> Service -> Repository

                        ## Service-local TDD Plan
                        - First red test: {test_name}
                        - Expected failure: missing {service} behavior
                        - Required Maven command: mvn -pl services/{service} -am test

                        ## Dependency Boundary
                        - Independent service change: yes
                        - HTTP/API dependencies: None
                        - MQ/DMQ/Kafka dependencies: None

                        ## Test Impact
                        - mvn -pl services/{service} -am test
                        """
                    ).strip(),
                    encoding="utf-8",
                )

            result = service_design_gate.validate(repo, design, service_dir)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["AC-1", "AC-2"], result["mapped_acceptance_ids"])

    def test_service_design_command_transitions_multi_run_to_planned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "checkout.md"
            service_dir = repo / "docs" / "agent-runs" / "run" / "service-designs"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            design.parent.mkdir(parents=True)
            service_dir.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    - AC-2 Payment is reserved.
                    """
                ).strip(),
                encoding="utf-8",
            )
            for service, ac_id, test_name in (
                ("order-service", "AC-1", "OrderServiceTest"),
                ("payment-service", "AC-2", "PaymentServiceTest"),
            ):
                (service_dir / f"{service}.md").write_text(
                    textwrap.dedent(
                        f"""
                        # Service Design Slice: services/{service}

                        ## Service Scope
                        - Service/module: services/{service}
                        - Allowed edit scope:
                          - services/{service}/

                        ## Global Intent Summary
                        - Checkout service responsibility.

                        ## Mapped Acceptance Criteria
                        | AC | global requirement | service responsibility | local tests |
                        | --- | --- | --- | --- |
                        | {ac_id} | Requirement | Local responsibility | {test_name} |

                        ## Runtime Path
                        - Controller -> Service -> Repository

                        ## Service-local TDD Plan
                        - First red test: {test_name}
                        - Expected failure: missing {service} behavior
                        - Required Maven command: mvn -pl services/{service} -am test

                        ## Dependency Boundary
                        - Independent service change: yes
                        - HTTP/API dependencies: None
                        - MQ/DMQ/Kafka dependencies: None

                        ## Test Impact
                        - mvn -pl services/{service} -am test
                        """
                    ).strip(),
                    encoding="utf-8",
                )
            state = run_state.build_state(
                "run",
                "multi",
                ["services/order-service", "services/payment-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "SERVICE_DESIGN_REQUIRED",
            )
            run_state.write_state(repo, state_path, state)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            role_template = Path("docs/agent-runs/run/agent-roles/use-case-designer.md")
            write_role_template(repo, role_template)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "service-designer-order-service",
                                "phase": "design",
                                "role_group": "design",
                                "service": "services/order-service",
                                "outputs": ["docs/agent-runs/run/service-designs/order-service.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                            {
                                "id": "T02",
                                "agent": "service-designer-payment-service",
                                "phase": "design",
                                "role_group": "design",
                                "service": "services/payment-service",
                                "outputs": ["docs/agent-runs/run/service-designs/payment-service.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            first = complete_dispatched_task(
                repo,
                schedule_path,
                state_path,
                "T01",
                "service-designer-order-service",
                ["docs/agent-runs/run/service-designs/order-service.md"],
            )
            second = complete_dispatched_task(
                repo,
                schedule_path,
                state_path,
                "T02",
                "service-designer-payment-service",
                ["docs/agent-runs/run/service-designs/payment-service.md"],
            )

            code, result = e2e_dev_harness.service_design(
                SimpleNamespace(
                    repo=repo,
                    global_design=design,
                    service_design_dir=service_dir,
                    service_design=None,
                    run_state=state_path,
                    status_file=None,
                )
            )
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(first["ready"], first["blocked_reasons"])
        self.assertTrue(second["ready"], second["blocked_reasons"])
        self.assertEqual(0, code)
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("PLANNED", updated["lifecycle"])
        self.assertEqual("passed", updated["gates"]["service_design"])

    def test_multi_implementation_gate_blocks_before_service_design_state_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifacts = orchestration_plan.artifacts(
                "checkout",
                agent_run_dir="docs/agent-runs/run",
                services=["services/order-service", "services/payment-service"],
            )
            design = repo / "docs" / "design" / "checkout.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Restated Intent
                    Build checkout.

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    - AC-2 Payment is reserved.

                    ## Open Questions
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            artifacts["design_doc"] = "docs/design/checkout.md"
            e2e_dev_harness.create_handoff_files(repo, artifacts)
            schedule = orchestration_plan.agent_schedule(
                "multi",
                ["services/order-service", "services/payment-service"],
                orchestration_plan.agent_plan("multi", artifacts, ["services/order-service", "services/payment-service"]),
            )
            (repo / artifacts["agent_schedule"]).write_text(json.dumps(schedule, indent=2), encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "docs/agent-runs/run",
                artifacts,
                "multi",
                ["services/order-service", "services/payment-service"],
            )
            artifact_registry.write_registry(repo, repo / artifacts["artifact_registry"], registry)
            state_path = repo / artifacts["run_state"]
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                ["services/order-service", "services/payment-service"],
                artifacts["artifact_registry"],
                "SERVICE_DESIGN_REQUIRED",
            )
            run_state.write_state(repo, state_path, state)

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(
                    repo=repo,
                    phase="implementation",
                    design_doc=Path("docs/design/checkout.md"),
                    run_state=Path(artifacts["run_state"]),
                )
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("service-design gate transitions" in reason for reason in result["blocked_reasons"]))

    def test_multi_implementation_gate_waits_for_tdd_and_r2_not_code_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            services = ["services/order-service", "services/payment-service"]
            artifacts = orchestration_plan.artifacts("checkout", agent_run_dir="docs/agent-runs/run", services=services)
            artifacts["design_doc"] = "docs/design/checkout.md"
            design = repo / artifacts["design_doc"]
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Restated Intent
                    Build checkout.

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    - AC-2 Payment is reserved.

                    ## Open Questions
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            e2e_dev_harness.create_handoff_files(repo, artifacts)
            for service, ac_id, test_name in (
                ("order-service", "AC-1", "OrderServiceTest"),
                ("payment-service", "AC-2", "PaymentServiceTest"),
            ):
                service_design = repo / "docs" / "agent-runs" / "run" / "service-designs" / f"{service}.md"
                service_design.write_text(
                    textwrap.dedent(
                        f"""
                        # Service Design Slice: services/{service}

                        ## Service Scope
                        - Service/module: services/{service}
                        - Allowed edit scope:
                          - services/{service}/

                        ## Global Intent Summary
                        - Checkout service responsibility.

                        ## Mapped Acceptance Criteria
                        | AC | global requirement | service responsibility | local tests |
                        | --- | --- | --- | --- |
                        | {ac_id} | Requirement | Local responsibility | {test_name} |

                        ## Runtime Path
                        - Controller -> Service -> Repository

                        ## Service-local TDD Plan
                        - First red test: {test_name}
                        - Expected failure: missing {service} behavior
                        - Required Maven command: mvn -pl services/{service} -am test

                        ## Dependency Boundary
                        - Independent service change: yes
                        - HTTP/API dependencies: None
                        - MQ/DMQ/Kafka dependencies: None

                        ## Test Impact
                        - mvn -pl services/{service} -am test
                        """
                    ).strip(),
                    encoding="utf-8",
                )
            agents = orchestration_plan.agent_plan("multi", artifacts, services)
            schedule = orchestration_plan.agent_schedule("multi", services, agents)
            (repo / artifacts["agent_schedule"]).write_text(json.dumps(schedule, indent=2), encoding="utf-8")
            registry = artifact_registry.build_registry(repo, "docs/agent-runs/run", artifacts, "multi", services)
            artifact_registry.write_registry(repo, repo / artifacts["artifact_registry"], registry)
            state_path = repo / artifacts["run_state"]
            state = run_state.build_state("docs/agent-runs/run", "multi", services, artifacts["artifact_registry"], "PLANNED")
            state["gates"]["service_design"] = "passed"
            run_state.write_state(repo, state_path, state)

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(
                    repo=repo,
                    phase="implementation",
                    design_doc=Path(artifacts["design_doc"]),
                    run_state=Path(artifacts["run_state"]),
                )
            )

        self.assertFalse(result["ready"])
        self.assertFalse(any("must be claimed" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("tdd-red" in reason and "r2-review" in reason for reason in result["blocked_reasons"]))

    def test_service_plan_archive_contains_microservice_scoped_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifacts = orchestration_plan.artifacts(
                "checkout",
                run_date="2026-05-23",
                services=["services/order-service"],
            )

            e2e_dev_harness.create_handoff_files(repo, artifacts)

            service_plan = repo / artifacts["service_plans"]["services/order-service"]["service_plan"]
            service_design = repo / artifacts["service_plans"]["services/order-service"]["service_design"]
            text = service_plan.read_text(encoding="utf-8")
            design_text = service_design.read_text(encoding="utf-8")
            request_text = (repo / artifacts["implementation_review_request"]).read_text(encoding="utf-8")

        self.assertIn("# Service Design Slice: services/order-service", design_text)
        self.assertIn("## Mapped Acceptance Criteria", design_text)
        self.assertIn("## Dependency Boundary", design_text)
        self.assertIn("# Service Implementation Plan: services/order-service", text)
        self.assertIn("## Agent Assignment", text)
        self.assertIn("## Modification Points", text)
        self.assertIn("## Change Logic", text)
        self.assertIn("## Service-local TDD Plan", text)
        self.assertIn("## Implementation Manifest", text)
        self.assertIn("## Cross-service Contracts", text)
        self.assertIn("Reviewer Agent:", request_text)
        self.assertIn("Forbidden:", request_text)
        self.assertIn("Output:", request_text)

    def test_artifact_registry_detects_stale_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("initial\n", encoding="utf-8")
            artifacts = {"exec_plan": "docs/agent-runs/run/exec-plan.md"}
            registry = artifact_registry.build_registry(repo, "run", artifacts, "single", [])
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            artifact.write_text("changed\n", encoding="utf-8")

            result = artifact_registry.validate_registry(repo, registry_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("stale" in reason.lower() for reason in result["blocked_reasons"]))

    def test_artifact_registry_refresh_updates_status_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"exec_plan": "docs/agent-runs/run/exec-plan.md"},
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            artifact.write_text("plan\n", encoding="utf-8")

            result = artifact_registry.refresh_registry(repo, registry_path)
            refreshed = json.loads(registry_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["global:exec_plan"], result["changed"])
        self.assertEqual("present", refreshed["artifacts"][0]["status"])
        self.assertTrue(refreshed["artifacts"][0]["sha256"])

    def test_artifact_registry_marks_recomputable_completion_derivatives_without_strict_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            exec_plan = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            exec_plan.parent.mkdir(parents=True)
            exec_plan.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {
                    "exec_plan": "docs/agent-runs/run/exec-plan.md",
                    "knowledge_graph_status": "docs/agent-runs/run/evidence/kg-status.json",
                    "phase_coverage": "docs/agent-runs/run/evidence/phase-coverage.json",
                    "strict_guard_result": "docs/agent-runs/run/evidence/strict-guard.json",
                },
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            artifact_registry.write_registry(repo, registry_path, registry)

            result = artifact_registry.validate_registry(repo, registry_path, strict=True)
            by_type = {item["type"]: item for item in registry["artifacts"]}

        self.assertFalse(result["ready"], result["blocked_reasons"])
        self.assertTrue(by_type["exec_plan"]["required_by_completion"])
        self.assertFalse(by_type["knowledge_graph_status"]["required_by_completion"])
        self.assertTrue(by_type["knowledge_graph_status"]["derived_by_completion"])
        self.assertIn("regenerate_command", by_type["knowledge_graph_status"])
        self.assertTrue(by_type["phase_coverage"]["required_by_completion"])
        self.assertFalse(by_type["phase_coverage"]["derived_by_completion"])
        self.assertTrue(by_type["strict_guard_result"]["required_by_completion"])
        self.assertFalse(by_type["strict_guard_result"]["derived_by_completion"])
        self.assertTrue(
            any("phase-coverage.json" in reason for reason in result["blocked_reasons"]),
            result["blocked_reasons"],
        )
        self.assertTrue(
            any("strict-guard.json" in reason for reason in result["blocked_reasons"]),
            result["blocked_reasons"],
        )

    def test_artifact_registry_blocks_paths_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.artifact-registry.v1",
                        "artifacts": [
                            {
                                "type": "exec_plan",
                                "path": "../outside.md",
                                "kind": "file",
                                "required_by_completion": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = artifact_registry.validate_registry(repo, registry_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("outside repository" in reason for reason in result["blocked_reasons"]))

    def test_artifact_registry_strict_blocks_missing_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"exec_plan": "docs/agent-runs/run/exec-plan.md"},
                "single",
                [],
            )
            registry["artifacts"][0]["sha256"] = ""
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            artifact_registry.write_registry(repo, registry_path, registry)

            result = artifact_registry.validate_registry(repo, registry_path, strict=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("missing" in reason.lower() for reason in result["blocked_reasons"]))

    def test_run_state_validates_artifact_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"exec_plan": "docs/agent-runs/run/exec-plan.md"},
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)

            result = run_state.validate_state(repo, state_path)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("PLANNED", result["lifecycle"])

    def test_run_state_transition_records_history_and_gate_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-gate.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            evidence.parent.mkdir(parents=True)
            red.write_text("expected failure\n", encoding="utf-8")
            evidence.write_text(json.dumps(implementation_gate_payload(red)), encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)

            result = run_state.transition_state(
                repo,
                state_path,
                "IMPLEMENTED",
                gate="implementation",
                gate_status="passed",
                evidence=evidence,
            )
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            lock_exists = (state_path.parent / ".phase-lock").exists()

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("IMPLEMENTED", updated["lifecycle"])
        self.assertEqual("passed", updated["gates"]["implementation"])
        self.assertEqual("PLANNED", updated["history"][0]["from"])
        self.assertEqual("IMPLEMENTED", updated["history"][0]["to"])
        self.assertTrue(lock_exists)

    def test_run_state_transition_blocks_regression_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "VERIFIED")
            run_state.write_state(repo, state_path, state)

            result = run_state.transition_state(repo, state_path, "PLANNED")

        self.assertFalse(result["ready"])
        self.assertTrue(any("regression" in reason.lower() for reason in result["blocked_reasons"]))

    def test_run_state_blocks_manual_implemented_transition_without_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = run_state.transition_state(repo, state_path, "IMPLEMENTED")

        self.assertFalse(result["ready"])
        self.assertTrue(any("gate=implementation" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("requires implementation gate evidence" in reason for reason in result["blocked_reasons"]))

    def test_run_state_blocks_implemented_transition_with_non_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("expected failure\n", encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = run_state.transition_state(
                repo,
                state_path,
                "IMPLEMENTED",
                gate="implementation",
                gate_status="passed",
                evidence=evidence,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("valid JSON" in reason or "implementation gate" in reason for reason in result["blocked_reasons"]))

    def test_run_state_blocks_forged_ready_only_implementation_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-gate.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(json.dumps({"phase": "implementation", "ready": True}), encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = run_state.transition_state(
                repo,
                state_path,
                "IMPLEMENTED",
                gate="implementation",
                gate_status="passed",
                evidence=evidence,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("TDD red" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("semantic reviews" in reason for reason in result["blocked_reasons"]))

    def test_multi_phase_guard_requires_claimed_service_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state = run_state.build_state(
                "run",
                "multi",
                ["services/order-service", "services/payment-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            state["gates"]["service_design"] = "passed"
            write_implemented_state(repo, state_path, state)
            schedule = {
                "schema": "e2e-dev-harness.agent-schedule.v1",
                "selected_mode": "multi",
                "services": ["services/order-service", "services/payment-service"],
                "tasks": [
                    {
                        "id": "T01",
                        "agent": "code-developer-order-service",
                        "phase": "implement",
                        "service": "services/order-service",
                        "status": "planned",
                    }
                ],
            }
            schedule_path.parent.mkdir(parents=True, exist_ok=True)
            schedule_path.write_text(json.dumps(schedule, indent=2), encoding="utf-8")

            blocked = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/order-service/src/main/java/OrderService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )
            claim = agent_scheduler.claim(repo, schedule_path, "T01", "agent-order", state_path)
            claimed_state = json.loads(state_path.read_text(encoding="utf-8"))
            claimed_state["dispatches"] = {
                "T01": {
                    "status": "worker_running",
                    "current_task_id": "T01",
                    "current_agent": "code-developer-order-service",
                    "worker_handle": "code-worker-order",
                }
            }
            claimed_state["dispatch"] = claimed_state["dispatches"]["T01"]
            run_state.write_state(repo, state_path, claimed_state)
            allowed = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/order-service/src/main/java/OrderService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )
            cross_service = phase_guard.validate_action(
                repo,
                "Edit",
                [
                    Path("services/order-service/src/main/java/OrderService.java"),
                    Path("services/payment-service/src/main/java/PaymentService.java"),
                ],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(blocked["ready"])
        self.assertTrue(any("no claimed code-developer task" in reason for reason in blocked["blocked_reasons"]))
        self.assertTrue(claim["ready"], claim["blocked_reasons"])
        self.assertTrue(allowed["ready"], allowed["blocked_reasons"])
        self.assertFalse(cross_service["ready"])
        self.assertTrue(any("only one service" in reason for reason in cross_service["blocked_reasons"]))

    def test_multi_phase_guard_blocks_unscoped_shared_runtime_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            state["owners"]["services/order-service"] = {
                "task_id": "T01",
                "agent": "agent-order",
                "status": "claimed",
            }
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("pom.xml")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("outside claimed services" in reason for reason in result["blocked_reasons"]))

    def test_multi_phase_guard_allows_explicit_shared_edit_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            state["owners"]["services/order-service"] = {
                "task_id": "T01",
                "agent": "agent-order",
                "status": "claimed",
            }
            state["shared_edit_scopes"] = ["shared-kernel"]
            state["dispatches"] = {
                "T01": {
                    "status": "worker_running",
                    "current_task_id": "T01",
                    "current_agent": "code-developer-order-service",
                    "worker_handle": "code-worker-order",
                }
            }
            state["dispatch"] = state["dispatches"]["T01"]
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("shared-kernel/src/main/java/com/example/Money.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_agent_task_complete_requires_existing_declared_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "unit-test-evidence.txt"
            other = repo / "docs" / "agent-runs" / "run" / "evidence" / "other.txt"
            evidence.parent.mkdir(parents=True)
            other.parent.mkdir(parents=True)
            evidence.write_text("passed\n", encoding="utf-8")
            other.write_text("passed\n", encoding="utf-8")
            schedule = {
                "schema": "e2e-dev-harness.agent-schedule.v1",
                "selected_mode": "multi",
                "services": ["services/order-service"],
                "tasks": [
                    {
                        "id": "T01",
                        "agent": "code-developer-order-service",
                        "phase": "implement",
                        "service": "services/order-service",
                        "status": "claimed",
                        "owner": "agent-order",
                        "outputs": [
                            "docs/agent-runs/run/service-plans/order-service/unit-test-evidence.txt"
                        ],
                    }
                ],
            }
            schedule_path.parent.mkdir(parents=True, exist_ok=True)
            schedule_path.write_text(json.dumps(schedule, indent=2), encoding="utf-8")

            missing = agent_scheduler.complete(repo, schedule_path, "T01", "agent-order", evidence=["missing.txt"])
            wrong = agent_scheduler.complete(repo, schedule_path, "T01", "agent-order", evidence=[str(other.relative_to(repo))])
            ok = agent_scheduler.complete(repo, schedule_path, "T01", "agent-order", evidence=[str(evidence.relative_to(repo))])

        self.assertFalse(missing["ready"])
        self.assertTrue(any("missing" in reason for reason in missing["blocked_reasons"]))
        self.assertFalse(wrong["ready"])
        self.assertTrue(any("task outputs" in reason for reason in wrong["blocked_reasons"]))
        self.assertTrue(ok["ready"], ok["blocked_reasons"])
        self.assertEqual(["docs/agent-runs/run/service-plans/order-service/unit-test-evidence.txt"], ok["task"]["evidence"])

    def test_agent_task_claim_blocks_unfinished_dependency_phases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            schedule_path.parent.mkdir(parents=True)
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            state["gates"]["service_design"] = "passed"
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {"id": "T01", "phase": "tdd-red", "status": "completed"},
                            {"id": "T02", "phase": "r2-review", "status": "planned"},
                            {
                                "id": "T03",
                                "phase": "implement",
                                "service": "services/order-service",
                                "status": "planned",
                                "depends_on_phases": ["tdd-red", "r2-review"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = agent_scheduler.claim(repo, schedule_path, "T03", "agent-order", state_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("r2-review" in reason for reason in result["blocked_reasons"]))

    def test_agent_task_complete_requires_service_artifacts_and_passed_unit_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            base = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service"
            base.mkdir(parents=True)
            unit = base / "unit-test-evidence.json"
            manifest = base / "implementation-manifest.md"
            coverage = base / "coverage-matrix.md"
            unit.write_text(json.dumps([{"command": "mvn -pl order-service test", "exit_code": 0}]), encoding="utf-8")
            manifest.write_text(
                "| id | module | artifact | artifact_type | source | required | tests | status | evidence |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| IM-1 | order-service | OrderService | service | AC-1 | yes | OrderServiceTest | verified | unit |\n",
                encoding="utf-8",
            )
            coverage.write_text(
                "| id | acceptance | use_case | service | tests | code_refs | business_review | status |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| AC-1 | ok | UC-1 | order-service | OrderServiceTest | OrderService | reviewed | verified |\n",
                encoding="utf-8",
            )
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "phase": "implement",
                                "service": "services/order-service",
                                "status": "claimed",
                                "owner": "agent-order",
                                "outputs": [
                                    "docs/agent-runs/run/service-plans/order-service/unit-test-evidence.json",
                                    "docs/agent-runs/run/service-plans/order-service/implementation-manifest.md",
                                    "docs/agent-runs/run/service-plans/order-service/coverage-matrix.md",
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = agent_scheduler.complete(
                repo,
                schedule_path,
                "T01",
                "agent-order",
                evidence=[
                    "docs/agent-runs/run/service-plans/order-service/unit-test-evidence.json",
                    "docs/agent-runs/run/service-plans/order-service/implementation-manifest.md",
                    "docs/agent-runs/run/service-plans/order-service/coverage-matrix.md",
                ],
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_agent_task_complete_blocks_template_manifest_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            base = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service"
            base.mkdir(parents=True)
            manifest = base / "implementation-manifest.md"
            manifest.write_text("TODO template\n", encoding="utf-8")
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "phase": "implement",
                                "service": "services/order-service",
                                "status": "claimed",
                                "owner": "agent-order",
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/implementation-manifest.md"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = agent_scheduler.complete(
                repo,
                schedule_path,
                "T01",
                "agent-order",
                evidence=["docs/agent-runs/run/service-plans/order-service/implementation-manifest.md"],
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("placeholder/template" in reason for reason in result["blocked_reasons"]))

    def test_clarify_auto_transitions_run_state_when_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants a quote returned.
                    - User confirmation: confirmed-by: user @2026-06-02

                    ## Goal
                    - Return a quote.

                    ## Scope
                    - services/sample-service

                    ## Use Cases
                    - Create quote.

                    ## Acceptance Criteria
                    - AC-1 Quote is returned.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-02
                    """
                ).strip(),
                encoding="utf-8",
            )
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence)
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "worker-1",
                "worker_session": "worker-session-1",
            }
            state["dispatches"] = {"T01": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "inputs": [],
                                "outputs": [evidence.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            complete = dispatcher.dispatch_complete(repo, schedule, state_path, "T01", "requirements-clarifier", [evidence.as_posix()])
            args = SimpleNamespace(
                repo=repo,
                design_doc=Path("docs/design/feature.md"),
                run_state=state_path,
                status_file=None,
            )

            code, result = e2e_dev_harness.clarify(args)
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(complete["ready"], complete["blocked_reasons"])
        self.assertEqual(0, code, result)
        self.assertEqual("CLARIFIED", updated["lifecycle"])
        self.assertEqual("passed", updated["gates"]["clarification"])
        self.assertTrue(result["run_state_transition"]["ready"])
        self.assertTrue(result["blocked_next_without_plan"])
        self.assertFalse(result["next_required"]["code_writes_allowed"])

    def test_clarify_auto_seals_and_completes_single_clarifier_handoff(self) -> None:
        # When the lone requirements-clarifier worker has written its handoff body
        # but not sealed it, the coordinator previously had to hand-run
        # dispatch-ack/complete/finish with a fresh worker handle, deadlocking for
        # many minutes. clarify must self-heal: seal the handoff and complete the
        # dispatch in one shot, then transition to CLARIFIED.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants a quote returned.
                    - User confirmation: confirmed-by: user @2026-06-02

                    ## Goal
                    - Return a quote.

                    ## Scope
                    - services/sample-service

                    ## Use Cases
                    - Create quote.

                    ## Acceptance Criteria
                    - AC-1 Quote is returned.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-02
                    """
                ).strip(),
                encoding="utf-8",
            )
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence, agent_id="requirements-clarifier")
            # Worker wrote the handoff body but did NOT seal it (no ready marker).
            marker = (repo / evidence).with_suffix(".ready.json")
            marker.unlink()
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "worker-1",
                "worker_session": "worker-session-1",
            }
            state["dispatches"] = {"T01": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "inputs": [],
                                "outputs": [evidence.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            # No manual dispatch_complete: clarify must seal + complete on its own.
            args = SimpleNamespace(
                repo=repo,
                design_doc=Path("docs/design/feature.md"),
                run_state=state_path,
                status_file=None,
            )

            code, result = e2e_dev_harness.clarify(args)
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            sealed_after = marker.exists()

        self.assertEqual(0, code, result)
        self.assertEqual("CLARIFIED", updated["lifecycle"])
        self.assertTrue(sealed_after, "clarify should auto-seal the clarifier handoff")
        self.assertEqual("worker_completed", updated["dispatch"]["status"])

    def test_clarify_does_not_rewrite_noncanonical_handoff_during_auto_seal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants a quote returned.
                    - User confirmation: confirmed-by: user @2026-06-02

                    ## Goal
                    - Return a quote.

                    ## Scope
                    - services/sample-service

                    ## Use Cases
                    - Create quote.

                    ## Acceptance Criteria
                    - AC-1 Quote is returned.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-02
                    """
                ).strip(),
                encoding="utf-8",
            )
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            write_ready_handoff(repo, evidence, agent_id="requirements-clarifier")
            handoff_path = repo / evidence
            original_text = handoff_path.read_text(encoding="utf-8").replace(
                "## Open Questions\nNone",
                "## Open Questions\nNo open questions remain; the earlier concern is resolved.",
            )
            handoff_path.write_text(original_text, encoding="utf-8")
            marker = handoff_path.with_suffix(".ready.json")
            marker.unlink()
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "worker-1",
                "worker_session": "worker-session-1",
            }
            state["dispatches"] = {"T01": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [evidence.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                repo=repo,
                design_doc=Path("docs/design/feature.md"),
                run_state=state_path,
                status_file=None,
            )

            code, result = e2e_dev_harness.clarify(args)
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            final_text = handoff_path.read_text(encoding="utf-8")
            marker_exists = marker.exists()

        self.assertEqual(2, code)
        self.assertEqual("CREATED", updated["lifecycle"])
        self.assertEqual(original_text, final_text)
        self.assertFalse(marker_exists)
        self.assertEqual("artifact_repair", result["clarification_dispatch_auto_complete"]["coordinator_action"]["required_action"])

    def test_clarify_does_not_refresh_stale_ready_marker_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants a quote returned.
                    - User confirmation: confirmed-by: user @2026-06-02

                    ## Goal
                    - Return a quote.

                    ## Scope
                    - services/sample-service

                    ## Use Cases
                    - Create quote.

                    ## Acceptance Criteria
                    - AC-1 Quote is returned.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-02
                    """
                ).strip(),
                encoding="utf-8",
            )
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            write_ready_handoff(repo, evidence, agent_id="requirements-clarifier")
            handoff_path = repo / evidence
            marker = handoff_path.with_suffix(".ready.json")
            stale_marker = marker.read_text(encoding="utf-8")
            handoff_path.write_text(
                handoff_path.read_text(encoding="utf-8").replace(
                    "Requirements are clarified for dispatch.",
                    "Requirements are clarified for dispatch with a later edit.",
                ),
                encoding="utf-8",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "worker-1",
                "worker_session": "worker-session-1",
            }
            state["dispatches"] = {"T01": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [evidence.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                repo=repo,
                design_doc=Path("docs/design/feature.md"),
                run_state=state_path,
                status_file=None,
            )

            code, result = e2e_dev_harness.clarify(args)
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            final_marker = marker.read_text(encoding="utf-8")

        self.assertEqual(2, code)
        self.assertEqual("CREATED", updated["lifecycle"])
        self.assertEqual(stale_marker, final_marker)
        self.assertEqual("artifact_repair", result["clarification_dispatch_auto_complete"]["coordinator_action"]["required_action"])
        self.assertIn("ready_marker_hash_mismatch", result["clarification_dispatch_auto_complete"]["blocker_codes"])

    def test_clarify_blocks_before_requirements_worker_completion_without_design_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text("# Feature\n\n## Restated Intent\n", encoding="utf-8")
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "waiting_dispatch",
                "runtime": "manual",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            schedule = state_path.parent / "agent-schedule.json"
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                repo=repo,
                design_doc=Path("docs/design/feature.md"),
                run_state=state_path,
                status_file=None,
            )

            code, result = e2e_dev_harness.clarify(args)

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertEqual("clarification_dispatch_incomplete", result["code"])
        self.assertIn("manual_worker_packet", result)
        self.assertIn("dispatch-ack", " ".join(result["next_commands"]))
        self.assertNotIn("missing_sections", result)
        self.assertNotIn("empty_sections", result)

    def test_gate_auto_transitions_implementation_phase_when_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            red.parent.mkdir(parents=True)
            red.write_text("expected failure\n", encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            args = SimpleNamespace(
                repo=repo,
                design_doc=None,
                kg_status_file=None,
                phase="implementation",
                red_test_evidence=red,
                coverage_matrix=None,
                unit_test_evidence=None,
                business_review=None,
                memory_updates=None,
                skip_spring_static_check=False,
                rework_dir=None,
                dependency_report=None,
                implementation_manifest=None,
                review_dir=None,
                review_profile=None,
                handoff_dir=None,
                contract_dir=None,
                require_contracts=False,
                require_handoffs=False,
                require_semantic_reviews=False,
                requirements_archive=None,
                require_requirements_archive=False,
                strict_workflow=False,
                run_state=state_path,
                status_file=None,
            )

            with patch.object(
                e2e_dev_harness.implementation_gate,
                "validate_gate_request",
                return_value={
                    "ready": True,
                    "blocked_reasons": [],
                    "warnings": [],
                    **implementation_gate_payload(red),
                },
            ):
                code, result = e2e_dev_harness.gate(args)
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            lock = json.loads((state_path.parent / ".phase-lock").read_text(encoding="utf-8"))

        self.assertEqual(0, code, result)
        self.assertEqual("IMPLEMENTED", updated["lifecycle"])
        self.assertEqual("passed", updated["gates"]["implementation"])
        self.assertEqual("code-write-open", lock["state"])
        self.assertTrue(result["run_state_transition"]["ready"])

    def test_phase_guard_blocks_code_write_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Code write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_claude_update_tool_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Update",
                [Path("jeepay-payment/src/main/java/com/jeequan/jeepay/pay/service/RiskControlService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Code write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_fails_closed_for_unknown_code_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = phase_guard.validate_action(
                repo,
                "PatchFile",
                [Path("jeepay-core/src/main/java/com/jeequan/jeepay/core/entity/PayOrder.java")],
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("unrecognized tool" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_stale_phase_lock_when_run_state_is_not_implemented(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)
            lock_path = state_path.parent / ".phase-lock"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["lifecycle"] = "IMPLEMENTED"
            lock["state"] = "code-write-open"
            lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("does not match run-state lifecycle" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_direct_harness_control_file_edit_with_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("docs/agent-runs/run/.phase-lock")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Harness control file write blocked" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(result["not_deadlock"])
        self.assertIn("next_valid_command", result)
        self.assertTrue(any("disable or edit harness hooks" in action for action in result["forbidden_actions"]))

    def test_phase_guard_blocks_direct_hook_config_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Write",
                [Path(".claude/settings.json")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("hook config edit blocked" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertEqual("CREATED", result["lifecycle"])
        self.assertTrue(result["not_deadlock"])
        self.assertIn("requirements-clarifier", " ".join(result["allowed_actions"]).lower())

    def test_phase_guard_blocks_red_test_write_in_planned_without_active_test_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            lock = json.loads((state_path.parent / ".phase-lock").read_text(encoding="utf-8"))

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/test/java/PaymentServiceTest.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertEqual("test-write-open", lock["state"])
        self.assertIn("PLANNED", lock["allowed_test_write_lifecycles"])
        self.assertFalse(result["ready"])
        self.assertTrue(any("test-case-developer" in reason for reason in result["blocked_reasons"]))
        self.assertEqual(["services/payment-service/src/test/java/PaymentServiceTest.java"], result["test_code_paths"])

    def test_phase_guard_allows_red_test_write_from_active_test_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            state["dispatches"] = {
                "T05": {
                    "status": "worker_running",
                    "current_task_id": "T05",
                    "current_agent": "test-case-developer",
                    "worker_handle": "test-worker-1",
                }
            }
            state["dispatch"] = state["dispatches"]["T05"]
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/test/java/PaymentServiceTest.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_blocks_mixed_test_and_runtime_write_in_planned_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "MultiEdit",
                [
                    Path("services/payment-service/src/test/java/PaymentServiceTest.java"),
                    Path("services/payment-service/src/main/java/PaymentService.java"),
                ],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertEqual(["services/payment-service/src/main/java/PaymentService.java"], result["runtime_code_paths"])
        self.assertTrue(any("Code write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_parses_apply_patch_hook_paths(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": textwrap.dedent(
                        """
                        *** Begin Patch
                        *** Update File: services/payment-service/src/main/java/PaymentService.java
                        @@
                        +changed
                        *** End Patch
                        """
                    )
                },
            }
        )

        tool, paths = phase_guard.parse_hook_input(hook_text)

        self.assertEqual("apply_patch", tool)
        self.assertEqual(["services/payment-service/src/main/java/PaymentService.java"], paths)

    def test_phase_guard_blocks_bash_write_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)
            hook_text = json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "cat <<'EOF' > services/payment-service/src/main/java/PaymentService.java\nclass X {}\nEOF"
                    },
                }
            )
            tool, paths = phase_guard.parse_hook_input(hook_text)

            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], run_dir=Path("docs/agent-runs/run"))

        self.assertEqual(["services/payment-service/src/main/java/PaymentService.java"], paths)
        self.assertFalse(result["ready"])
        self.assertTrue(any("Code write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_forged_implemented_state_and_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)
            state["lifecycle"] = "IMPLEMENTED"
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            lock_path = state_path.parent / ".phase-lock"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["lifecycle"] = "IMPLEMENTED"
            lock["state"] = "code-write-open"
            lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("transition history" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_inline_python_control_file_mutation(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python -c \"from pathlib import Path; "
                        "p=Path('docs/agent-runs/run/.phase-lock'); "
                        "p.write_text('{\\\"lifecycle\\\":\\\"IMPLEMENTED\\\"}')\""
                    )
                },
            }
        )
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Harness control file write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_allows_harness_cli_referencing_run_state(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py clarify "
                        "--design-doc docs/design/URCS.md "
                        "--run-state docs/agent-runs/run/run-state.json 2>&1"
                    )
                },
            }
        )
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertIn("docs/agent-runs/run/run-state.json", paths)
        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_allows_control_plane_repair_cli(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py control-plane repair . "
                        "--run-dir docs/agent-runs/run --scope task-contracts --json"
                    )
                },
            }
        )
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_blocks_direct_control_plane_json_mutation(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python -c \"from pathlib import Path; "
                        "p=Path('docs/agent-runs/run/control-plane.json'); "
                        "p.write_text('{}')\""
                    )
                },
            }
        )
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Harness control file write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_unscoped_inline_shell_mutation(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "python -c \"target='services/' + 'payment/src/main/java/Pay.java'; open(target, 'w').write('x')\""
                },
            }
        )
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Shell write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_extracts_indirect_python_write_target(self) -> None:
        target = (
            r"C:\Users\14907\Documents\Codex\2026-05-23\petalpay\docs\design\DESIGN-2026-002-"
            "\u667a\u80fd\u4ea4\u6613\u98ce\u63a7\u5f15\u64ce\u4e0e\u591a\u7ea7\u8d44\u91d1\u6e05\u7ed3\u7b97\u7cfb\u7edf.md"
        )
        hook_text = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python -c \""
                        f"p = r'{target}'\n"
                        "with open(p, 'w', encoding='utf-8') as f:\n"
                        "    f.write('x')"
                        "\""
                    )
                },
            }
        )

        tool, paths = phase_guard.parse_hook_input(hook_text)

        self.assertEqual("Bash", tool)
        self.assertIn(target, paths)

    def test_phase_guard_blocks_indirect_python_write_to_worker_owned_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            target = repo / "docs" / "agent-runs" / "run" / "handoffs" / "01-requirements-clarifier.md"
            relative_target = target.relative_to(repo).as_posix()
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "awaiting_runtime_spawn",
                "runtime": "codex",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            (run_dir / "agent-schedule.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [relative_target],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            hook_text = json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": (
                            "python -c \""
                            f"p = r'{target}'\n"
                            "with open(p, 'w', encoding='utf-8') as f:\n"
                            "    f.write('x')"
                            "\""
                        )
                    },
                }
            )
            tool, paths = phase_guard.parse_hook_input(hook_text)
            command_text = phase_guard.extract_hook_command_text(hook_text)

            result = phase_guard.validate_action(
                repo,
                tool,
                [Path(path) for path in paths],
                run_dir=Path("docs/agent-runs/run"),
                command_text=command_text,
            )

        self.assertFalse(result["ready"])
        self.assertIn(relative_target, " ".join(result["blocked_reasons"]))
        self.assertTrue(any("Worker output write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_allows_readonly_bash_without_active_run(self) -> None:
        hook_text = json.dumps({"tool_name": "Bash", "tool_input": {"command": "python --version"}})
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_pre_code_blocks_code_write_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.pre_code(
                SimpleNamespace(
                    repo=repo,
                    tool="Edit",
                    path=[Path("services/payment-service/src/main/java/PaymentService.java")],
                    patch=None,
                    command_text="",
                    lock=None,
                    run_dir=Path("docs/agent-runs/run"),
                    status_file=None,
                )
            )

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])

    def test_phase_guard_blocks_code_write_in_implementation_without_active_code_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("code-developer" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_allows_code_write_from_active_code_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            state["dispatches"] = {
                "T07": {
                    "status": "worker_running",
                    "current_task_id": "T07",
                    "current_agent": "code-developer",
                    "worker_handle": "code-worker-1",
                }
            }
            state["dispatch"] = state["dispatches"]["T07"]
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_blocks_created_coordinator_writing_requirements_worker_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "waiting_dispatch",
                "runtime": "manual",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Write",
                [Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("requirements-clarifier" in reason for reason in result["blocked_reasons"]))
        self.assertIn("manual_worker_packet", result)
        self.assertIn("dispatch-ack", " ".join(result["manual_worker_packet"]["next_commands"]))

    def test_phase_guard_allows_requirements_worker_writing_owned_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "manual",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "requirements-worker-1",
                "worker_session": "requirements-worker-session-1",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Write",
                [Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_stop_guard_blocks_implemented_run_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            write_implemented_state(repo, state_path, state)

            result = harness_stop_guard.evaluate(repo, run_state_path=state_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("IMPLEMENTED" in reason for reason in result["blocked_reasons"]))
        self.assertIn("R3 review", result["next_action"])

    def test_stop_guard_allows_verified_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            write_implemented_state(repo, state_path, state)
            completion = state_path.parent / "evidence" / "completion-gate.json"
            completion.write_text(json.dumps({"phase": "completion", "ready": True}), encoding="utf-8")
            transition = run_state.transition_state(
                repo,
                state_path,
                "VERIFIED",
                gate="completion",
                gate_status="passed",
                evidence=completion,
            )
            self.assertTrue(transition["ready"], transition["blocked_reasons"])

            result = harness_stop_guard.evaluate(repo, run_state_path=state_path)

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_stop_guard_allows_no_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = harness_stop_guard.evaluate(Path(tmp))

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_stop_guard_ignores_empty_stale_run_scaffold_without_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "2026-06-02-URCS"
            for name in ("agent-roles", "confirmations", "coordinator-results", "evidence"):
                (run_dir / name).mkdir(parents=True)

            result = harness_stop_guard.evaluate(repo)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(any("empty harness run directories" in warning for warning in result["warnings"]))

    def test_stop_guard_blocks_run_directory_without_run_state_when_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            (run_dir / "evidence").mkdir(parents=True)
            (run_dir / "evidence" / "partial.txt").write_text("partial\n", encoding="utf-8")

            result = harness_stop_guard.evaluate(repo)

        self.assertFalse(result["ready"])
        self.assertTrue(any("run-state" in reason for reason in result["blocked_reasons"]))

    def test_hook_examples_call_phase_guard(self) -> None:
        hook_dir = ROOT / "skills" / "e2e-dev-harness" / "hooks"

        for name in (
            "claude-code-settings.example.json",
            "codex-pre-action.example.json",
            "gemini-pre-action.example.json",
            "opencode-plugin.example.js",
        ):
            with self.subTest(name=name):
                text = (hook_dir / name).read_text(encoding="utf-8")
                self.assertIn("phase_guard.py", text)
                self.assertNotIn("python skills/e2e-dev-harness/scripts/phase_guard.py .", text)
                self.assertIn("--require-active-run-for-read", text)
                if name == "opencode-plugin.example.js":
                    self.assertIn("tool.execute.before", text)
                    self.assertIn("throw new Error", text)
                if name == "claude-code-settings.example.json":
                    self.assertIn("--require-session-checkpoint", text)
                if name != "opencode-plugin.example.js":
                    self.assertIn("blocking", text.lower() if "claude" not in name else "blocking")
                if name == "claude-code-settings.example.json":
                    self.assertIn("harness_stop_guard.py", text)
                    self.assertIn("Bash", text)
                    self.assertIn("Update", text)
                    self.assertIn("Read", text)
                    self.assertIn("Grep", text)
                    self.assertIn("Glob", text)

    def test_install_hooks_dry_run_reports_claude_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = install_hooks.install(repo, "claude", dry_run=True)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["target"].endswith(".claude\\settings.json") or result["target"].endswith(".claude/settings.json"))
        self.assertIn("hooks", result["planned_config"])
        command = result["planned_config"]["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        matcher = result["planned_config"]["hooks"]["PreToolUse"][0]["matcher"]
        self.assertIn("Update", matcher)
        self.assertIn(str(ROOT / "skills" / "e2e-dev-harness" / "scripts" / "phase_guard.py"), command)
        self.assertIn(str(repo), command)
        self.assertIn("--require-active-run-for-read", command)
        self.assertIn("--require-session-checkpoint", command)
        stop_command = result["planned_config"]["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn(str(ROOT / "skills" / "e2e-dev-harness" / "scripts" / "harness_stop_guard.py"), stop_command)
        self.assertIn(str(repo), stop_command)

    def test_install_hooks_rewrites_portable_runtime_templates(self) -> None:
        for runtime in ("codex", "gemini"):
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)

                result = install_hooks.install(repo, runtime, dry_run=True)
                command = result["planned_config"]["command"]

                self.assertTrue(result["ready"], result["blocked_reasons"])
                self.assertIn(str(ROOT / "skills" / "e2e-dev-harness" / "scripts" / "phase_guard.py"), command)
                self.assertIn(str(repo), command)
                self.assertNotIn("skills/e2e-dev-harness/scripts/phase_guard.py .", command)

    def test_install_hooks_installs_opencode_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = install_hooks.install(repo, "opencode")
            target = repo / ".opencode" / "plugins" / "e2e-dev-harness.js"
            validation = install_hooks.validate_config(target)
            text = target.read_text(encoding="utf-8")

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(validation["ready"], validation["blocked_reasons"])
        self.assertIn("tool.execute.before", text)
        self.assertIn(str(ROOT / "skills" / "e2e-dev-harness" / "scripts" / "phase_guard.py").replace("\\", "\\\\"), text)
        self.assertIn(str(repo).replace("\\", "\\\\"), text)
        self.assertIn("--require-active-run-for-read", text)
        self.assertIn("--require-session-checkpoint", text)

    def test_install_hooks_rejects_nonblocking_opencode_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = repo / ".opencode" / "plugins" / "e2e-dev-harness.js"
            target.parent.mkdir(parents=True)
            target.write_text("export const X = { 'tool.execute.after': () => {} };\n", encoding="utf-8")

            result = install_hooks.validate_config(target)

        self.assertFalse(result["ready"])
        self.assertTrue(any("tool.execute.before" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_merges_claude_settings_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"permissions": {"allow": ["Bash(git status)"]}}), encoding="utf-8")

            first = install_hooks.install(repo, "claude")
            second = install_hooks.install(repo, "claude")
            config = json.loads(settings.read_text(encoding="utf-8"))
            validation = install_hooks.validate_config(settings)

        self.assertTrue(first["ready"], first["blocked_reasons"])
        self.assertTrue(second["ready"], second["blocked_reasons"])
        self.assertTrue(validation["ready"], validation["blocked_reasons"])
        self.assertEqual(["Bash(git status)"], config["permissions"]["allow"])
        self.assertEqual(1, len(config["hooks"]["PreToolUse"]))
        self.assertEqual(1, len(config["hooks"]["Stop"]))

    def test_install_hooks_rejects_repo_relative_phase_guard_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python skills/e2e-dev-harness/scripts/phase_guard.py . --hook-input - --json",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.validate_config(settings)

        self.assertFalse(result["ready"])
        self.assertTrue(any("absolute path" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rejects_missing_claude_stop_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Read|Grep|Glob|Task|Write|Edit|Update|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'phase_guard.py'}\" \"{repo}\" --hook-input - --require-active-run-for-read --require-session-checkpoint --json",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.validate_config(settings)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Stop hook" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rejects_missing_claude_update_matcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Read|Grep|Glob|Task|Write|Edit|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'phase_guard.py'}\" \"{repo}\" --hook-input - --require-active-run-for-read --require-session-checkpoint --json",
                                        }
                                    ],
                                }
                            ],
                            "Stop": [
                                {
                                    "matcher": "",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'harness_stop_guard.py'}\" \"{repo}\" --hook-input - --json",
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.validate_config(settings)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Update" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rewrites_stale_repo_relative_phase_guard_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python skills/e2e-dev-harness/scripts/phase_guard.py . --hook-input - --json",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.install(repo, "claude", dry_run=True)
            entries = result["planned_config"]["hooks"]["PreToolUse"]

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(1, len(entries))
        command = entries[0]["hooks"][0]["command"]
        self.assertIn(str(ROOT / "skills" / "e2e-dev-harness" / "scripts" / "phase_guard.py"), command)
        self.assertIn(str(repo), command)
        self.assertNotIn("python skills/e2e-dev-harness/scripts/phase_guard.py .", command)

    def test_auto_transition_from_ready_gate_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            red = run_dir / "evidence" / "red-test.txt"
            status = run_dir / "evidence" / "implementation-gate.json"
            red.parent.mkdir(parents=True)
            red.write_text("expected failure\n", encoding="utf-8")
            status.write_text(json.dumps(implementation_gate_payload(red)), encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = auto_transition.transition_from_status(repo, status, state_path)
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("transitioned", result["action"])
        self.assertEqual("IMPLEMENTED", updated["lifecycle"])
        self.assertEqual("passed", updated["gates"]["implementation"])

    def test_auto_transition_skips_unready_gate_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            status = run_dir / "evidence" / "implementation-gate.json"
            status.parent.mkdir(parents=True)
            status.write_text(json.dumps({"phase": "implementation", "ready": False}), encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = auto_transition.transition_from_status(repo, status, state_path)
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("skipped", result["action"])
        self.assertEqual("PLANNED", updated["lifecycle"])

    def test_ci_template_documents_harness_verify(self) -> None:
        template = ROOT / "skills" / "e2e-dev-harness" / "ci" / "github-actions-harness.yml"
        text = template.read_text(encoding="utf-8")

        self.assertIn("e2e_dev_harness.py verify", text)
        self.assertIn("--harness", text)
        self.assertIn("HARNESS_RUN_STATE", text)

    def test_harness_policy_blocks_completed_run_without_reviews(self) -> None:
        registry = {
            "schema": "e2e-dev-harness.artifact-registry.v1",
            "selected_mode": "single",
            "services": ["services/order-service"],
            "artifacts": [
                {
                    "type": "requirements_archive",
                    "owner": "global",
                    "path": "docs/agent-runs/run/requirements-archive.md",
                    "status": "present",
                }
            ],
        }
        state = {
            "schema": "e2e-dev-harness.run-state.v1",
            "run_id": "run",
            "lifecycle": "VERIFIED",
            "selected_mode": "single",
            "services": ["services/order-service"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = harness_policy.validate_policy(repo, None, state, registry)

        self.assertFalse(result["ready"])
        self.assertTrue(any("R1 design review" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("R2 test review" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("R3 implementation review" in reason for reason in result["blocked_reasons"]))

    def test_harness_policy_cannot_disable_required_completion_reviews(self) -> None:
        registry = {
            "schema": "e2e-dev-harness.artifact-registry.v1",
            "selected_mode": "single",
            "services": ["services/order-service"],
            "artifacts": [
                {
                    "type": "requirements_archive",
                    "owner": "global",
                    "path": "docs/agent-runs/run/requirements-archive.md",
                    "status": "present",
                }
            ],
        }
        state = {
            "schema": "e2e-dev-harness.run-state.v1",
            "run_id": "run",
            "lifecycle": "VERIFIED",
            "selected_mode": "single",
            "services": ["services/order-service"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            policy = repo / ".e2e" / "harness-policy.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                json.dumps(
                    {
                        "require_run_state": False,
                        "require_artifact_registry": False,
                        "require_semantic_reviews_on_completion": False,
                    }
                ),
                encoding="utf-8",
            )

            result = harness_policy.validate_policy(repo, policy, state, registry)

        self.assertTrue(result["policy"]["require_run_state"])
        self.assertTrue(result["policy"]["require_artifact_registry"])
        self.assertTrue(result["policy"]["require_semantic_reviews_on_completion"])
        self.assertFalse(result["ready"])
        self.assertTrue(any("R3 implementation review" in reason for reason in result["blocked_reasons"]))

    def test_harness_verify_replays_state_registry_and_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"exec_plan": "docs/agent-runs/run/exec-plan.md"},
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)

            result = harness_verify.validate(repo, state_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("not VERIFIED" in reason for reason in result["blocked_reasons"]))

    def test_harness_verify_stops_when_run_state_cannot_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text("{", encoding="utf-8")

            result = harness_verify.validate(repo, state_path)

        self.assertFalse(result["ready"])
        self.assertIsNone(result["artifact_registry"])
        self.assertIsNone(result["policy"])
        self.assertTrue(any("Run state" in reason for reason in result["blocked_reasons"]))

    def test_run_summary_reports_missing_required_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {
                    "exec_plan": "docs/agent-runs/run/exec-plan.md",
                    "requirements": "docs/agent-runs/run/handoffs/01-requirements-clarifier.md",
                    "design_review": "docs/agent-runs/run/reviews/R1-design-review.md",
                },
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)

            summary = run_summary.build_summary(
                repo,
                state_path,
                {"ready": False, "blocked_reasons": ["R3 missing"], "warnings": ["hash warning"]},
            )

        self.assertEqual("e2e-dev-harness.run-summary.v1", summary["schema"])
        self.assertEqual(3, summary["artifact_count"])
        self.assertEqual(1, summary["blocked_count"])
        self.assertEqual(1, summary["warning_count"])
        self.assertIn("docs/agent-runs/run/handoffs/01-requirements-clarifier.md", summary["required_missing"])
        self.assertEqual("planned", summary["semantic_reviews"]["R1"])
        self.assertIn("Resolve harness verification blockers.", summary["next_actions"])

    def test_run_summary_blocks_corrupt_execution_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            run_dir.mkdir(parents=True)
            trace = run_dir / "execution-trace.json"
            trace.write_text("{not-json", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"execution_trace": "docs/agent-runs/run/execution-trace.json"},
                "single",
                [],
            )
            registry_path = run_dir / "artifact-registry.json"
            state_path = run_dir / "run-state.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)

            summary = run_summary.build_summary(repo, state_path, {"ready": True, "blocked_reasons": [], "warnings": []})

        self.assertFalse(summary["ready"])
        self.assertEqual(1, summary["source_error_count"])
        self.assertTrue(any("Execution trace is invalid JSON" in reason for reason in summary["blocked_reasons"]))
        self.assertIn("Repair unreadable or invalid harness JSON artifacts before trusting the archive.", summary["next_actions"])

    def test_run_summary_blocks_corrupt_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text("{not-json", encoding="utf-8")

            summary = run_summary.build_summary(repo, state_path, {"ready": True, "blocked_reasons": [], "warnings": []})

        self.assertFalse(summary["ready"])
        self.assertEqual(1, summary["source_error_count"])
        self.assertTrue(any("Run state is invalid JSON" in reason for reason in summary["blocked_reasons"]))

    def test_harness_verify_writes_run_summary_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"exec_plan": "docs/agent-runs/run/exec-plan.md"},
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            summary_json = Path("docs/agent-runs/run/run-summary.json")
            summary_md = Path("docs/agent-runs/run/run-summary.md")
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)
            result = harness_verify.validate(repo, state_path)

            summary = harness_verify.write_summary_outputs(repo, state_path, result, summary_json, summary_md)

            written = json.loads((repo / summary_json).read_text(encoding="utf-8"))
            markdown_text = (repo / summary_md).read_text(encoding="utf-8")

        self.assertFalse(summary["ready"])
        self.assertEqual("run", written["run_id"])
        self.assertTrue(any("not VERIFIED" in reason for reason in written["blocked_reasons"]))
        self.assertIn("# Run Summary: run", markdown_text)

    def test_workflow_tier_auto_marks_messaging_cross_service_as_critical(self) -> None:
        design_text = "Publish a DMQ refund callback with topic, tag, group, and payload contract."
        facts = {"service_candidates": ["services/refund-service", "services/ledger-service"], "multi_service": True}
        dependency_report = {"dependencies": [{"kind": "dmq"}], "unresolved_questions": []}

        result = task_tier.evaluate("auto", design_text, facts, dependency_report)

        self.assertEqual("critical", result["tier"])
        self.assertIn("gitnexus-impact", result["required_gates"])
        self.assertIn("contracts", result["required_gates"])
        self.assertIn("strict-guard", result["required_gates"])

    def test_workflow_tier_auto_keeps_single_service_rest_endpoint_standard(self) -> None:
        design_text = "Add one REST API endpoint in order-service for an admin lookup screen."
        facts = {"service_candidates": ["services/order-service"], "multi_service": False}

        result = task_tier.evaluate("auto", design_text, facts, {"dependencies": []})

        self.assertEqual("standard", result["tier"])
        self.assertIn("r1-review", result["required_gates"])
        self.assertNotIn("contracts", result["required_gates"])
        self.assertNotIn("strict-guard", result["required_gates"])

    def test_workflow_tier_explicit_basic_cannot_downgrade_critical_auto_minimum(self) -> None:
        design_text = "Publish a DMQ refund callback with topic, tag, group, and payload contract."
        facts = {"service_candidates": ["services/refund-service", "services/ledger-service"], "multi_service": True}
        dependency_report = {"dependencies": [{"kind": "dmq"}], "unresolved_questions": []}

        result = task_tier.evaluate("basic", design_text, facts, dependency_report)

        self.assertEqual("basic", result["user_requested"])
        self.assertEqual("critical", result["auto_minimum"]["tier"])
        self.assertEqual("critical", result["effective"]["tier"])
        self.assertEqual("critical", result["tier"])
        self.assertTrue(result["downgrade_blocked"])
        self.assertIn("contracts", result["required_gates"])

    def test_workflow_tier_auto_marks_cross_service_http_api_as_critical(self) -> None:
        design_text = "Add a REST API client from order-service to payment-service."
        facts = {"service_candidates": ["services/order-service", "services/payment-service"], "multi_service": True}
        dependency_report = {
            "dependencies": [{"kind": "http", "source_service": "services/order-service"}],
            "unresolved_questions": [],
        }

        result = task_tier.evaluate("auto", design_text, facts, dependency_report)

        self.assertEqual("critical", result["tier"])
        self.assertIn("contracts", result["required_gates"])
        self.assertIn("strict-guard", result["required_gates"])

    def test_workflow_tier_basic_still_keeps_harness_record(self) -> None:
        result = task_tier.evaluate("basic", "Update validation message.", {}, {})

        self.assertEqual("basic", result["tier"])
        self.assertIn("clarification", result["required_gates"])
        self.assertIn("impact-summary", result["required_gates"])
        self.assertIn("test-evidence", result["required_gates"])
        self.assertIn("task-alignment", result["required_gates"])
        self.assertIn("run-state", result["required_gates"])
        self.assertIn("artifact-registry", result["required_gates"])
        self.assertIn("run-summary", result["required_gates"])
        self.assertNotIn("r1-review", result["required_gates"])

    def test_prepare_reports_workflow_tier(self) -> None:
        facts = {
            "poms": ["pom.xml"],
            "root_modules": [],
            "spring_entrypoints": [],
            "spring_configs": [],
            "design_docs_or_media_count": 0,
            "design_docs_or_media_sample": [],
            "graphify_graph": "graphify-out/graph.json",
            "graphify_graph_exists": False,
            "service_candidates": ["services/payment-service", "services/ledger-service"],
            "multi_service": True,
        }
        dependency_result = {
            "ready": True,
            "tool_priority": ["gitnexus", "deterministic-scan", "graphify"],
            "dependencies": [{"kind": "http", "source_service": "services/payment-service"}],
            "unresolved_questions": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "refund.md"
            design.parent.mkdir(parents=True)
            design.write_text("Refund API updates payment state and calls ledger-service.", encoding="utf-8")
            args = SimpleNamespace(
                repo=repo,
                design_doc=Path("docs/design/refund.md"),
                path=None,
                service=None,
                agent_mode="off",
                agent_scope="auto",
                include_agent_content=False,
                max_agent_chars=12000,
                max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
                superpowers_mode="off",
                memory_mode="off",
                agent_orchestration_mode="off",
                service_scope="discovery",
                agent_run_dir=None,
                run_date="2026-05-23",
                kg_mode="auto",
                dependency_scan_mode="strict",
                write_dependency_report=False,
                dependency_output_dir=None,
                workflow_tier="auto",
                status_file=None,
            )
            with (
                patch.object(e2e_dev_harness.kg_refresh, "detect", return_value=facts),
                patch.object(e2e_dev_harness.cross_service_dependency_scan, "scan", return_value=dependency_result),
            ):
                code, result = e2e_dev_harness.prepare(args)

        self.assertEqual(0, code, result.get("blocked_reasons"))
        self.assertEqual("critical", result["workflow_tier"]["tier"])
        self.assertIn("contracts", result["workflow_tier"]["required_gates"])

    def test_verify_harness_replays_state_and_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"exec_plan": "docs/agent-runs/run/exec-plan.md"},
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            summary_path = repo / "docs" / "agent-runs" / "run" / "run-summary.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)
            args = SimpleNamespace(
                repo=repo,
                design_doc=None,
                path=None,
                service=None,
                agent_mode="off",
                agent_scope="auto",
                include_agent_content=False,
                max_agent_chars=12000,
                max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
                superpowers_mode="off",
                memory_mode="off",
                agent_orchestration_mode="off",
                service_scope="discovery",
                agent_run_dir=None,
                run_date="2026-05-23",
                kg_mode="auto",
                dependency_scan_mode="off",
                write_dependency_report=False,
                dependency_output_dir=None,
                workflow_tier="basic",
                module=None,
                run_gate=False,
                phase="planning",
                kg_status_file=None,
                red_test_evidence=None,
                coverage_matrix=None,
                unit_test_evidence=None,
                business_review=None,
                memory_updates=None,
                requirements_archive=None,
                require_requirements_archive=False,
                dependency_report=None,
                implementation_manifest=None,
                rework_dir=None,
                review_dir=None,
                review_profile=None,
                handoff_dir=None,
                contract_dir=None,
                require_contracts=False,
                require_handoffs=False,
                require_semantic_reviews=False,
                skip_spring_static_check=False,
                skip_maven=True,
                strict_workflow=False,
                workflow_approval=None,
                harness=True,
                state=state_path,
                policy=None,
                strict_artifacts=False,
                run_completion_gate=False,
                summary_json=summary_path,
                summary_md=None,
                status_file=None,
            )

            code, result = e2e_dev_harness.verify(args)
            summary_exists = summary_path.exists()

        self.assertEqual(2, code, result)
        self.assertFalse(result["harness"]["ready"])
        self.assertTrue(any("not VERIFIED" in reason for reason in result["harness"]["blocked_reasons"]))
        self.assertTrue(summary_exists)

    def test_execution_trace_records_elapsed_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            trace = Path("docs/agent-runs/run/execution-trace.json")

            execution_trace.append_event(
                repo,
                trace,
                "r3-review",
                "finish",
                status="ready",
                elapsed_ms=120,
                input_tokens=1000,
                output_tokens=250,
                agent="reviewer-r3",
                decision="approved",
            )
            result = execution_trace.validate_trace(repo, trace, ["r3-review"])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(120, result["summary"]["elapsed_ms_total"])
        self.assertEqual(1250, result["summary"]["tokens"]["total"])

    def test_execution_trace_blocks_corrupt_json_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            trace = repo / "docs" / "agent-runs" / "run" / "execution-trace.json"
            trace.parent.mkdir(parents=True)
            trace.write_text("{not-json", encoding="utf-8")

            result = execution_trace.append_event(repo, trace.relative_to(repo), "verify", "finish")
            validation = execution_trace.validate_trace(repo, trace.relative_to(repo))
            trace_text = trace.read_text(encoding="utf-8")

        self.assertFalse(result["ready"])
        self.assertFalse(validation["ready"])
        self.assertIn("{not-json", trace_text)
        self.assertTrue(any("invalid JSON" in reason for reason in result["blocked_reasons"]))

    def test_verify_blocks_when_trace_file_is_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            trace_path = repo / "docs" / "agent-runs" / "run" / "execution-trace.json"
            trace_path.parent.mkdir(parents=True)
            trace_path.write_text("{not-json", encoding="utf-8")
            args = SimpleNamespace(
                repo=repo,
                design_doc=None,
                path=None,
                service=None,
                agent_mode="off",
                agent_scope="auto",
                include_agent_content=False,
                max_agent_chars=12000,
                max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
                superpowers_mode="off",
                memory_mode="off",
                agent_orchestration_mode="off",
                service_scope="discovery",
                agent_run_dir=None,
                run_date="2026-05-23",
                kg_mode="auto",
                dependency_scan_mode="off",
                write_dependency_report=False,
                dependency_output_dir=None,
                workflow_tier="basic",
                module=None,
                run_gate=False,
                phase="planning",
                kg_status_file=None,
                red_test_evidence=None,
                coverage_matrix=None,
                unit_test_evidence=None,
                business_review=None,
                memory_updates=None,
                requirements_archive=None,
                require_requirements_archive=False,
                dependency_report=None,
                implementation_manifest=None,
                changed_files=None,
                base_ref=None,
                rework_dir=None,
                review_dir=None,
                review_profile=None,
                handoff_dir=None,
                contract_dir=None,
                require_contracts=False,
                require_handoffs=False,
                require_semantic_reviews=False,
                skip_spring_static_check=False,
                run_state=None,
                skip_maven=True,
                strict_workflow=False,
                workflow_approval=None,
                harness=False,
                state=None,
                policy=None,
                strict_artifacts=False,
                run_completion_gate=False,
                summary_json=None,
                summary_md=None,
                status_file=None,
                trace_file=trace_path,
            )

            code, result = e2e_dev_harness.verify(args)
            trace_text = trace_path.read_text(encoding="utf-8")

        self.assertEqual(2, code)
        self.assertFalse(result["execution_trace"]["ready"])
        self.assertIn("{not-json", trace_text)

    def test_verify_writes_execution_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            trace_path = Path("docs/agent-runs/run/execution-trace.json")
            args = SimpleNamespace(
                repo=repo,
                design_doc=None,
                path=None,
                service=None,
                agent_mode="off",
                agent_scope="auto",
                include_agent_content=False,
                max_agent_chars=12000,
                max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
                superpowers_mode="off",
                memory_mode="off",
                agent_orchestration_mode="off",
                service_scope="discovery",
                agent_run_dir=None,
                run_date="2026-05-23",
                kg_mode="auto",
                dependency_scan_mode="off",
                write_dependency_report=False,
                dependency_output_dir=None,
                workflow_tier="basic",
                module=None,
                run_gate=False,
                phase="planning",
                kg_status_file=None,
                red_test_evidence=None,
                coverage_matrix=None,
                unit_test_evidence=None,
                business_review=None,
                memory_updates=None,
                requirements_archive=None,
                require_requirements_archive=False,
                dependency_report=None,
                implementation_manifest=None,
                changed_files=None,
                base_ref=None,
                rework_dir=None,
                review_dir=None,
                review_profile=None,
                handoff_dir=None,
                contract_dir=None,
                require_contracts=False,
                require_handoffs=False,
                require_semantic_reviews=False,
                skip_spring_static_check=False,
                run_state=None,
                skip_maven=True,
                strict_workflow=False,
                workflow_approval=None,
                harness=False,
                state=None,
                policy=None,
                strict_artifacts=False,
                run_completion_gate=False,
                summary_json=None,
                summary_md=None,
                status_file=None,
                trace_file=trace_path,
            )

            code, _result = e2e_dev_harness.verify(args)
            trace_result = execution_trace.validate_trace(repo, trace_path, ["prepare", "maven", "verify"])

        self.assertEqual(0, code, _result.get("blocked_reasons"))
        self.assertTrue(trace_result["ready"], trace_result["blocked_reasons"])
        self.assertGreaterEqual(trace_result["summary"]["elapsed_ms_total"], 0)

    def test_multi_agent_plan_splits_code_developers_by_service(self) -> None:
        artifacts = orchestration_plan.artifacts(
            "checkout",
            run_date="2026-05-23",
            services=["services/order-service", "services/payment-service"],
        )

        agents = orchestration_plan.agent_plan("multi", artifacts, ["services/order-service", "services/payment-service"])
        names = [agent["name"] for agent in agents]

        self.assertIn("code-developer-order-service", names)
        self.assertIn("code-developer-payment-service", names)
        self.assertIn("implementation-reviewer-order-service", names)
        self.assertIn("implementation-reviewer-payment-service", names)
        self.assertIn("coverage-reviewer", names)
        order_developer = next(agent for agent in agents if agent["name"] == "code-developer-order-service")
        self.assertNotIn(
            artifacts["service_plans"]["services/order-service"]["implementation_review"],
            order_developer["outputs"],
        )

    def test_auto_mode_ignores_low_signal_api_message_words(self) -> None:
        body = "\n".join(
            f"Line {i}: The api endpoint emits an event message and uses a timeout."
            for i in range(80)
        )
        design_text = f"# Feature\n\n## Goal\nAdd one REST api endpoint.\n\n{body}"
        facts: dict = {"service_candidates": ["services/order-service"]}

        mode, reasons = orchestration_plan.choose_mode("auto", facts, design_text, False)

        self.assertEqual("single-review", mode, reasons)
        self.assertTrue(any("single-review floor" in reason for reason in reasons))

    def test_auto_mode_uses_single_review_for_single_service_risk_terms(self) -> None:
        design_text = textwrap.dedent(
            """
            # Payment Notice

            The payment service publishes a DMQ topic with a payload schema and requires idempotent retry.
            """
        )
        facts: dict = {"service_candidates": ["services/payment-service"]}

        mode, reasons = orchestration_plan.choose_mode("auto", facts, design_text, False)

        self.assertEqual("single-review", mode)
        self.assertTrue(any("risk keywords" in reason for reason in reasons))

    def test_auto_mode_uses_single_review_above_large_design_threshold(self) -> None:
        design_text = "# Large Feature\n\n" + ("x" * (orchestration_plan.LARGE_DESIGN_CHAR_THRESHOLD + 1))
        facts: dict = {"service_candidates": ["services/order-service"]}

        mode, reasons = orchestration_plan.choose_mode("auto", facts, design_text, False)

        self.assertEqual("single-review", mode)
        self.assertTrue(any("context isolation" in reason for reason in reasons))

    def test_auto_mode_triggers_multi_for_multiple_services_even_without_risk_terms(self) -> None:
        facts: dict = {"service_candidates": ["services/order-service", "services/payment-service"]}

        mode, reasons = orchestration_plan.choose_mode("auto", facts, "# Feature\n\nUpdate status fields.", False)

        self.assertEqual("multi", mode)
        self.assertTrue(any("multiple service" in reason for reason in reasons))

    def test_choose_mode_accepts_single_review(self) -> None:
        facts: dict = {"service_candidates": ["services/order-service"]}

        mode, reasons = orchestration_plan.choose_mode("single-review", facts, "irrelevant", False)

        self.assertEqual("single-review", mode)
        self.assertEqual(["mode explicitly set to single-review"], reasons)

    def test_single_review_escalates_to_multi_for_multiple_services(self) -> None:
        facts: dict = {"service_candidates": ["services/order-service", "services/payment-service"]}

        mode, reasons = orchestration_plan.choose_mode("single-review", facts, "irrelevant", False)

        self.assertEqual("multi", mode)
        self.assertTrue(any("single-review escalated" in reason for reason in reasons))

    def test_single_escalates_to_multi_for_multiple_services(self) -> None:
        facts: dict = {"service_candidates": ["services/order-service", "services/payment-service"]}

        mode, reasons = orchestration_plan.choose_mode("single", facts, "irrelevant", False)

        self.assertEqual("multi", mode)
        self.assertTrue(any("single escalated" in reason for reason in reasons))

    def test_single_escalates_to_single_review_for_single_service_risk_terms(self) -> None:
        facts: dict = {"service_candidates": ["services/payment-service"]}

        mode, reasons = orchestration_plan.choose_mode("single", facts, "payment risk control and retry", False)

        self.assertEqual("single-review", mode)
        self.assertTrue(any("single escalated to single-review" in reason for reason in reasons))

    def test_single_review_keeps_phase_reviewers_and_coverage_reviewer(self) -> None:
        artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        agents = orchestration_plan.agent_plan("single-review", artifacts, [])
        names = [agent["name"] for agent in agents]

        self.assertNotIn("single-agent", names)
        self.assertIn("requirements-clarifier", names)
        self.assertIn("use-case-designer", names)
        self.assertIn("test-case-developer", names)
        self.assertIn("code-developer", names)
        self.assertIn("single-reviewer-r1-design", names)
        self.assertIn("single-reviewer-r2-test", names)
        self.assertIn("single-reviewer-r3-implementation", names)
        self.assertIn("coverage-reviewer", names)
        schedule = orchestration_plan.agent_schedule("single-review", [], agents)
        groups = {task["agent"]: task["role_group"] for task in schedule["tasks"]}
        self.assertEqual("design", groups["requirements-clarifier"])
        self.assertEqual("test", groups["test-case-developer"])
        self.assertEqual("code", groups["code-developer"])
        coverage = next(agent for agent in agents if agent["name"] == "coverage-reviewer")
        self.assertIn(artifacts["requirements_archive"], coverage["outputs"])

    def test_orchestration_plan_cli_accepts_single_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            facts = {
                "service_candidates": ["services/order-service"],
                "multi_service": False,
                "design_docs_or_media_count": 0,
                "spring_entrypoints": [],
            }

            with patch.object(orchestration_plan, "detect", return_value=facts), \
                    patch.object(
                        sys,
                        "argv",
                        [
                            "orchestration_plan.py",
                            str(repo),
                            "--mode",
                            "single-review",
                            "--service-scope",
                            "affected",
                            "--service",
                            "services/order-service",
                            "--json",
                        ],
                    ), \
                    patch("sys.stdout", new_callable=io.StringIO) as stdout:
                exit_code = orchestration_plan.main()

            result = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertEqual("single-review", result["selected_mode"])
        self.assertIn("coverage-reviewer", [agent["name"] for agent in result["agents"]])


class SkillDocumentationTests(unittest.TestCase):
    def test_skill_files_do_not_use_utf8_bom(self) -> None:
        skill_dir = ROOT / "skills" / "e2e-dev-harness"
        offenders = [
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in skill_dir.rglob("*")
            if path.is_file() and path.read_bytes().startswith(b"\xef\xbb\xbf")
        ]

        self.assertEqual([], offenders)

    def test_skill_points_non_codex_agents_to_platform_compatibility_reference(self) -> None:
        skill_text = (ROOT / "skills" / "e2e-dev-harness" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Claude Code", skill_text)
        self.assertIn("Codex", skill_text)
        self.assertIn("Gemini", skill_text)
        self.assertIn("references/platform-compatibility.md", skill_text)

    def test_skill_declares_custom_review_profile_reference(self) -> None:
        skill_text = (ROOT / "skills" / "e2e-dev-harness" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("references/review-profiles.md", skill_text)
        self.assertIn("common-review-issues.md", skill_text)
        self.assertIn("references/requirements-archive.md", skill_text)

    def test_requirements_archive_reference_documents_completion_summary(self) -> None:
        reference = ROOT / "skills" / "e2e-dev-harness" / "references" / "requirements-archive.md"
        text = reference.read_text(encoding="utf-8")

        self.assertIn("docs/agent-runs/<run>/requirements-archive.md", text)
        self.assertIn("Acceptance Criteria Status", text)
        self.assertIn("Promoted Memory Entries", text)
        self.assertIn("--requirements-archive", text)

    def test_review_profile_reference_documents_project_discovery_and_extends(self) -> None:
        reference = ROOT / "skills" / "e2e-dev-harness" / "references" / "review-profiles.md"
        text = reference.read_text(encoding="utf-8")

        self.assertIn(".e2e/review-profile.json", text)
        self.assertIn("docs/review-profile.json", text)
        self.assertIn("extends", text)
        self.assertIn("severity", text)
        self.assertIn("security-heavy", text)
        self.assertIn("api-first", text)

    def test_common_review_issues_reference_exists(self) -> None:
        reference = ROOT / "skills" / "e2e-dev-harness" / "references" / "common-review-issues.md"
        text = reference.read_text(encoding="utf-8")

        self.assertIn("Issue ID", text)
        self.assertIn("Criteria", text)
        self.assertIn("Examples", text)
        self.assertIn("code-path-trace-gap", text)
        self.assertIn("weak-completion-evidence", text)
        self.assertIn("impact-summary-overload", text)
        self.assertNotRegex(text, r"[\u4e00-\u9fff]")

    def test_readme_documents_hook_configuration(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Hook Configuration", text)
        self.assertIn("claude-code-settings.example.json", text)
        self.assertIn("codex-pre-action.example.json", text)
        self.assertIn("gemini-pre-action.example.json", text)
        self.assertIn("opencode-plugin.example.js", text)
        self.assertIn(".opencode/plugins", text)
        self.assertIn("phase_guard.py", text)
        self.assertIn(".phase-lock", text)
        self.assertIn("templates", text)

    def test_github_actions_harness_is_windows_first(self) -> None:
        text = (ROOT / "skills" / "e2e-dev-harness" / "ci" / "github-actions-harness.yml").read_text(encoding="utf-8")

        self.assertIn("runs-on: windows-latest", text)
        self.assertIn("shell: pwsh", text)
        self.assertNotIn("ubuntu-latest", text)

    def test_bundled_review_profiles_have_guidance_metadata(self) -> None:
        for name in ("default", "security-heavy", "api-first"):
            with self.subTest(profile=name):
                profile, blocked, path, source, chain = reviewer_gate.load_review_profile(ROOT, name)

                self.assertEqual([], blocked)
                self.assertTrue(path and path.replace("\\", "/").endswith(f"{name}.json"))
                self.assertEqual("explicit", source)
                self.assertTrue(chain)
                for phase, items in profile["required_checklist"].items():
                    self.assertTrue(items, phase)
                    for item in items:
                        self.assertIn("description", item)
                        self.assertIn("severity", item)
                        self.assertIn("references", item)

    def test_tdd_reference_documents_audit_field_template(self) -> None:
        text = (ROOT / "skills" / "e2e-dev-harness" / "references" / "tdd-java-spring.md").read_text(encoding="utf-8")

        self.assertIn("createdAt", text)
        self.assertIn("updatedAt", text)
        self.assertIn("createdBy", text)

    def test_skill_body_is_concise_for_progressive_disclosure(self) -> None:
        skill_text = (ROOT / "skills" / "e2e-dev-harness" / "SKILL.md").read_text(encoding="utf-8")
        body = skill_text.split("---", 2)[-1]
        words = body.split()
        long_lines = [
            line
            for line in body.splitlines()
            if len(line) > 240 and not line.startswith("description:")
        ]

        self.assertLessEqual(len(words), 2200)
        self.assertEqual([], long_lines)

    def test_compacted_skill_keeps_hard_gate_navigation(self) -> None:
        skill_text = (ROOT / "skills" / "e2e-dev-harness" / "SKILL.md").read_text(encoding="utf-8")

        required_terms = [
            "Superpowers",
            "GitNexus",
            "Graphify",
            "R1/R2/R3",
            "Coverage Reviewer",
            "single-review",
            "rework",
            "memory",
            "agent-instructions.md",
            "agent-orchestration.md",
            "implementation-gates.md",
            "kg-tool-selection.md",
            "memory-integration.md",
            "tdd-java-spring.md",
        ]

        for term in required_terms:
            with self.subTest(term=term):
                self.assertIn(term, skill_text)


class SuperpowersProbeCompatibilityTests(unittest.TestCase):
    def test_discovers_superpowers_in_claude_code_skills_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            skills = home / ".claude" / "skills"
            for name in (
                "using-superpowers",
                "brainstorming",
                "writing-plans",
                "test-driven-development",
            ):
                path = skills / name / "SKILL.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"---\nname: {name}\ndescription: test\n---\n", encoding="utf-8")

            with (
                patch.dict(superpowers_probe.os.environ, {"SUPERPOWERS_SKILLS_DIR": "", "SUPERPOWERS_ROOT": ""}, clear=False),
                patch.object(superpowers_probe.Path, "home", return_value=home),
            ):
                result = superpowers_probe.discover()

        self.assertTrue(result["available"], result)
        self.assertTrue(any(".claude" in path.replace("\\", "/") for path in result["found"].values()))


class UnifiedCliTests(unittest.TestCase):
    REVIEW_CHECKLIST = ImplementationGateTests.REVIEW_CHECKLIST

    def default_review_checklist(self, phase: str) -> str:
        return "\n".join(f"- [x] {item}: checked." for item in self.REVIEW_CHECKLIST.get(phase, []))

    def write_semantic_reviews(self, repo: Path) -> Path:
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

    def test_align_prepare_scopes_warns_when_explicit_scopes_differ(self) -> None:
        agent_scope, service_scope, notes = e2e_dev_harness.align_prepare_scopes("discovery", "affected")

        self.assertEqual("discovery", agent_scope)
        self.assertEqual("affected", service_scope)
        self.assertTrue(any("differ" in note for note in notes))

    def test_prepare_reuses_single_knowledge_graph_detection(self) -> None:
        facts = {
            "poms": ["pom.xml"],
            "root_modules": [],
            "spring_entrypoints": [],
            "spring_configs": [],
            "design_docs_or_media_count": 0,
            "design_docs_or_media_sample": [],
            "graphify_graph": "graphify-out/graph.json",
            "graphify_graph_exists": False,
            "service_candidates": [],
            "multi_service": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "AGENT.md").write_text("# Root\n", encoding="utf-8")
            calls = []
            args = SimpleNamespace(
                repo=repo,
                design_doc=None,
                path=None,
                service=None,
                agent_mode="off",
                agent_scope="auto",
                include_agent_content=False,
                max_agent_chars=12000,
                max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
                superpowers_mode="off",
                memory_mode="off",
                agent_orchestration_mode="auto",
                service_scope="discovery",
                agent_run_dir=None,
                run_date="2026-05-23",
                kg_mode="auto",
                dependency_scan_mode="off",
                write_dependency_report=False,
                dependency_output_dir=None,
                status_file=None,
            )

            def fake_detect(path: Path) -> dict:
                calls.append(path)
                return facts

            with patch.object(e2e_dev_harness.kg_refresh, "detect", side_effect=fake_detect):
                code, result = e2e_dev_harness.prepare(args)

        self.assertEqual(0, code)
        self.assertEqual(1, len(calls))
        self.assertEqual("discovery", result["orchestration"]["selected_mode"])
        self.assertEqual([], result["orchestration"]["agents"])

    def test_prepare_runs_gitnexus_first_dependency_scan(self) -> None:
        facts = {
            "poms": ["pom.xml"],
            "root_modules": [],
            "spring_entrypoints": [],
            "spring_configs": [],
            "design_docs_or_media_count": 0,
            "design_docs_or_media_sample": [],
            "graphify_graph": "graphify-out/graph.json",
            "graphify_graph_exists": False,
            "service_candidates": ["services/order-service", "services/payment-service"],
            "multi_service": True,
        }
        dependency_result = {
            "ready": True,
            "tool_priority": ["gitnexus", "deterministic-scan", "graphify"],
            "dependencies": [],
            "unresolved_questions": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "AGENT.md").write_text("# Root\n", encoding="utf-8")
            args = SimpleNamespace(
                repo=repo,
                design_doc=None,
                path=None,
                service=None,
                agent_mode="off",
                agent_scope="auto",
                include_agent_content=False,
                max_agent_chars=12000,
                max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
                superpowers_mode="off",
                memory_mode="off",
                agent_orchestration_mode="off",
                service_scope="discovery",
                agent_run_dir=None,
                run_date="2026-05-23",
                kg_mode="auto",
                dependency_scan_mode="strict",
                write_dependency_report=False,
                dependency_output_dir=None,
                status_file=None,
            )

            with (
                patch.object(e2e_dev_harness.kg_refresh, "detect", return_value=facts),
                patch.object(e2e_dev_harness.cross_service_dependency_scan, "scan", return_value=dependency_result) as scan,
            ):
                code, result = e2e_dev_harness.prepare(args)

        self.assertEqual(0, code)
        scan.assert_called_once()
        self.assertEqual("strict", scan.call_args.kwargs["gitnexus_mode"])
        self.assertEqual(["gitnexus", "deterministic-scan", "graphify"], result["cross_service_dependencies"]["tool_priority"])

    def test_dependency_report_recommends_affected_services_for_plan(self) -> None:
        facts = {
            "service_candidates": ["services/order-service", "services/payment-service", "services/catalog-service"],
            "multi_service": True,
            "design_docs_or_media_count": 0,
            "spring_entrypoints": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            report = repo / "knowledge-graph" / "cross-service-dependencies.json"
            report.parent.mkdir(parents=True)
            report.write_text(
                json.dumps(
                    {
                        "ready": True,
                        "dependencies": [
                            {
                                "kind": "http",
                                "source_service": "services/order-service",
                                "target_service": "services/payment-service",
                            }
                        ],
                        "unresolved_questions": [],
                    }
                ),
                encoding="utf-8",
            )

            result = e2e_dev_harness.orchestration_status(
                repo,
                "auto",
                None,
                service_scope="auto",
                facts=facts,
                dependency_report=report,
            )

        self.assertEqual("affected", result["resolved_service_scope"])
        self.assertEqual(["services/order-service", "services/payment-service"], result["selected_services"])

    def test_cli_gate_accepts_rework_dir(self) -> None:
        design_text = textwrap.dedent(
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
            - Required Red Test: QuoteServiceTest covers AC-1
            - Evidence: Completion review found the code path missing.
            - Exit Criteria: Completion gate passes after code refs are verified.
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
            rework_dir = repo / "docs" / "agent-runs" / "run" / "rework"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            rework_dir.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            (rework_dir / "rework-001.md").write_text(rework, encoding="utf-8")
            args = SimpleNamespace(
                repo=repo,
                design_doc=design,
                kg_status_file=kg,
                phase="completion",
                red_test_evidence=red,
                coverage_matrix=matrix,
                unit_test_evidence=unit,
                business_review=review,
                memory_updates=None,
                dependency_report=None,
                rework_dir=[rework_dir],
                skip_spring_static_check=True,
                status_file=None,
            )

            code, result = e2e_dev_harness.gate(args)

        self.assertEqual(2, code)
        self.assertEqual(1, result["rework"]["open_count"])

    def test_cli_gate_accepts_implementation_manifest(self) -> None:
        design_text = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Add a quote endpoint.

            ## Scope
            - services/sample-service

            ## Use Cases
            - Return a quote.

            ## Acceptance Criteria
            - AC-1 QuoteService returns a quote.

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
            | AC-1 | Quote is returned | Create quote | services/sample-service | QuoteServiceTest | QuoteService | reviewed | covered |
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
            artifact = repo / "services/sample-service/src/main/java/com/example/QuoteService.java"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("class QuoteService {}\n", encoding="utf-8")
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            approval = repo / "approval.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")
            approval.write_text("Approval: user-approved\n", encoding="utf-8")
            review_dir = self.write_semantic_reviews(repo)
            args = SimpleNamespace(
                repo=repo,
                design_doc=design,
                kg_status_file=kg,
                phase="completion",
                red_test_evidence=red,
                coverage_matrix=matrix,
                unit_test_evidence=unit,
                business_review=review,
                memory_updates=None,
                dependency_report=None,
                rework_dir=None,
                review_dir=[review_dir],
                require_semantic_reviews=False,
                implementation_manifest=manifest_path,
                skip_spring_static_check=True,
                no_harness_state=True,
                harness_state_approval=approval,
                status_file=None,
            )

            code, result = e2e_dev_harness.gate(args)

        self.assertEqual(0, code, result.get("blocked_reasons"))
        self.assertTrue(result["implementation_manifest"]["ready"])

    def test_cli_gate_accepts_dependency_report(self) -> None:
        design_text = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Call payment service when an order is created.

            ## Scope
            - services/order-service
            - services/payment-service

            ## Use Cases
            - order-service calls payment-service over HTTP.

            ## Acceptance Criteria
            - AC-1 Payment callback is delivered.

            ## Change Logic
            - Current behavior: order creation does not call payment.
            - Target behavior: order creation invokes payment callback flow.
            - Runtime path: OrderController -> OrderService -> PaymentClient -> PaymentController.
            - State/data effect: sends payment request payload and stores callback status.

            ## Impact Summary
            - Source: GitNexus impact + dependency scanner
            - Raw Evidence: docs/agent-runs/run/evidence/impact-analysis.json

            | type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
            | --- | --- | --- | --- | --- | --- |
            | HTTP | order-service -> payment-service callback | services/order-service, services/payment-service | AC-1 | PaymentCallbackTest; contract ACK | high |

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
            | AC-1 | Payment callback is delivered | HTTP flow | services/order-service, services/payment-service | PaymentCallbackTest | PaymentClient, PaymentController | reviewed | covered |
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
                "services/order-service/src/main/java/com/example/PaymentClient.java",
                "services/payment-service/src/main/java/com/example/PaymentController.java",
            ):
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("class Placeholder {}\n", encoding="utf-8")
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            dependency_report.parent.mkdir(parents=True, exist_ok=True)
            design.write_text(design_text, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            write_command_evidence(red, "mvn test -Dtest=PaymentCallbackTest", exit_code=1)
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            manifest_path.write_text(
                textwrap.dedent(
                    """
                    | id | module | artifact | artifact_type | source | required | tests | status | evidence |
                    | --- | --- | --- | --- | --- | --- | --- | --- | --- |
                    | IM-1 | services/order-service | services/order-service/src/main/java/com/example/PaymentClient.java | client | AC-1 dependency-report | yes | PaymentCallbackTest | verified | done |
                    | IM-2 | services/payment-service | services/payment-service/src/main/java/com/example/PaymentController.java | controller | AC-1 dependency-report | yes | PaymentCallbackTest | verified | done |
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
            args = SimpleNamespace(
                repo=repo,
                design_doc=design,
                kg_status_file=kg,
                phase="completion",
                red_test_evidence=red,
                coverage_matrix=matrix,
                unit_test_evidence=unit,
                business_review=review,
                memory_updates=None,
                dependency_report=dependency_report,
                implementation_manifest=manifest_path,
                rework_dir=None,
                review_dir=[review_dir],
                require_semantic_reviews=False,
                skip_spring_static_check=True,
                no_harness_state=True,
                harness_state_approval=approval,
                status_file=None,
            )

            code, result = e2e_dev_harness.gate(args)

        self.assertEqual(0, code, result.get("blocked_reasons"))
        self.assertTrue(result["dependency_report"]["ready"])

    def test_verify_strict_workflow_blocks_skip_maven(self) -> None:
        args = SimpleNamespace(
            repo=Path("."),
            design_doc=None,
            path=None,
            service=None,
            agent_mode="off",
            agent_scope="auto",
            include_agent_content=False,
            max_agent_chars=12000,
            max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
            superpowers_mode="auto",
            memory_mode="off",
            agent_orchestration_mode="off",
            service_scope="discovery",
            agent_run_dir=None,
            run_date="2026-05-23",
            kg_mode="auto",
            dependency_scan_mode="auto",
            write_dependency_report=True,
            dependency_output_dir=None,
            run_gate=False,
            phase="planning",
            kg_status_file=None,
            red_test_evidence=None,
            coverage_matrix=None,
            unit_test_evidence=None,
            business_review=None,
            memory_updates=None,
            dependency_report=None,
            rework_dir=None,
            skip_spring_static_check=False,
            skip_maven=True,
            strict_workflow=True,
            workflow_approval=None,
            status_file=None,
        )
        prepare_result = {
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
            },
        }

        with patch.object(e2e_dev_harness, "prepare", return_value=(0, prepare_result)):
            code, result = e2e_dev_harness.verify(args)

        self.assertEqual(2, code)
        self.assertFalse(result["workflow_guard"]["ready"])
        self.assertTrue(any("Maven" in reason for reason in result["workflow_guard"]["blocked_reasons"]))

    def test_verify_reports_missing_maven_without_traceback(self) -> None:
        args = SimpleNamespace(
            repo=Path("."),
            design_doc=None,
            path=None,
            service=None,
            agent_mode="off",
            agent_scope="auto",
            include_agent_content=False,
            max_agent_chars=12000,
            max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
            superpowers_mode="auto",
            memory_mode="off",
            agent_orchestration_mode="off",
            service_scope="discovery",
            agent_run_dir=None,
            run_date="2026-05-23",
            kg_mode="auto",
            dependency_scan_mode="auto",
            write_dependency_report=True,
            dependency_output_dir=None,
            run_gate=False,
            phase="planning",
            kg_status_file=None,
            red_test_evidence=None,
            coverage_matrix=None,
            unit_test_evidence=None,
            business_review=None,
            memory_updates=None,
            dependency_report=None,
            implementation_manifest=None,
            rework_dir=None,
            skip_spring_static_check=False,
            skip_maven=False,
            strict_workflow=False,
            workflow_approval=None,
            status_file=None,
            module=None,
        )
        prepare_result = {"blocked": False}

        with (
            patch.object(e2e_dev_harness, "prepare", return_value=(0, prepare_result)),
            patch.object(e2e_dev_harness.shutil, "which", return_value=None),
            patch.object(e2e_dev_harness.subprocess, "run") as subprocess_run,
        ):
            code, result = e2e_dev_harness.verify(args)

        self.assertEqual(127, code)
        self.assertEqual(127, result["maven"]["exit_code"])
        self.assertIn("Maven executable not found", result["maven"]["stderr_tail"])
        subprocess_run.assert_not_called()

    def test_verify_reports_maven_timeout_without_hanging(self) -> None:
        args = SimpleNamespace(
            repo=Path("."),
            design_doc=None,
            path=None,
            service=None,
            agent_mode="off",
            agent_scope="auto",
            include_agent_content=False,
            max_agent_chars=12000,
            max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
            superpowers_mode="auto",
            memory_mode="off",
            agent_orchestration_mode="off",
            service_scope="discovery",
            agent_run_dir=None,
            run_date="2026-05-23",
            kg_mode="auto",
            dependency_scan_mode="auto",
            write_dependency_report=True,
            dependency_output_dir=None,
            run_gate=False,
            phase="planning",
            kg_status_file=None,
            red_test_evidence=None,
            coverage_matrix=None,
            unit_test_evidence=None,
            business_review=None,
            memory_updates=None,
            dependency_report=None,
            implementation_manifest=None,
            rework_dir=None,
            skip_spring_static_check=False,
            skip_maven=False,
            strict_workflow=False,
            workflow_approval=None,
            status_file=None,
            module=None,
        )

        with (
            patch.object(e2e_dev_harness, "prepare", return_value=(0, {"blocked": False})),
            patch.object(e2e_dev_harness.shutil, "which", return_value="mvn"),
            patch.object(
                e2e_dev_harness.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["mvn", "test"], 600, output="partial"),
            ),
        ):
            code, result = e2e_dev_harness.verify(args)

        self.assertEqual(124, code)
        self.assertEqual(124, result["maven"]["exit_code"])
        self.assertIn("timed out", result["maven"]["stderr_tail"])


class MemorySafetyTests(unittest.TestCase):
    def test_validate_proposed_updates_blocks_local_path(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Use tool at C:\\Users\\person\\secret.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("local path" in r.lower() for r in result["blocked_reasons"]))

    def test_validate_proposed_updates_blocks_secret(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Use api_key=sk-123456 for external service.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("secret" in r.lower() for r in result["blocked_reasons"]))

    def test_validate_proposed_updates_blocks_todo(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: TODO confirm timeout value.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("todo" in r.lower() or "tbd" in r.lower() for r in result["blocked_reasons"]))

    def test_validate_proposed_updates_blocks_exact_duplicate(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Quote timeout is 3 seconds.

            ### M-2

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Quote timeout is 3 seconds.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("duplicate" in r.lower() for r in result["blocked_reasons"]))

    def test_validate_proposed_updates_blocks_existing_memory_duplicate(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Quote timeout is 3 seconds.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            memory_capture.append_memory(repo, "decision", "user-approved", "approved", "Quote timeout is 3 seconds.")
            path = repo / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path, repo)

        self.assertFalse(result["ready"])
        self.assertTrue(any("already exists" in r.lower() for r in result["blocked_reasons"]))

    def test_validate_proposed_updates_warns_on_fuzzy_duplicate(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Quote timeout remains three seconds for all services.

            ### M-2

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Quote timeout remains three seconds for all the services.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path)

        self.assertTrue(any("similar" in w.lower() for w in result["warnings"]))

    def test_append_memory_blocks_dirty_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)

            result = memory_capture.append_memory(
                repo, "decision", "user-approved", "approved",
                "Use secret at C:\\Users\\admin\\config with api_key=abc123",
            )

        self.assertIsNone(result["path"])
        self.assertTrue(len(result["blocked_reasons"]) > 0)

    def test_memory_status_strict_calls_validate_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)

            result = e2e_dev_harness.memory_status(repo, "strict")

        self.assertTrue(result["enabled"])
        self.assertIn("blocked_reasons", result)
        self.assertEqual("strict", result["mode"])


class AcceptanceCriteriaExtractionTests(unittest.TestCase):
    def test_extracts_ac_ids_from_design(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Acceptance Criteria

            - AC-1 Quote is returned within 3 seconds.
            - AC-2 Error response includes code and message.
            - AC3 Service health check returns 200.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            ids = clarification_gate.extract_acceptance_criteria(path)

        self.assertEqual(["AC-1", "AC-2", "AC-3"], ids)

    def test_generates_ids_for_unnumbered_acceptance_bullets(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Acceptance Criteria

            - Quote is returned within 3 seconds.
            - Error response includes code and message.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            ids = clarification_gate.extract_acceptance_criteria(path)

        self.assertEqual(["AC-1", "AC-2"], ids)

    def test_returns_empty_when_no_acceptance_section(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Goal

            - Return a quote.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            ids = clarification_gate.extract_acceptance_criteria(path)

        self.assertEqual([], ids)


class CoverageGateAcCheckTests(unittest.TestCase):
    def test_blocks_missing_design_doc_when_ac_check_requested(self) -> None:
        markdown = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote returned | Create quote | services/a | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            matrix = repo / "coverage.md"
            unit = repo / "unit.txt"
            review = repo / "business.md"
            matrix.write_text(markdown, encoding="utf-8")
            write_command_evidence(unit)
            review.write_text("Reviewed.\n", encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review, repo / "missing-design.md")

        self.assertFalse(result["ready"])
        self.assertTrue(any("design document not found" in reason.lower() for reason in result["blocked_reasons"]))

    def test_blocks_missing_generated_acs_from_design(self) -> None:
        markdown = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote returned | Create quote | services/a | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        design = textwrap.dedent(
            """
            # Feature

            ## Acceptance Criteria

            - Quote is returned.
            - Error response includes code.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            matrix = repo / "coverage.md"
            unit = repo / "unit.txt"
            review = repo / "business.md"
            design_path = repo / "design.md"
            matrix.write_text(markdown, encoding="utf-8")
            write_command_evidence(unit)
            review.write_text("Reviewed.\n", encoding="utf-8")
            design_path.write_text(design, encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review, design_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("AC-2" in reason for reason in result["blocked_reasons"]))

    def test_blocks_missing_acs_from_design(self) -> None:
        markdown = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote returned | Create quote | services/a | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        design = textwrap.dedent(
            """
            # Feature

            ## Acceptance Criteria

            - AC-1 Quote is returned.
            - AC-2 Error response includes code.
            - AC-3 Health check returns 200.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            matrix = repo / "coverage.md"
            unit = repo / "unit.txt"
            review = repo / "business.md"
            design_path = repo / "design.md"
            matrix.write_text(markdown, encoding="utf-8")
            write_command_evidence(unit)
            review.write_text("Reviewed.\n", encoding="utf-8")
            design_path.write_text(design, encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review, design_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("AC-2" in reason for reason in result["blocked_reasons"]))

    def test_blocks_messaging_ac_without_sender_completion_evidence(self) -> None:
        markdown = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Publish DMQ callback notification | Payment succeeds | services/payment-service | PaymentServiceTest | PaymentService | reviewed | covered |
            """
        ).strip()
        design = textwrap.dedent(
            """
            # Feature

            ## Acceptance Criteria

            - AC-1 Publish DMQ callback notification after payment succeeds.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            matrix = repo / "coverage.md"
            unit = repo / "unit.txt"
            review = repo / "business.md"
            design_path = repo / "design.md"
            matrix.write_text(markdown, encoding="utf-8")
            write_command_evidence(unit)
            review.write_text("Reviewed.\n", encoding="utf-8")
            design_path.write_text(design, encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review, design_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("messaging AC AC-1" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("sender" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertTrue(any("payload" in reason.lower() for reason in result["blocked_reasons"]))

    def test_passes_messaging_ac_with_sender_and_payload_evidence(self) -> None:
        markdown = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Publish DMQ callback notification | Payment succeeds | services/payment-service | PaymentCallbackDmqSenderTest verifies topic tag payload publish | PaymentService#complete -> PaymentCallbackDmqSender.send | reviewed | covered |
            """
        ).strip()
        design = textwrap.dedent(
            """
            # Feature

            ## Acceptance Criteria

            - AC-1 Publish DMQ callback notification after payment succeeds.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            matrix = repo / "coverage.md"
            unit = repo / "unit.txt"
            review = repo / "business.md"
            design_path = repo / "design.md"
            matrix.write_text(markdown, encoding="utf-8")
            write_command_evidence(unit)
            review.write_text("Reviewed.\n", encoding="utf-8")
            design_path.write_text(design, encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review, design_path)

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_passes_when_all_acs_covered(self) -> None:
        markdown = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote returned | Create quote | services/a | QuoteTest | QuoteService | reviewed | covered |
            | AC-2 | Error code | Error case | services/a | ErrorTest | ErrorService | reviewed | covered |
            """
        ).strip()
        design = textwrap.dedent(
            """
            # Feature

            ## Acceptance Criteria

            - AC-1 Quote is returned.
            - AC-2 Error response includes code.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            matrix = repo / "coverage.md"
            unit = repo / "unit.txt"
            review = repo / "business.md"
            design_path = repo / "design.md"
            matrix.write_text(markdown, encoding="utf-8")
            write_command_evidence(unit)
            review.write_text("Reviewed.\n", encoding="utf-8")
            design_path.write_text(design, encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review, design_path)

        self.assertTrue(result["ready"])


class HashCommandTests(unittest.TestCase):
    def test_hash_entry_matches_handoff_gate_recomputation(self) -> None:
        from e2e_harness.cli.commands import hash_artifacts

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = repo / "docs" / "agent-runs" / "run" / "evidence" / "impact-summary.md"
            target.parent.mkdir(parents=True)
            # CRLF on purpose: byte-exact hashing must not normalize line endings.
            target.write_bytes(b"# Impact Summary\r\nrisk: LOW\r\n")

            exit_code, result = hash_artifacts.run(repo, [target])

            self.assertEqual(exit_code, 0)
            self.assertTrue(result["ready"])
            self.assertEqual(result["blocked_reasons"], [])
            entry = result["hash_entries"][0]
            # The gate recomputes hashes via hashlib.sha256(read_bytes()); the
            # command MUST produce the identical digest or the gate will reject it.
            expected = hashlib.sha256(target.read_bytes()).hexdigest()
            self.assertEqual(entry["sha256"], expected)
            self.assertEqual(entry["path"], "docs/agent-runs/run/evidence/impact-summary.md")
            self.assertEqual(
                entry["frontmatter_line"],
                f"docs/agent-runs/run/evidence/impact-summary.md sha256:{expected}",
            )

    def test_hash_missing_file_blocks(self) -> None:
        from e2e_harness.cli.commands import hash_artifacts

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            exit_code, result = hash_artifacts.run(repo, [repo / "nope.md"])

            self.assertEqual(exit_code, 2)
            self.assertFalse(result["ready"])
            self.assertTrue(result["hash_entries"] == [])
            self.assertTrue(any("nope.md" in reason for reason in result["blocked_reasons"]))

    def test_hash_cli_emits_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = repo / "req.md"
            target.write_bytes(b"user request\n")
            argv = [
                "e2e_dev_harness.py",
                "hash",
                str(repo),
                "--path",
                "req.md",
            ]
            stdout = io.StringIO()
            with patch.object(sys, "argv", argv), redirect_stdout(stdout):
                code = e2e_dev_harness.main()
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, code)
        expected = hashlib.sha256(b"user request\n").hexdigest()
        # The compact output contract must surface the hash entries, not strip them.
        self.assertEqual(payload["hash_entries"][0]["frontmatter_line"], f"req.md sha256:{expected}")


if __name__ == "__main__":
    unittest.main()
