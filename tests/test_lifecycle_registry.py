"""Lifecycle phase tables have a single source of truth in `agent_roles`.

These tests pin the convergence contract:
- `LIFECYCLE_REGISTRY` derives both the allowed-phase and satisfied-phase tables;
- `agent_scheduler` and `dispatcher` re-export identical satisfied tables
  (the historical divergence at `SERVICE_DESIGN_REQUIRED` is gone);
- `dispatcher.LIFECYCLE_ALLOWED_PHASES` stays byte-identical to the registry.

Decision (evidence-based, see harness-role-phase-convergence-plan Step 2):
`SERVICE_DESIGN_REQUIRED` satisfied == {clarify, design, r1-review}. The extra
`r1-review` is intentional: it defers the R1 design review until service design
completes (test `test_dispatch_next_service_design_skips_satisfied_global_design_task`
proves the service-design task dispatches first). The scheduler's earlier
omission was the real bug.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_roles  # noqa: E402
import agent_scheduler  # noqa: E402
import dispatcher  # noqa: E402


class LifecycleRegistryTest(unittest.TestCase):
    def test_registry_exposes_allowed_and_satisfied_tables(self) -> None:
        self.assertTrue(agent_roles.LIFECYCLE_ALLOWED_PHASES)
        self.assertTrue(agent_roles.LIFECYCLE_SATISFIED_PHASES)

    def test_satisfied_tables_derive_from_registry(self) -> None:
        self.assertEqual(
            {lc: meta["satisfied"] for lc, meta in agent_roles.LIFECYCLE_REGISTRY.items() if "satisfied" in meta},
            agent_roles.LIFECYCLE_SATISFIED_PHASES,
        )

    def test_allowed_tables_derive_from_registry(self) -> None:
        self.assertEqual(
            {lc: meta["allowed"] for lc, meta in agent_roles.LIFECYCLE_REGISTRY.items() if "allowed" in meta},
            agent_roles.LIFECYCLE_ALLOWED_PHASES,
        )

    def test_service_design_required_satisfied_value(self) -> None:
        self.assertEqual(
            {"clarify", "design", "r1-review"},
            agent_roles.LIFECYCLE_SATISFIED_PHASES["SERVICE_DESIGN_REQUIRED"],
        )


class LifecycleConvergenceTest(unittest.TestCase):
    """The historical divergence between the two consumers must be impossible."""

    def test_scheduler_and_dispatcher_satisfied_tables_are_identical(self) -> None:
        self.assertEqual(
            agent_scheduler.LIFECYCLE_SATISFIED_PHASES,
            dispatcher.LIFECYCLE_SATISFIED_PHASES,
        )

    def test_both_consumers_reference_registry_satisfied(self) -> None:
        self.assertEqual(
            agent_roles.LIFECYCLE_SATISFIED_PHASES,
            agent_scheduler.LIFECYCLE_SATISFIED_PHASES,
        )
        self.assertEqual(
            agent_roles.LIFECYCLE_SATISFIED_PHASES,
            dispatcher.LIFECYCLE_SATISFIED_PHASES,
        )

    def test_dispatcher_allowed_references_registry(self) -> None:
        self.assertEqual(
            agent_roles.LIFECYCLE_ALLOWED_PHASES,
            dispatcher.LIFECYCLE_ALLOWED_PHASES,
        )


if __name__ == "__main__":
    unittest.main()
