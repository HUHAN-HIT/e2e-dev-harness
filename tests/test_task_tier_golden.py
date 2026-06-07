"""Golden anti-regression contract for task tier classification (Spec D4)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import task_tier  # noqa: E402


class TaskTierGoldenTests(unittest.TestCase):
    def _auto(self, text, facts=None, deps=None):
        return task_tier.evaluate("auto", text, facts or {}, deps or {})

    def test_payment_cross_service_is_critical(self):
        result = self._auto(
            "Rework the payment refund callback settlement across services.",
            {"service_candidates": ["services/pay", "services/ledger"], "multi_service": True},
            {"dependencies": [{"kind": "http"}]},
        )
        self.assertEqual("critical", result["tier"])
        self.assertIn("contracts", result["required_gates"])
        self.assertIn("strict-guard", result["required_gates"])

    def test_mq_multi_service_is_critical(self):
        result = self._auto(
            "Publish a RocketMQ notification with topic and payload.",
            {"service_candidates": ["services/a", "services/b"], "multi_service": True},
            {"dependencies": [{"kind": "rocketmq"}]},
        )
        self.assertEqual("critical", result["tier"])

    def test_single_table_repository_change_is_minimal(self):
        result = self._auto(
            "Adjust one repository query in order-service for a single table read.",
            {"service_candidates": ["services/order"], "multi_service": False},
            {"dependencies": []},
        )
        self.assertEqual("minimal", result["tier"])
        self.assertEqual(
            ["clarification", "test-evidence", "task-alignment", "run-state"],
            result["required_gates"],
        )

    def test_util_function_change_is_minimal(self):
        result = self._auto(
            "Fix an off-by-one in a small utility helper function.",
            {"service_candidates": ["services/order"], "multi_service": False},
            {"dependencies": []},
        )
        self.assertEqual("minimal", result["tier"])

    def test_single_service_rest_endpoint_locked_standard(self):
        result = self._auto(
            "Add one REST API endpoint in order-service for an admin lookup screen.",
            {"service_candidates": ["services/order"], "multi_service": False},
            {"dependencies": []},
        )
        self.assertEqual("standard", result["tier"])

    def test_compliance_audit_task_is_audited(self):
        result = self._auto(
            "Run a compliance audit of the regulatory incident handling path.",
            {"service_candidates": ["services/order"], "multi_service": False},
            {"dependencies": []},
        )
        self.assertEqual("audited", result["tier"])


if __name__ == "__main__":
    unittest.main()
