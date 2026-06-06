"""Workflow guard and verified-workflow-result helper."""
from __future__ import annotations

import sys
import json
import tempfile
import unittest

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import workflow_guard  # noqa: E402
from conftest import verified_workflow_result  # noqa: E402


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

    def test_phase_coverage_uses_user_clarification_ready_for_clarify_phase(self) -> None:
        verify_result = verified_workflow_result()
        verify_result["clarification"] = {
            "ready_for_implementation": False,
            "user_clarification_ready": True,
            "design_outline_ready": True,
            "implementation_evidence_ready": False,
            "mechanical_repair_ready": True,
        }

        result = workflow_guard.validate_phase_coverage(verify_result, completion_required=True)

        clarify = next(item for item in result["phases"] if item["phase"] == "clarify")
        self.assertTrue(clarify["ready"])

    def test_legacy_clarification_status_falls_back_with_warning(self) -> None:
        verify_result = verified_workflow_result()
        verify_result["clarification"] = {"ready_for_implementation": True}

        result = workflow_guard.validate_verify_result(
            verify_result,
            strict=True,
            require_completion=True,
        )

        self.assertTrue(result["ready"], result)
        self.assertTrue(any("legacy clarification readiness" in warning.lower() for warning in result["warnings"]))

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




if __name__ == "__main__":
    unittest.main()
