"""Cross-service dependency scanner and Spring static analysis."""
from __future__ import annotations

import sys
import importlib
import json
import subprocess
import tempfile
import textwrap
import unittest

from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "harness_v2" / "adapters" / "scanner" / "_legacy"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cross_service_dependency_scan  # noqa: E402


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

    def test_dependency_report_requires_verified_gitnexus_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            report = repo / "knowledge-graph" / "cross-service-dependencies.json"
            report.parent.mkdir(parents=True)
            report.write_text(
                json.dumps(
                    {
                        "ready": True,
                        "tool_priority": ["gitnexus", "deterministic-scan"],
                        "gitnexus": {"primary": True, "available": False, "verified": False},
                        "dependencies": [{"kind": "http", "confidence": "verified"}],
                        "unresolved_questions": [],
                    }
                ),
                encoding="utf-8",
            )

            result = cross_service_dependency_scan.validate_dependency_report(repo, report, require_gitnexus=True)

        self.assertFalse(result["ready"])
        self.assertTrue(result["gitnexus_required"])
        self.assertFalse(result["gitnexus_verified"])
        self.assertTrue(any("GitNexus impact evidence" in reason for reason in result["blocked_reasons"]))

    def test_dependency_report_allows_user_approved_gitnexus_degradation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            report = repo / "knowledge-graph" / "cross-service-dependencies.json"
            approval = repo / "docs" / "agent-runs" / "run" / "evidence" / "gitnexus-degradation.md"
            report.parent.mkdir(parents=True)
            approval.parent.mkdir(parents=True)
            report.write_text(
                json.dumps(
                    {
                        "ready": True,
                        "tool_priority": ["gitnexus", "deterministic-scan"],
                        "gitnexus": {"primary": True, "available": False, "verified": False},
                        "dependencies": [{"kind": "dmq", "confidence": "verified"}],
                        "unresolved_questions": [],
                    }
                ),
                encoding="utf-8",
            )
            approval.write_text(
                textwrap.dedent(
                    """
                    # GitNexus Degradation
                    Approval: user-approved
                    Reason: GitNexus MCP server was unavailable during this run.
                    Fallback Evidence: deterministic scanner, Maven module graph, targeted code reads, and service tests.
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = cross_service_dependency_scan.validate_dependency_report(
                repo,
                report,
                require_gitnexus=True,
                gitnexus_degradation=approval,
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(result["gitnexus_degraded"])
        self.assertTrue(result["gitnexus_degradation"]["ready"])



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
import spring_static_check  # noqa: E402

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




if __name__ == "__main__":
    unittest.main()
