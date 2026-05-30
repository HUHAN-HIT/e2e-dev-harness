"""Coverage gate: unit, acceptance-criteria, and AC-check validation."""
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

import coverage_gate  # noqa: E402
from conftest import write_command_evidence  # noqa: E402


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



if __name__ == "__main__":
    unittest.main()
