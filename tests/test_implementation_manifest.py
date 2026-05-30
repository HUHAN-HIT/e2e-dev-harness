"""Implementation manifest and requirements-archive tests."""
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

import implementation_manifest  # noqa: E402
import requirements_archive  # noqa: E402


class ImplementationManifestTests(unittest.TestCase):
    def test_manifest_blocks_missing_required_artifact(self) -> None:
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | jeepay-service | jeepay-service/src/main/java/com/example/VnpayPaymentConfigService.java | config-service | explicit-requirement | yes | VnpayPaymentConfigServiceTest | verified | required by task |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(manifest, encoding="utf-8")

            result = implementation_manifest.validate(repo, manifest_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("does not exist" in reason for reason in result["blocked_reasons"]))

    def test_manifest_requires_all_design_modules(self) -> None:
        design = textwrap.dedent(
            """
            # VNPay

            ## Affected services/modules
            - jeepay-core: constants and params
            - jeepay-service: channel config service
            - jeepay-payment: payment, notice, refund services
            """
        ).strip()
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | jeepay-core | jeepay-core/src/main/java/com/example/VnpayNormalMchParams.java | params | explicit-requirement | yes | VnpayNormalMchParamsTest | verified | done |
            | IM-2 | jeepay-payment | jeepay-payment/src/main/java/com/example/VnpayPaymentService.java | payment-service | explicit-requirement | yes | VnpayPaymentServiceTest | verified | done |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            for path in (
                "jeepay-core/src/main/java/com/example/VnpayNormalMchParams.java",
                "jeepay-payment/src/main/java/com/example/VnpayPaymentService.java",
            ):
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("class Placeholder {}\n", encoding="utf-8")
            design_path = repo / "docs" / "design" / "vnpay.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            design_path.parent.mkdir(parents=True)
            manifest_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")

            result = implementation_manifest.validate(repo, manifest_path, design_path)

        self.assertFalse(result["ready"])
        self.assertIn("jeepay-service", " ".join(result["blocked_reasons"]))

    def test_manifest_blocks_required_artifact_section_class_not_listed(self) -> None:
        design = textwrap.dedent(
            """
            # VNPay

            ## Required Artifacts
            - AC-1 VnpayQrOrderRS is returned for QR orders.
            """
        ).strip()
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | jeepay-payment | jeepay-payment/src/main/java/com/example/VnpayPaymentService.java | payment-service | explicit-requirement | yes | VnpayPaymentServiceTest | verified | done |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = repo / "jeepay-payment/src/main/java/com/example/VnpayPaymentService.java"
            target.parent.mkdir(parents=True)
            target.write_text("class Placeholder {}\n", encoding="utf-8")
            design_path = repo / "docs" / "design" / "vnpay.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            design_path.parent.mkdir(parents=True)
            manifest_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")

            result = implementation_manifest.validate(repo, manifest_path, design_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("VnpayQrOrderRS" in reason for reason in result["blocked_reasons"]))

    def test_manifest_ignores_reference_class_outside_required_artifact_sections(self) -> None:
        design = textwrap.dedent(
            """
            # Checkout

            ## Acceptance Criteria
            - AC-1 Checkout result is returned.

            ## Notes
            - Legacy OrderService is a reference only and must not be reimplemented.
            """
        ).strip()
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | checkout-service | checkout-service/src/main/java/com/example/CheckoutService.java | service | explicit-requirement | yes | CheckoutServiceTest | verified | done |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = repo / "checkout-service/src/main/java/com/example/CheckoutService.java"
            target.parent.mkdir(parents=True)
            target.write_text("class Placeholder {}\n", encoding="utf-8")
            design_path = repo / "docs" / "design" / "checkout.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            design_path.parent.mkdir(parents=True)
            manifest_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")

            result = implementation_manifest.validate(repo, manifest_path, design_path)

        self.assertTrue(result["ready"])
        self.assertNotIn("OrderService", result["design_artifacts"])

    def test_manifest_allows_verified_existing_artifacts(self) -> None:
        design = textwrap.dedent(
            """
            # VNPay

            ## Affected services/modules
            - jeepay-core: constants and params
            - jeepay-payment: payment service

            ## Acceptance Criteria
            - AC-1 VnpayPaymentService returns the VNPay URL.
            """
        ).strip()
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | jeepay-core | jeepay-core/src/main/java/com/example/VnpayNormalMchParams.java | params | explicit-requirement | yes | VnpayNormalMchParamsTest | verified | done |
            | IM-2 | jeepay-payment | jeepay-payment/src/main/java/com/example/VnpayPaymentService.java | payment-service | explicit-requirement | yes | VnpayPaymentServiceTest | verified | done |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            for path in (
                "jeepay-core/src/main/java/com/example/VnpayNormalMchParams.java",
                "jeepay-payment/src/main/java/com/example/VnpayPaymentService.java",
            ):
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("class Placeholder {}\n", encoding="utf-8")
            design_path = repo / "docs" / "design" / "vnpay.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            design_path.parent.mkdir(parents=True)
            manifest_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")

            result = implementation_manifest.validate(repo, manifest_path, design_path)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(2, result["required_rows"])




