"""Task alignment guard tests."""
from __future__ import annotations

import sys
import subprocess
import tempfile
import textwrap
import unittest

from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import task_alignment_guard  # noqa: E402


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




if __name__ == "__main__":
    unittest.main()
