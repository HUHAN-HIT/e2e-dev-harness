from __future__ import annotations

import importlib
import json
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
import cross_service_dependency_scan  # noqa: E402
import e2e_dev_workflow  # noqa: E402
import implementation_gate  # noqa: E402
import kg_refresh  # noqa: E402
import memory_capture  # noqa: E402
import orchestration_plan  # noqa: E402
import rework_gate  # noqa: E402
from common import split_command  # noqa: E402


def write_command_evidence(path: Path, command: str = "mvn test", exit_code: int = 0) -> None:
    path.write_text(
        json.dumps(
            {
                "command": command,
                "exit_code": exit_code,
                "stdout_tail": "BUILD SUCCESS",
                "stderr_tail": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )


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


class CrossServiceDependencyScanTests(unittest.TestCase):
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

    def test_gitnexus_evidence_runs_context_and_impact_for_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            service = repo / "services" / "quote-service"
            (service / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
            (service / "pom.xml").write_text("<project />", encoding="utf-8")
            (service / "src" / "main" / "java" / "com" / "example" / "QuotePublisher.java").write_text(
                'class QuotePublisher { void publish() { dmqTemplate.publish("quote.created", payload); } }',
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

        self.assertTrue(any(command[:2] == ["gitnexus", "context"] for command in calls))
        self.assertTrue(any(command[:2] == ["gitnexus", "impact"] for command in calls))
        self.assertTrue(result["gitnexus"]["evidence"])

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
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")

            result = implementation_gate.validate_gate(repo, design, kg, "completion", red, matrix, unit, review)

        self.assertTrue(result["ready"])
        self.assertEqual(1, result["coverage"]["coverage_rows"])
        self.assertTrue(result["spring_static_check"]["ready"])

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
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
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
            dependency_report = repo / "knowledge-graph" / "cross-service-dependencies.json"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
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
            dependency_report = repo / "knowledge-graph" / "cross-service-dependencies.json"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(markdown, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            dependency_report.write_text(
                json.dumps({"ready": True, "dependencies": [{"kind": "http"}], "unresolved_questions": []}),
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

        self.assertTrue(result["ready"])
        self.assertTrue(result["dependency_report"]["ready"])


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

    def test_plan_artifacts_include_dependency_report_path(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/cross-service-dependencies.json",
            result["dependency_report"],
        )

    def test_service_plan_archive_contains_microservice_scoped_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifacts = orchestration_plan.artifacts(
                "checkout",
                run_date="2026-05-23",
                services=["services/order-service"],
            )

            e2e_dev_workflow.create_handoff_files(repo, artifacts)

            service_plan = repo / artifacts["service_plans"]["services/order-service"]["service_plan"]
            text = service_plan.read_text(encoding="utf-8")

        self.assertIn("# Service Implementation Plan: services/order-service", text)
        self.assertIn("## Modification Points", text)
        self.assertIn("## Service-local TDD Plan", text)
        self.assertIn("## Cross-service Contracts", text)

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

            with patch.object(e2e_dev_workflow.kg_refresh, "detect", side_effect=fake_detect):
                code, result = e2e_dev_workflow.prepare(args)

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
                patch.object(e2e_dev_workflow.kg_refresh, "detect", return_value=facts),
                patch.object(e2e_dev_workflow.cross_service_dependency_scan, "scan", return_value=dependency_result) as scan,
            ):
                code, result = e2e_dev_workflow.prepare(args)

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

            result = e2e_dev_workflow.orchestration_status(
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

            code, result = e2e_dev_workflow.gate(args)

        self.assertEqual(2, code)
        self.assertEqual(1, result["rework"]["open_count"])

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
            dependency_report = repo / "knowledge-graph" / "cross-service-dependencies.json"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            dependency_report.parent.mkdir(parents=True, exist_ok=True)
            design.write_text(design_text, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            dependency_report.write_text(
                json.dumps({"ready": True, "dependencies": [{"kind": "http"}], "unresolved_questions": []}),
                encoding="utf-8",
            )
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
                rework_dir=None,
                skip_spring_static_check=True,
                status_file=None,
            )

            code, result = e2e_dev_workflow.gate(args)

        self.assertEqual(0, code)
        self.assertTrue(result["dependency_report"]["ready"])


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


if __name__ == "__main__":
    unittest.main()
