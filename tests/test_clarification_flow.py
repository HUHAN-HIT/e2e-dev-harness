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

        self.assertEqual(0, code)
        self.assertFalse(result["ready_for_implementation"])
        self.assertEqual("transition", result["clarification_transaction"]["stage"])
        self.assertEqual("dispatch_mechanical_repair", result["next_agent_action"])
        self.assertIn("mechanical_repair_dispatch", result)
        self.assertEqual("mechanical_repair", result["next_required"]["gate"])
        command = result["next_required"]["command"]
        self.assertIn("dispatch-beat", command)
        self.assertIn("generated", command)
        self.assertIn("spawn request/prompt", command)
        self.assertIn("Do not call Agent directly", command)

    def test_user_clarified_created_run_transitions_with_missing_implementation_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants a refund callback API.
                    - User confirmation: confirmed-by: user @2026-06-03-session.

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
                    None. confirmed-by: user @2026-06-03-session.
                    """
                ).strip(),
                encoding="utf-8",
            )
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
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertTrue(result["user_clarification_ready"], result)
        self.assertTrue(result["design_outline_ready"], result)
        self.assertFalse(result["implementation_evidence_ready"], result)
        self.assertFalse(result["ready_for_implementation"], result)
        self.assertEqual("transition", result["clarification_transaction"]["stage"])
        self.assertEqual("CLARIFIED", updated_state["lifecycle"])
        self.assertEqual("plan", result["next_required"]["phase"])

    def test_design_outline_missing_transitions_to_clarified_with_design_repair_next_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants a refund callback API.
                    - User confirmation: confirmed-by: user @2026-06-03-session.

                    ## Scope
                    - services/payment-service

                    ## Use Cases
                    - Merchant calls HTTP refund callback endpoint.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-03-session.
                    """
                ).strip(),
                encoding="utf-8",
            )
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
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertFalse(result["design_outline_ready"], result)
        self.assertEqual("CLARIFIED", updated_state["lifecycle"])
        self.assertEqual("design_outline", result["next_required"]["gate"])
        self.assertEqual("clarification_repair", result["next_required"]["phase"])
        self.assertIn("design-outline", result["next_required"]["command"])


if __name__ == "__main__":
    unittest.main()
