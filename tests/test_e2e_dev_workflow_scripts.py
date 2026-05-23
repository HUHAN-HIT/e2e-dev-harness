from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-workflow" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import clarification_gate  # noqa: E402
import agent_instructions  # noqa: E402
import coverage_gate  # noqa: E402
import e2e_dev_workflow  # noqa: E402
import implementation_gate  # noqa: E402
import memory_capture  # noqa: E402
import orchestration_plan  # noqa: E402
from common import split_command  # noqa: E402


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


class CommandSplitTests(unittest.TestCase):
    def test_simple_graph_command_splits_without_shell(self) -> None:
        self.assertEqual(["graphify", "update", "."], split_command("graphify update ."))

    def test_shell_control_operators_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            split_command("graphify update . && echo unsafe")


class AgentInstructionScopeTests(unittest.TestCase):
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
            unit.write_text("mvn -pl services/a -am test: PASS\n", encoding="utf-8")
            review.write_text("Business logic reviewed against AC-1.\n", encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review)

        self.assertTrue(result["ready"])
        self.assertEqual(1, result["coverage_rows"])

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
            unit.write_text("PASS\n", encoding="utf-8")
            review.write_text("Reviewed.\n", encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review)

        self.assertFalse(result["ready"])
        self.assertTrue(any("code_refs" in reason for reason in result["blocked_reasons"]))


class ImplementationGateTests(unittest.TestCase):
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
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            unit.write_text("mvn -pl services/sample-service -am test: PASS\n", encoding="utf-8")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")

            result = implementation_gate.validate_gate(repo, design, kg, "completion", red, matrix, unit, review)

        self.assertTrue(result["ready"])
        self.assertEqual(1, result["coverage"]["coverage_rows"])

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
            unit.write_text("mvn -pl services/sample-service -am test: PASS\n", encoding="utf-8")
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
            unit.write_text("mvn -pl services/sample-service -am test: PASS\n", encoding="utf-8")
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
    def test_discovery_mode_has_no_agent_plan(self) -> None:
        artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        agents = orchestration_plan.agent_plan("discovery", artifacts, [])

        self.assertEqual([], agents)

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
            "docs/agent-runs/2026-05-23-checkout/service-plans/order-service/implementation-plan.md",
            result["service_plans"]["services/order-service"]["service_plan"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/payment-service/code-agent.md",
            result["service_plans"]["services/payment-service"]["code_agent"],
        )

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
        self.assertIn("coverage-reviewer", names)


class UnifiedCliTests(unittest.TestCase):
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
                superpowers_mode="off",
                memory_mode="off",
                agent_orchestration_mode="auto",
                service_scope="discovery",
                agent_run_dir=None,
                run_date="2026-05-23",
                kg_mode="auto",
                status_file=None,
            )

            def fake_detect(path: Path) -> dict:
                calls.append(path)
                return facts

            with patch.object(e2e_dev_workflow.kg_refresh, "detect", side_effect=fake_detect):
                code, result = e2e_dev_workflow.prepare(args)

        self.assertEqual(0, code)
        self.assertEqual(1, len(calls))
        self.assertEqual("discovery", result["orchestration"]["selected_mode"])
        self.assertEqual([], result["orchestration"]["agents"])


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

            result = e2e_dev_workflow.memory_status(repo, "strict")

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
            unit.write_text("PASS\n", encoding="utf-8")
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
            unit.write_text("PASS\n", encoding="utf-8")
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
            unit.write_text("PASS\n", encoding="utf-8")
            review.write_text("Reviewed.\n", encoding="utf-8")
            design_path.write_text(design, encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review, design_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("AC-2" in reason for reason in result["blocked_reasons"]))

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
            unit.write_text("PASS\n", encoding="utf-8")
            review.write_text("Reviewed.\n", encoding="utf-8")
            design_path.write_text(design, encoding="utf-8")

            result = coverage_gate.validate(repo, matrix, unit, review, design_path)

        self.assertTrue(result["ready"])


if __name__ == "__main__":
    unittest.main()
