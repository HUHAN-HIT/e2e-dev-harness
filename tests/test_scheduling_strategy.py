from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import scheduling_strategy  # noqa: E402


class SchedulingStrategyTests(unittest.TestCase):
    def test_low_risk_single_service_stays_single_worker(self) -> None:
        result = scheduling_strategy.decide(
            selected_mode="single",
            services=["services/order-service"],
            reasons=[],
            design_text="## Acceptance Criteria\n- AC-1: Return an order quote.\n",
        )

        self.assertEqual("e2e-dev-harness.scheduling-decision.v1", result["schema"])
        self.assertEqual("single-worker", result["execution_model"])
        self.assertEqual(1, result["max_workers"])
        self.assertEqual("single", result["task_split"]["strategy"])
        self.assertEqual("serial", result["parallelism"]["code"])
        self.assertEqual(
            ["services/order-service"],
            result["review_strategy"]["service_reviewers"],
        )

    def test_complex_single_service_creates_task_item_lanes_but_gates_code_parallelism(
        self,
    ) -> None:
        result = scheduling_strategy.decide(
            selected_mode="single-review",
            services=["services/order-service"],
            reasons=["large or design-heavy implementation context"],
            design_text=(
                "## Acceptance Criteria\n"
                "- AC-1: Validate quote inputs.\n"
                "- AC-2: Persist quote audit trail.\n"
                "- AC-3: Publish quote created event.\n"
            ),
        )

        self.assertEqual("split-single", result["execution_model"])
        self.assertEqual("acceptance-criteria", result["task_split"]["strategy"])
        self.assertEqual(
            ["AC-1", "AC-2", "AC-3"],
            [lane["acceptance_id"] for lane in result["implementation_lanes"]],
        )
        self.assertEqual("gated-by-edit-scope", result["parallelism"]["code"])
        self.assertIn(
            "single service code lanes need non-overlapping edit scopes",
            result["blocked_parallelism"][0],
        )

    def test_multi_service_parallelizes_by_service_and_keeps_global_review(self) -> None:
        result = scheduling_strategy.decide(
            selected_mode="multi",
            services=["services/order-service", "services/payment-service"],
            reasons=["multiple affected services/modules"],
            design_text="## Acceptance Criteria\n- AC-1: Order requests payment authorization.\n",
        )

        self.assertEqual("service-parallel", result["execution_model"])
        self.assertEqual(2, result["max_workers"])
        self.assertEqual("service", result["task_split"]["strategy"])
        self.assertEqual("service-parallel", result["parallelism"]["code"])
        self.assertEqual(
            ["services/order-service", "services/payment-service"],
            result["review_strategy"]["service_reviewers"],
        )
        self.assertTrue(result["review_strategy"]["global_review"])

    def test_review_strategy_names_service_and_global_aggregation(self) -> None:
        result = scheduling_strategy.decide(
            selected_mode="multi",
            services=["services/order-service", "services/payment-service"],
            reasons=["multiple affected services/modules"],
            design_text="## Acceptance Criteria\n- AC-1: Cross-service flow.\n",
        )

        self.assertEqual(
            ["services/order-service", "services/payment-service"],
            result["review_strategy"]["service_reviewers"],
        )
        self.assertTrue(result["review_strategy"]["global_review"])
        self.assertEqual(
            "service-reviews-then-global-r3",
            result["review_strategy"]["aggregation"],
        )

    def test_split_single_without_explicit_acs_uses_fallback_lane_metadata(self) -> None:
        result = scheduling_strategy.decide(
            selected_mode="single-review",
            services=["services/order-service"],
            reasons=["large or design-heavy implementation context"],
            design_text="## Acceptance Criteria\n- Validate order quote.\n",
        )

        self.assertEqual(["AC-1"], result["task_split"]["acceptance_ids"])
        self.assertEqual(
            ["AC-1"],
            [lane["acceptance_id"] for lane in result["implementation_lanes"]],
        )
        self.assertEqual(
            "task-item-reviews-then-service-r3",
            result["review_strategy"]["aggregation"],
        )

    def test_single_worker_review_strategy_names_review_chain(self) -> None:
        result = scheduling_strategy.decide(
            selected_mode="single-review",
            services=["services/order-service"],
            reasons=[],
            design_text="## Acceptance Criteria\n- AC-1: Return an order quote.\n",
        )

        self.assertEqual("single-worker", result["execution_model"])
        self.assertEqual(
            "single-reviewer-chain",
            result["review_strategy"]["aggregation"],
        )

    def test_single_worker_non_review_strategy_is_minimal(self) -> None:
        result = scheduling_strategy.decide(
            selected_mode="single",
            services=["services/order-service"],
            reasons=[],
            design_text="## Acceptance Criteria\n- AC-1: Return an order quote.\n",
        )

        self.assertEqual("single-worker", result["execution_model"])
        self.assertEqual("minimal", result["review_strategy"]["aggregation"])


if __name__ == "__main__":
    unittest.main()
