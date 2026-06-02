"""AC progress gate and test-impact plan tests."""
from __future__ import annotations

import sys
import json
import tempfile
import textwrap
import unittest

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ac_progress_gate  # noqa: E402
import test_impact_plan  # noqa: E402
from conftest import write_command_evidence  # noqa: E402


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




if __name__ == "__main__":
    unittest.main()
