"""Clarification gate: open-question resolution and non-goals validation."""
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

import clarification_gate  # noqa: E402


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

    def test_user_confirmation_required_blocks_self_resolved_open_questions(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Restated Intent
            - The user wants checkout quotes returned.
            - User confirmation: confirmed-by: user @2026-06-02

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
            - None
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path, require_intent=True, require_user_confirmation=True)

        self.assertFalse(result["ready_for_implementation"])
        self.assertTrue(any("Open Questions" in gap for gap in result["user_confirmation_gaps"]))
        self.assertTrue(result["interaction_required"])

    def test_user_confirmation_required_accepts_confirmed_intent_and_open_questions(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Restated Intent
            - The user wants checkout quotes returned.
            - User confirmation: confirmed-by: user @2026-06-02

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
            - None. confirmed-by: user @2026-06-02
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path, require_intent=True, require_user_confirmation=True)

        self.assertTrue(result["ready_for_implementation"], result)
        self.assertEqual([], result["user_confirmation_gaps"])

    def test_user_confirmation_required_blocks_unconfirmed_restated_intent(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Restated Intent
            - The user wants checkout quotes returned.

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
            - None. confirmed-by: user @2026-06-02
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path, require_intent=True, require_user_confirmation=True)

        self.assertFalse(result["ready_for_implementation"])
        self.assertTrue(any("Restated Intent" in gap for gap in result["user_confirmation_gaps"]))

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

    def test_agent_fixable_impact_gaps_do_not_request_user_input(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Restated Intent
            - The agent understands the user wants a refund callback API.
            - User confirmation: confirmed-by: user @2026-06-03-session.

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

            ## Test Design
            - Unit test first.

            ## Open Questions
            None. confirmed-by: user @2026-06-03-session.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path, require_intent=True, require_user_confirmation=True)

        self.assertFalse(result["ready_for_implementation"])
        self.assertTrue(result["agent_remediation_required"])
        self.assertFalse(result["interaction_required"])
        self.assertFalse(result["interaction_contract"]["must_wait_for_user_answer"])
        self.assertEqual([], result["questions_to_ask_user"])
        self.assertEqual([], result["ask_user_requests"])
        self.assertTrue(any("Impact Summary" in item for item in result["agent_remediation_actions"]))

    def test_agent_fixable_change_logic_gaps_do_not_request_user_input(self) -> None:
        markdown = textwrap.dedent(
            """
            # Feature

            ## Restated Intent
            - The agent understands the user wants a refund callback API.
            - User confirmation: confirmed-by: user @2026-06-03-session.

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
            None. confirmed-by: user @2026-06-03-session.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_text(markdown, encoding="utf-8")

            result = clarification_gate.validate(path, require_intent=True, require_user_confirmation=True)

        self.assertFalse(result["ready_for_implementation"])
        self.assertTrue(result["agent_remediation_required"])
        self.assertFalse(result["interaction_required"])
        self.assertEqual([], result["questions_to_ask_user"])
        self.assertTrue(any("Change Logic" in item for item in result["agent_remediation_actions"]))

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

    def test_impact_summary_accepts_chinese_headers_from_design_docs(self) -> None:
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

            | AC | \u540d\u79f0 | \u7c7b\u578b | \u5165\u53e3/\u51fa\u53e3 | Source | Raw Evidence | \u5f71\u54cd\u7684\u63a5\u53e3/\u8c03\u7528\u65b9 | \u6240\u9700\u6d4b\u8bd5 | \u5173\u8054\u5951\u7ea6 | \u98ce\u9669 |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | refund callback | HTTP | POST /api/refunds/callback | GitNexus impact | docs/agent-runs/run/evidence/impact-analysis.json | merchant-admin | controller contract test | OpenAPI response contract | medium |

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

    def test_impact_summary_policy_exposes_bounded_limits(self) -> None:
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

        self.assertEqual(
            {
                "max_chars": 2400,
                "max_rows": 12,
                "raw_evidence_required": True,
                "source_required": True,
            },
            result["impact_summary_policy"],
        )

    def test_impact_summary_over_limit_exposes_mechanical_repair(self) -> None:
        long_note = " ".join("caller-impact" for _ in range(260))
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

            ## Change Logic
            - Current behavior: no public refund callback endpoint exists.
            - Target behavior: POST /api/refunds/callback accepts merchant refund callback requests.
            - Runtime path: RefundCallbackController -> RefundCallbackService -> RefundRepository.
            - State/data effect: persists refund status field and response body.

            ## Impact Summary
            - Source: GitNexus impact + dependency scanner
            - Raw Evidence: docs/agent-runs/run/evidence/impact-analysis.json
            - Notes: {long_note}

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
        self.assertFalse(result["interaction_required"])
        self.assertTrue(result["agent_remediation_required"])
        repairs = result["mechanical_remediation_tasks"]
        self.assertEqual("impact_summary_too_long", repairs[0]["code"])
        self.assertEqual("artifact_repair", repairs[0]["kind"])
        self.assertEqual("Impact Summary", repairs[0]["section"])
        self.assertEqual(2400, repairs[0]["max_chars"])
        self.assertIn("compress", repairs[0]["objective"].lower())

    def test_impact_summary_incomplete_table_exposes_mechanical_repair(self) -> None:
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

            | type | interface | related AC | risk |
            | --- | --- | --- | --- |
            | HTTP | POST /api/refunds/callback | AC-1 | medium |

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
        self.assertFalse(result["interaction_required"])
        self.assertTrue(result["agent_remediation_required"])
        repairs = result["mechanical_remediation_tasks"]
        self.assertEqual("impact_summary_table_incomplete", repairs[0]["code"])
        self.assertEqual("artifact_repair", repairs[0]["kind"])
        self.assertEqual("Impact Summary", repairs[0]["section"])
        self.assertIn("affected_callers_consumers", repairs[0]["gap"])
        self.assertIn("required_tests_contracts", repairs[0]["gap"])




if __name__ == "__main__":
    unittest.main()
