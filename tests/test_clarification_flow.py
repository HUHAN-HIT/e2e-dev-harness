from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_state  # noqa: E402
from e2e_harness.engine import clarification_flow  # noqa: E402


class ClarificationFlowTests(unittest.TestCase):
    def test_primary_clarifier_incomplete_blocks_before_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text("# Feature\n\n## Restated Intent\n", encoding="utf-8")
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "waiting_dispatch",
                "runtime": "manual",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            schedule = state_path.parent / "agent-schedule.json"
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            code, result = clarification_flow.run(repo, Path("docs/design/feature.md"), run_state=state_path)

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertEqual("primary_completion", result["clarification_transaction"]["stage"])
        self.assertNotIn("missing_sections", result)
        self.assertNotIn("empty_sections", result)

    def test_primary_complete_repair_pending_blocks_at_repair_barrier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            markdown = (
                textwrap.dedent(
                    """\
                    # Feature

                    ## Restated Intent
                    - The user wants a refund callback.
                    - User confirmation: confirmed-by: user @2026-06-02

                    ## Goal
                    - Add refund callback support.

                    ## Scope
                    - services/payment-service

                    ## Use Cases
                    - Merchant calls HTTP refund callback endpoint.

                    ## Acceptance Criteria
                    - AC-1 POST /api/refunds/callback returns accepted status.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-02

                    ## Change Logic
                    - Current behavior: no public refund callback endpoint exists.
                    - Target behavior: POST /api/refunds/callback accepts merchant refund callback requests.
                    - Runtime path: RefundCallbackController -> RefundCallbackService -> RefundRepository.
                    - State/data effect: persists refund status field and response body.

                    ## Impact Summary
                    - Source: GitNexus impact
                    - Raw Evidence: docs/agent-runs/run/evidence/impact.json

                    | type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
                    | --- | --- | --- | --- | --- | --- |
                    | HTTP | POST /api/refunds/callback | merchant-admin | AC-1 | controller contract test | medium |
                    """
                ).strip()
                + "\n\n"
                + ("Raw GitNexus detail that belongs in evidence, not the design summary.\n" * 80)
            )
            design.write_text(markdown, encoding="utf-8")
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)
            schedule = state_path.parent / "agent-schedule.json"
            (state_path.parent / "dispatch-events").mkdir(parents=True)
            (state_path.parent / "dispatch-events" / "T01-completed.json").write_text(
                json.dumps({"event": "worker_completed", "task_id": "T01", "agent": "requirements-clarifier"}),
                encoding="utf-8",
            )
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": ["docs/design/feature.md"],
                                "status": "completed",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            code, result = clarification_flow.run(repo, Path("docs/design/feature.md"), run_state=state_path)

        self.assertEqual(2, code)
        self.assertFalse(result["ready_for_implementation"])
        self.assertEqual("repair_barrier", result["clarification_transaction"]["stage"])
        self.assertEqual("dispatch_mechanical_repair", result["next_agent_action"])
        self.assertIn("mechanical_repair_dispatch", result)


if __name__ == "__main__":
    unittest.main()
