"""Contract gate, rework gate, and contract validation."""
from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import contract_gate  # noqa: E402
import rework_gate  # noqa: E402
import e2e_dev_harness  # noqa: E402
import orchestration_plan  # noqa: E402


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
        self.assertIn("Do not put this handoff file in output_hashes", text)
        self.assertIn("ready marker records this handoff file hash", text)
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




if __name__ == "__main__":
    unittest.main()
