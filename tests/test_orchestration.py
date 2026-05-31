"""Orchestration plan, artifact tests, and auto-transition."""
from __future__ import annotations

import io
import hashlib
import json
import os
import subprocess
import sys
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

import orchestration_plan  # noqa: E402
import auto_transition  # noqa: E402
import phase_guard  # noqa: E402
import run_state  # noqa: E402
import run_summary  # noqa: E402
import session_checkpoint  # noqa: E402
import e2e_dev_harness  # noqa: E402
import install_hooks  # noqa: E402
import harness_stop_guard  # noqa: E402
import agent_instructions  # noqa: E402
import agent_scheduler  # noqa: E402
import artifact_registry  # noqa: E402
import context_pack  # noqa: E402
import dispatcher  # noqa: E402
import execution_trace  # noqa: E402
import harness_policy  # noqa: E402
import harness_verify  # noqa: E402
import implementation_gate  # noqa: E402
import service_design_gate  # noqa: E402
import task_tier  # noqa: E402


def implementation_gate_payload(red_path: Path) -> dict:
    return {
        "phase": "implementation",
        "ready": True,
        "knowledge_graph_status_loaded": True,
        "tdd": {"ready": True, "red_evidence": str(red_path)},
        "semantic_reviews": {"ready": True, "covered_phases": ["design", "test"]},
    }


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
              - {path.as_posix()}
            input_hashes:
              - user-request sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
            output_hashes:
              - {path.as_posix()} sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
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
            schedule = json.loads(Path(result["agent_schedule"]).read_text(encoding="utf-8"))
            guard = phase_guard.validate_action(repo, "Write", [Path("services/refund/src/main/java/RefundService.java")])

        self.assertEqual(0, code)
        self.assertTrue(design_exists)
        self.assertIn("## Restated Intent", design_text)
        self.assertEqual("CREATED", state["lifecycle"])
        self.assertEqual("code-write-locked", lock["state"])
        self.assertEqual("bootstrap", schedule["selected_mode"])
        self.assertEqual("requirements-clarifier", schedule["tasks"][0]["agent"])
        self.assertEqual("clarify", schedule["tasks"][0]["phase"])
        self.assertTrue(schedule["tasks"][0]["role_template"])
        self.assertFalse(guard["ready"])

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

    def test_runtime_hook_status_accepts_ready_opencode_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            install_hooks.install(repo, "opencode")

            result = e2e_dev_harness.runtime_hook_status(repo)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("opencode", result["runtime"])

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
        schedule = orchestration_plan.agent_schedule("single", [], agents)
        self.assertTrue(schedule["require_role_templates"])
        for task in schedule["tasks"]:
            self.assertIn("agent-roles/", task["role_template"])

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
            - jeepay-core: constants and params
            - jeepay-service: channel config service
            - jeepay-payment: payment, notice, refund services

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
        self.assertIn("jeepay-service", result["handoff_artifacts"]["service_plans"])
        self.assertIn("code-developer-jeepay-service", [agent["name"] for agent in result["agents"]])
        code_agent = next(agent for agent in result["agents"] if agent["name"] == "code-developer-jeepay-service")
        service_paths = result["handoff_artifacts"]["service_plans"]["jeepay-service"]
        self.assertIn(service_paths["service_design"], code_agent["inputs"])
        self.assertIn(service_paths["test_impact_plan"], code_agent["inputs"])
        self.assertEqual("e2e-dev-harness.agent-schedule.v1", result["agent_schedule"]["schema"])
        self.assertTrue(any(task["parallel_group"] == "service:jeepay-service" for task in result["agent_schedule"]["tasks"]))

    def test_plan_archive_creates_handoffs_for_design_affected_root_modules(self) -> None:
        design_text = textwrap.dedent(
            """
            # VNPay

            ## Goal
            - Add VNPay channel.

            ## Affected services/modules
            - jeepay-core: constants and params
            - jeepay-service: channel config service
            - jeepay-payment: payment, notice, refund services

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
            self.assertTrue(any(item["type"] == "design_doc" for item in registry["artifacts"]))
            archive_text = (repo / result["handoff_artifacts"]["requirements_archive"]).read_text(encoding="utf-8")
            self.assertIn("Final Clarified Requirement", archive_text)
            self.assertIn("Acceptance Criteria Status", archive_text)
            impact_text = (repo / result["handoff_artifacts"]["impact_summary"]).read_text(encoding="utf-8")
            self.assertIn("Raw Evidence", impact_text)
            self.assertIn("affected callers/consumers", impact_text)
            for module in ("jeepay-core", "jeepay-service", "jeepay-payment"):
                paths = result["handoff_artifacts"]["service_plans"][module]
                self.assertTrue((repo / paths["service_design"]).exists())
                self.assertTrue((repo / paths["service_plan"]).exists())
                self.assertTrue((repo / paths["code_agent"]).exists())
                self.assertTrue((repo / paths["implementation_manifest"]).exists())
                self.assertTrue((repo / paths["test_impact_plan"]).exists())
                self.assertTrue((repo / paths["test_review_request"]).exists())
                self.assertTrue((repo / paths["implementation_review_request"]).exists())
                self.assertFalse((repo / paths["test_review"]).exists())
                self.assertFalse((repo / paths["implementation_review"]).exists())
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

        self.assertEqual("single", selected)
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

    def test_runtime_capabilities_mark_claude_code_as_subagent_dispatcher(self) -> None:
        result = dispatcher.runtime_capabilities("claude-code")

        self.assertTrue(result["supports_subagent"])
        self.assertTrue(result["supports_task_hook"])
        self.assertTrue(result["supports_isolated_review"])
        self.assertEqual("native-subagent", result["dispatch_mode"])

    def test_dispatch_next_claims_task_and_writes_context_pack_invocation_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            output = Path("docs/agent-runs/run/service-plans/order-service/code-agent.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "inputs": [handoff.as_posix()],
                                "outputs": [output.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_next(
                repo,
                schedule,
                state_path,
                runtime="claude-code",
                coordinator_agent="coordinator-agent",
                developer_session="coordinator-session",
            )
            schedule_data = json.loads(schedule.read_text(encoding="utf-8"))
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))
            context_pack_exists = (repo / result["context_pack"]).exists()
            invocation_exists = (repo / result["invocation_path"]).exists()

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("T10", result["task"]["id"])
        self.assertEqual("claimed", schedule_data["tasks"][0]["status"])
        self.assertEqual("code-developer-order-service", schedule_data["tasks"][0]["owner"])
        self.assertTrue(context_pack_exists)
        self.assertTrue(invocation_exists)
        self.assertEqual("worker_running", updated_state["dispatch"]["status"])
        self.assertEqual("T10", updated_state["dispatch"]["current_task_id"])
        self.assertIn("Task prompt", result["task_prompt"])
        self.assertIn("e2e-dev-harness isolated worker task", result["task_prompt"])

    def test_dispatch_next_budget_block_does_not_claim_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/use-case-designer.md")
            large_input = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, large_input)
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state("docs/agent-runs/run", "single-review", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED"),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T02",
                                "agent": "use-case-designer",
                                "phase": "design",
                                "role_group": "design",
                                "inputs": [large_input.as_posix()],
                                "outputs": ["docs/agent-runs/run/handoffs/02-use-case-designer.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="claude-code", max_chars=10)
            schedule_data = json.loads(schedule.read_text(encoding="utf-8"))

        self.assertFalse(result["ready"])
        self.assertTrue(any("Context pack" in reason for reason in result["blocked_reasons"]))
        self.assertEqual("planned", schedule_data["tasks"][0]["status"])
        self.assertNotIn("owner", schedule_data["tasks"][0])

    def test_dispatch_next_enters_waiting_dispatch_without_subagent_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state("docs/agent-runs/run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "PLANNED"),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "inputs": [],
                                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="manual")
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertFalse(result["ready"])
        self.assertEqual("waiting_dispatch", result["dispatch"]["status"])
        self.assertEqual("WAITING_DISPATCH", updated_state["lifecycle"])
        self.assertEqual("waiting_dispatch", updated_state["dispatch"]["status"])
        self.assertIn("manual_dispatch_packet", result)

    def test_dispatch_next_skips_blocked_task_and_claims_next_ready_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            ready_handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            missing_handoff = "docs/agent-runs/run/handoffs/missing.md"
            write_role_template(repo, role_template)
            write_ready_handoff(repo, ready_handoff)
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state("docs/agent-runs/run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED"),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "code-developer-blocked",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "inputs": [missing_handoff],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/blocked.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                            {
                                "id": "T02",
                                "agent": "code-developer-ready",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "inputs": [ready_handoff.as_posix()],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/code-agent.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="claude-code")
            schedule_data = json.loads(schedule.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("T02", result["task"]["id"])
        self.assertEqual("planned", schedule_data["tasks"][0]["status"])
        self.assertEqual("claimed", schedule_data["tasks"][1]["status"])
        self.assertTrue(any(item["task_id"] == "T01" for item in result["skipped_tasks"]))

    def test_dispatch_complete_runs_reviewer_gate_for_review_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            review = Path("docs/agent-runs/run/reviews/R1-design-review.md")
            role_template = Path("docs/agent-runs/run/agent-roles/semantic-reviewer.md")
            write_role_template(repo, role_template)
            (repo / review).parent.mkdir(parents=True, exist_ok=True)
            (repo / review).write_text("review evidence\n", encoding="utf-8")
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state("docs/agent-runs/run", "single-review", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED"),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T04",
                                "agent": "design-reviewer",
                                "phase": "r1-review",
                                "role_group": "review",
                                "inputs": ["docs/agent-runs/run/review-requests/R1-design-review-request.md"],
                                "outputs": [review.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "design-reviewer",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(dispatcher.reviewer_gate, "validate", return_value={"ready": True, "blocked_reasons": [], "warnings": [], "covered_phases": ["design"]}) as validate:
                result = dispatcher.dispatch_complete(repo, schedule, state_path, "T04", "design-reviewer", [review.as_posix()])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertIn("reviewer_gate", result)
        validate.assert_called_once()

    def test_dispatch_complete_restores_previous_lifecycle_after_waiting_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence, "requirements-agent")
            state = run_state.build_state("docs/agent-runs/run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "WAITING_DISPATCH")
            state["dispatch"] = {
                "status": "waiting_dispatch",
                "runtime": "manual",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
            }
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
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
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_complete(repo, schedule, state_path, "T01", "requirements-clarifier", [evidence.as_posix()])
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("CREATED", updated_state["lifecycle"])
        self.assertEqual("worker_completed", updated_state["dispatch"]["status"])

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

    def test_service_design_gate_blocks_mojibake_text(self) -> None:
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
                    - Explicitly out of scope: 鍏朵粬妯″潡

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
        self.assertTrue(any("mojibake" in reason for reason in result["blocked_reasons"]))

    def test_service_design_gate_cli_emits_utf8_json_on_windows_codepage(self) -> None:
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
                    - Explicitly out of scope: 鍏朵粬妯″潡

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

                    ## Test Impact
                    - mvn -pl services/order-service -am test
                    """
                ).strip(),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "cp936"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "service_design_gate.py"),
                    str(repo),
                    "--global-design",
                    str(design),
                    "--service-design-dir",
                    str(service_dir),
                    "--json",
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertNotEqual(0, completed.returncode)
        decoded = completed.stdout.decode("utf-8")
        self.assertIn("mojibake", decoded)

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

    def test_multi_implementation_gate_requires_claimed_service_tasks(self) -> None:
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
        self.assertTrue(any("must be claimed" in reason for reason in result["blocked_reasons"]))

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

    def test_run_state_blocks_verified_transition_without_completion_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            implementation_gate = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-gate.json"
            unit_evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit-test.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            implementation_gate.parent.mkdir(parents=True)
            red.write_text("expected failure\n", encoding="utf-8")
            implementation_gate.write_text(json.dumps(implementation_gate_payload(red)), encoding="utf-8")
            unit_evidence.write_text(json.dumps({"command": "mvn test", "exit_code": 0}), encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            implemented = run_state.transition_state(
                repo,
                state_path,
                "IMPLEMENTED",
                gate="implementation",
                gate_status="passed",
                evidence=implementation_gate,
            )

            result = run_state.transition_state(
                repo,
                state_path,
                "VERIFIED",
                gate="completion",
                gate_status="passed",
                evidence=unit_evidence,
            )

        self.assertTrue(implemented["ready"], implemented["blocked_reasons"])
        self.assertFalse(result["ready"])
        self.assertTrue(any("completion gate evidence" in reason for reason in result["blocked_reasons"]))

    def test_run_state_allows_verified_transition_with_completion_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            implementation_gate = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-gate.json"
            completion_gate = repo / "docs" / "agent-runs" / "run" / "evidence" / "completion-gate.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            implementation_gate.parent.mkdir(parents=True)
            red.write_text("expected failure\n", encoding="utf-8")
            implementation_gate.write_text(json.dumps(implementation_gate_payload(red)), encoding="utf-8")
            completion_gate.write_text(json.dumps({"phase": "completion", "ready": True}), encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            implemented = run_state.transition_state(
                repo,
                state_path,
                "IMPLEMENTED",
                gate="implementation",
                gate_status="passed",
                evidence=implementation_gate,
            )

            result = run_state.transition_state(
                repo,
                state_path,
                "VERIFIED",
                gate="completion",
                gate_status="passed",
                evidence=completion_gate,
            )

        self.assertTrue(implemented["ready"], implemented["blocked_reasons"])
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("VERIFIED", result["lifecycle"])

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

    def test_agent_task_claim_blocks_same_agent_across_design_test_code_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule_path.parent.mkdir(parents=True)
            schedule = {
                "schema": "e2e-dev-harness.agent-schedule.v1",
                "tasks": [
                    {
                        "id": "T01",
                        "agent": "use-case-designer",
                        "phase": "design",
                        "role_group": "design",
                        "status": "completed",
                        "owner": "agent-alpha",
                    },
                    {
                        "id": "T02",
                        "agent": "test-case-developer",
                        "phase": "tdd-red",
                        "role_group": "test",
                        "status": "planned",
                    },
                    {
                        "id": "T03",
                        "agent": "code-developer",
                        "phase": "implement",
                        "role_group": "code",
                        "status": "planned",
                    },
                ],
            }
            schedule_path.write_text(json.dumps(schedule), encoding="utf-8")

            blocked = agent_scheduler.claim(repo, schedule_path, "T02", "agent-alpha")
            allowed = agent_scheduler.claim(repo, schedule_path, "T02", "agent-beta")

        self.assertFalse(blocked["ready"])
        self.assertTrue(any("cannot own both test and design" in reason for reason in blocked["blocked_reasons"]))
        self.assertTrue(allowed["ready"], allowed["blocked_reasons"])

    def test_agent_task_claim_requires_ready_input_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff = repo / "docs" / "agent-runs" / "run" / "handoffs" / "01-requirements-clarifier.md"
            handoff.parent.mkdir(parents=True)
            handoff.write_text(e2e_dev_harness.handoff_text("requirements-clarifier"), encoding="utf-8")
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "status": "completed",
                            },
                            {
                                "id": "T02",
                                "agent": "use-case-designer",
                                "phase": "design",
                                "role_group": "design",
                                "status": "planned",
                                "depends_on_phases": ["clarify"],
                                "inputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = agent_scheduler.claim(repo, schedule_path, "T02", "agent-designer")

        self.assertFalse(result["ready"])
        self.assertTrue(any("input handoff is not ready" in reason for reason in result["blocked_reasons"]))

    def test_agent_task_claim_requires_existing_role_template_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule_path.parent.mkdir(parents=True)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "code-developer",
                                "phase": "implement",
                                "role_group": "code",
                                "status": "planned",
                                "role_template": "docs/agent-runs/run/agent-roles/code-developer.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            missing = agent_scheduler.claim(repo, schedule_path, "T01", "agent-code")
            template = repo / "docs" / "agent-runs" / "run" / "agent-roles" / "code-developer.md"
            template.parent.mkdir(parents=True)
            template.write_text(e2e_dev_harness.role_template_text("code-developer"), encoding="utf-8")
            ok = agent_scheduler.claim(repo, schedule_path, "T01", "agent-code")

        self.assertFalse(missing["ready"])
        self.assertTrue(any("role_template is missing" in reason for reason in missing["blocked_reasons"]))
        self.assertTrue(ok["ready"], ok["blocked_reasons"])

    def test_create_archive_writes_role_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

            created = e2e_dev_harness.create_handoff_files(repo, artifacts)
            template = repo / artifacts["role_templates"]["code-developer"]
            text = template.read_text(encoding="utf-8")

        self.assertTrue(any("agent-roles" in path for path in created))
        self.assertIn("## Role Boundary", text)
        self.assertIn("## Forbidden", text)
        self.assertIn("Do not alter requirements", text)

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
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)
            args = SimpleNamespace(
                repo=repo,
                design_doc=Path("docs/design/feature.md"),
                run_state=state_path,
                status_file=None,
            )

            code, result = e2e_dev_harness.clarify(args)
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(0, code, result)
        self.assertEqual("CLARIFIED", updated["lifecycle"])
        self.assertEqual("passed", updated["gates"]["clarification"])
        self.assertTrue(result["run_state_transition"]["ready"])
        self.assertTrue(result["blocked_next_without_plan"])
        self.assertFalse(result["next_required"]["code_writes_allowed"])

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

    def test_phase_guard_blocks_direct_harness_control_file_edit(self) -> None:
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
        self.assertIn("clarify", " ".join(result["allowed_actions"]).lower())

    def test_phase_guard_blocks_apply_patch_delete_of_harness_control_file(self) -> None:
        patch_text = "*** Begin Patch\n*** Delete File: docs/agent-runs/run/run-state.json\n*** End Patch\n"
        hook_text = json.dumps({"tool_name": "ApplyPatch", "tool_input": {"patch": patch_text}})
        tool, paths = phase_guard.parse_hook_input(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths])

        self.assertEqual("ApplyPatch", tool)
        self.assertEqual(["docs/agent-runs/run/run-state.json"], paths)
        self.assertFalse(result["ready"])
        self.assertTrue(any("Harness control file write blocked" in reason for reason in result["blocked_reasons"]))

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

    def test_phase_guard_allows_readonly_bash_without_active_run(self) -> None:
        hook_text = json.dumps({"tool_name": "Bash", "tool_input": {"command": "python --version"}})
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_blocks_code_read_before_start_when_entry_guard_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = phase_guard.validate_action(
                repo,
                "Read",
                [Path("services/payment/src/main/java/PayOrder.java")],
                require_active_run_for_read=True,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Code exploration blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_allows_code_read_after_start_when_entry_guard_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Read",
                [Path("services/payment/src/main/java/PayOrder.java")],
                run_dir=Path("docs/agent-runs/run"),
                require_active_run_for_read=True,
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_parses_common_read_path_fields(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Read",
                "tool_input": {
                    "filePath": "services/payment/src/main/java/PayOrder.java",
                    "absolutePath": "C:/repo/services/payment/src/main/java/PayOrder.java",
                },
            }
        )

        tool, paths = phase_guard.parse_hook_input(hook_text)

        self.assertEqual("Read", tool)
        self.assertIn("services/payment/src/main/java/PayOrder.java", paths)
        self.assertIn("C:/repo/services/payment/src/main/java/PayOrder.java", paths)

    def test_phase_guard_allows_read_outside_target_repo_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            outside = Path(tmp) / "other" / "PayOrder.java"
            outside.parent.mkdir()
            outside.write_text("class PayOrder {}", encoding="utf-8")

            result = phase_guard.validate_action(
                repo,
                "Read",
                [outside],
                require_active_run_for_read=True,
                require_session_checkpoint=True,
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(any("outside the configured harness repository" in warning for warning in result["warnings"]))

    def test_phase_guard_blocks_code_agent_dispatch_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="Implement the payment service and write production code.",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Code-agent dispatch blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_code_agent_dispatch_without_dispatch_packet_after_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "multi", ["services/payment"], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="Implement the payment service and write production code.",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("dispatcher context pack" in reason.lower() for reason in result["blocked_reasons"]))

    def test_phase_guard_allows_dispatcher_generated_code_agent_task_after_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            schedule = run_dir / "agent-schedule.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            state = run_state.build_state("run", "multi", ["services/payment"], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            write_implemented_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-payment",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/payment",
                                "inputs": [handoff.as_posix()],
                                "outputs": ["docs/agent-runs/run/service-plans/payment/code-agent.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            dispatch_result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="claude-code")

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text=dispatch_result["task_prompt"],
            )

        self.assertTrue(dispatch_result["ready"], dispatch_result["blocked_reasons"])
        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_allows_non_code_reviewer_task_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="Run R1 design review and check requirements coverage.",
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_run_state_validation_blocks_forged_implemented_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            registry = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text('{"schema":"e2e-dev-harness.artifact-registry.v1","artifacts":[]}\n', encoding="utf-8")
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            run_state.write_state(repo, state_path, state)

            result = run_state.validate_state(repo, state_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("transition history" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_allows_red_test_write_in_planned_phase(self) -> None:
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
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["services/payment-service/src/test/java/PaymentServiceTest.java"], result["test_code_paths"])

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

    def test_phase_guard_allows_code_write_in_implementation(self) -> None:
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

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_allows_run_artifact_writes_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
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

    def test_stop_guard_strict_blocks_clarified_run_before_planning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)

            result = harness_stop_guard.evaluate(repo, run_state_path=state_path, strict=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("not terminal" in reason for reason in result["blocked_reasons"]))
        self.assertIn("R1 design review", result["guidance"]["remaining_phases"])
        self.assertIn("Do not ask the user to choose", result["guidance"]["agent_instruction"])

    def test_stop_guard_allows_waiting_dispatch_without_marking_completion_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "WAITING_DISPATCH",
            )
            state["dispatch"] = {
                "status": "waiting_dispatch",
                "runtime": "manual",
                "current_task_id": "T10",
                "current_agent": "code-developer-order-service",
            }
            run_state.write_state(repo, state_path, state)

            result = harness_stop_guard.evaluate(repo, run_state_path=state_path, strict=True)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("WAITING_DISPATCH", result["lifecycle"])
        self.assertTrue(result["dispatch_waiting"])
        self.assertFalse(result["completion_ready"])
        self.assertIn("independent subagent", result["warnings"][0])

    def test_stop_guard_json_hook_writes_blocking_guidance_to_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("docs/agent-runs/run", "single", [], "docs/agent-runs/run/artifact-registry.json", "RED_READY")
            run_state.write_state(repo, state_path, state)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "harness_stop_guard.py"),
                    str(repo),
                    "--run-state",
                    str(state_path),
                    "--strict",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(2, completed.returncode)
        self.assertIn('"ready": false', completed.stdout)
        self.assertIn("HARNESS STOP BLOCKED", completed.stderr)
        self.assertIn("R2 test review", completed.stderr)
        self.assertIn("Do not ask the user to choose", completed.stderr)

    def test_stop_guard_allows_no_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = harness_stop_guard.evaluate(Path(tmp))

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_stop_guard_blocks_run_directory_without_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            (run_dir / "evidence").mkdir(parents=True)

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
                    self.assertIn("--strict", text)
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
        self.assertIn("--strict", stop_command)

    def test_install_hooks_rewrites_portable_runtime_templates(self) -> None:
        for runtime in ("codex", "gemini"):
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)

                result = install_hooks.install(repo, runtime, dry_run=True)
                command = result["planned_config"]["command"]

                self.assertTrue(result["ready"], result["blocked_reasons"])
                self.assertIn(str(ROOT / "skills" / "e2e-dev-harness" / "scripts" / "phase_guard.py"), command)
                self.assertIn("--require-active-run-for-read", command)
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

    def test_install_hooks_rejects_wrong_installed_phase_guard_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            wrong_phase_guard = Path.home() / ".claude" / "skills" / "e2e-dev-harness" / "phase_guard.py"
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Read|Grep|Glob|Write|Edit|Update|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f'"{sys.executable}" "{wrong_phase_guard}" "{repo}" --hook-input - --require-active-run-for-read --require-session-checkpoint --json',
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
                                            "command": f'"{sys.executable}" "{ROOT / "skills" / "e2e-dev-harness" / "scripts" / "harness_stop_guard.py"}" "{repo}" --hook-input - --strict --json',
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
        self.assertTrue(any("installed phase_guard.py" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rejects_posttooluse_only_phase_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PostToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f'"{sys.executable}" "{ROOT / "skills" / "e2e-dev-harness" / "scripts" / "phase_guard.py"}" "{repo}" --hook-input - --require-active-run-for-read --json',
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
                                            "command": f'"{sys.executable}" "{ROOT / "skills" / "e2e-dev-harness" / "scripts" / "harness_stop_guard.py"}" "{repo}" --hook-input - --strict --json',
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
        self.assertTrue(any("PreToolUse" in reason for reason in result["blocked_reasons"]))

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

    def test_install_hooks_rejects_missing_claude_task_matcher(self) -> None:
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
                                    "matcher": "Read|Grep|Glob|Write|Edit|Update|MultiEdit|NotebookEdit|Bash",
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
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'harness_stop_guard.py'}\" \"{repo}\" --hook-input - --strict --json",
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
        self.assertTrue(any("Task" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rejects_unscoped_gateguard_fact_force(self) -> None:
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
                                },
                                {
                                    "matcher": "Write|Edit|Update|MultiEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python gateguard-fact-force.py --all-writes",
                                        }
                                    ],
                                },
                            ],
                            "Stop": [
                                {
                                    "matcher": "",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'harness_stop_guard.py'}\" \"{repo}\" --hook-input - --strict --json",
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
        self.assertTrue(any("gateguard-fact-force" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rejects_non_strict_claude_stop_guard(self) -> None:
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
        self.assertTrue(any("--strict" in reason for reason in result["blocked_reasons"]))

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

    def test_pre_code_blocks_when_project_hook_config_is_broken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            write_implemented_state(repo, state_path, state)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Read|Grep|Glob|Write|Edit|Update|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": r"\python C:\Users\14907\.claude\skills\e2e-dev-harness\phase_guard.py . --hook-input - --require-active-run-for-read --require-session-checkpoint --json",
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
                                            "command": r"\python C:\Users\14907\.claude\skills\e2e-dev-harness\phase_guard.py . --hook-input - --strict --json",
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            home = repo / "home"
            home.mkdir()
            args = SimpleNamespace(
                repo=repo,
                tool="Edit",
                path=[Path("services/payment-service/src/main/java/PaymentService.java")],
                patch=None,
                command_text="",
                lock=None,
                run_dir=Path("docs/agent-runs/run"),
                status_file=None,
            )

            with patch.object(e2e_dev_harness.Path, "home", return_value=home):
                code, result = e2e_dev_harness.pre_code(args)

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertTrue(any("Runtime hook config is present but not enforcing" in reason for reason in result["blocked_reasons"]))

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

    def test_workflow_tier_auto_marks_chinese_payment_risk_control_as_critical(self) -> None:
        design_text = "统一支付风控系统：黑名单、商户评级、限额规则、观察模式、降级策略。"
        facts = {"service_candidates": ["jeepay-payment"], "multi_service": False}

        result = task_tier.evaluate("auto", design_text, facts, {"dependencies": []})

        self.assertEqual("critical", result["tier"])
        self.assertIn("gitnexus-impact", result["required_gates"])
        self.assertIn("strict-guard", result["required_gates"])

    def test_plan_archive_writes_registered_knowledge_graph_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "services" / "order-service" / "src" / "main").mkdir(parents=True)
            (repo / "services" / "order-service" / "pom.xml").write_text("<project />\n", encoding="utf-8")
            (repo / "pom.xml").write_text(
                "<project><modules><module>services/order-service</module></modules></project>\n",
                encoding="utf-8",
            )
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text("# Feature\n\n## Scope\n- services/order-service\n", encoding="utf-8")
            args = SimpleNamespace(
                repo=repo,
                mode="single",
                design_doc=Path("docs/design/feature.md"),
                agent_run_dir="docs/agent-runs/run",
                run_date="2026-05-31",
                service_scope="affected",
                service=["services/order-service"],
                path=None,
                dependency_report=None,
                create_archive=True,
                write_exec_plan=False,
                status_file=None,
            )

            code, result = e2e_dev_harness.plan(args)
            kg_path = repo / result["handoff_artifacts"]["knowledge_graph_status"]
            kg_exists = kg_path.exists()
            kg_status = json.loads(kg_path.read_text(encoding="utf-8"))

        self.assertEqual(0, code, result.get("blocked_reasons"))
        self.assertTrue(kg_exists)
        self.assertIn("selected_tools", kg_status)

    def test_implementation_gate_uses_run_state_registry_knowledge_graph_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            kg = run_dir / "evidence" / "knowledge-graph-refresh.json"
            kg.parent.mkdir(parents=True)
            kg.write_text(json.dumps({"selected_tools": ["gitnexus"], "available_tools": {"gitnexus": "gitnexus"}}), encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "docs/agent-runs/run",
                {
                    "run_state": "docs/agent-runs/run/run-state.json",
                    "artifact_registry": "docs/agent-runs/run/artifact-registry.json",
                    "knowledge_graph_status": "docs/agent-runs/run/evidence/knowledge-graph-refresh.json",
                },
                "single",
                [],
            )
            registry_path = run_dir / "artifact-registry.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("docs/agent-runs/run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, run_dir / "run-state.json", state)

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(
                    repo=repo,
                    phase="implementation",
                    run_state=Path("docs/agent-runs/run/run-state.json"),
                    tdd_mode="off",
                    require_semantic_reviews=False,
                    require_gitnexus_evidence="off",
                    workflow_tier="basic",
                )
            )

        self.assertFalse(any("Knowledge graph status file not found" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(result["knowledge_graph_status_loaded"])

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

        self.assertEqual("single", mode, reasons)

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




if __name__ == "__main__":
    unittest.main()