class RequirementsArchiveTests(unittest.TestCase):
    def archive_doc(self) -> str:
        return textwrap.dedent(
            """
            # Requirements Archive

            ## Original Request
            Build quote creation.

            ## Final Clarified Requirement
            Return a quote for valid input and reject invalid input.

            ## Scope And Non-Goals
            Scope: services/sample-service. Non-goals: billing integration.

            ## Acceptance Criteria Status
            | id | requirement | status | evidence |
            | --- | --- | --- | --- |
            | AC-1 | Quote is returned | verified | docs/agent-runs/run/evidence/coverage-matrix.md |

            ## Use Case Coverage
            UC-1 covers AC-1 happy path and validation failure.

            ## Impacted Services APIs And Contracts
            services/sample-service; no HTTP/DMQ contract change.

            ## Implementation Evidence
            docs/agent-runs/run/evidence/implementation-manifest.md

            ## Test Evidence
            docs/agent-runs/run/evidence/green-test.txt

            ## Review And Rework Summary
            R1/R2/R3 approved; no open rework.

            ## Deferred And Residual Risks
            None.

            ## Promoted Memory Entries
            M-1 promoted to memory/decisions.md.

            ## Follow Up Opportunities
            None.
            """
        ).strip()

    def test_requirements_archive_blocks_missing_required_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            archive = repo / "docs" / "agent-runs" / "run" / "requirements-archive.md"
            archive.parent.mkdir(parents=True)
            archive.write_text("# Requirements Archive\n\n## Original Request\nBuild quote creation.\n", encoding="utf-8")

            result = requirements_archive.validate(repo, archive)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Final Clarified Requirement" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("Acceptance Criteria Status" in reason for reason in result["blocked_reasons"]))

    def test_requirements_archive_allows_complete_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            archive = repo / "docs" / "agent-runs" / "run" / "requirements-archive.md"
            archive.parent.mkdir(parents=True)
            archive.write_text(self.archive_doc(), encoding="utf-8")

            result = requirements_archive.validate(repo, archive)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(12, result["section_count"])

    def test_requirements_archive_blocks_placeholders_in_required_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            archive = repo / "docs" / "agent-runs" / "run" / "requirements-archive.md"
            archive.parent.mkdir(parents=True)
            archive.write_text(self.archive_doc().replace("Return a quote for valid input", "TBD"), encoding="utf-8")

            result = requirements_archive.validate(repo, archive)

        self.assertFalse(result["ready"])
        self.assertTrue(any("placeholder" in reason.lower() for reason in result["blocked_reasons"]))

    def test_requirements_archive_discovers_archive_from_agent_run_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            archive = repo / "docs" / "agent-runs" / "run" / "requirements-archive.md"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            red.parent.mkdir(parents=True)
            archive.write_text(self.archive_doc(), encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")

            discovered = requirements_archive.discover(repo, [red])

        self.assertEqual(archive.resolve(), discovered.resolve())




if __name__ == "__main__":
    unittest.main()
