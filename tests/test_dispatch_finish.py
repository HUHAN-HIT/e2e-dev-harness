"""dispatch-finish: post-spawn one-shot chaining (ack -> handoff finalize -> complete).

These tests pin the *orchestration* contract of the new single-worker fast path:
- the three deterministic post-spawn steps run in order;
- any failing step short-circuits the rest (no silent bypass);
- handoff finalize is optional.

Isolation is unchanged: dispatch_engine.finish still requires a real worker
handle (forwarded to dispatch_ack) and still runs the full dispatch_complete
gate. We stub the underlying steps to keep the test fast and focused on the
chaining logic this module adds.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import dispatcher  # noqa: E402
import phase_guard  # noqa: E402
import run_state  # noqa: E402
from e2e_harness.cli.commands import dispatch as dispatch_command  # noqa: E402
from e2e_harness.cli.commands import handoff as handoff_command  # noqa: E402
from e2e_harness.engine import dispatch_engine  # noqa: E402


class DispatchFinishOrchestrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []
        self._orig_ack = dispatcher.dispatch_ack
        self._orig_complete = dispatcher.dispatch_complete
        self._orig_finalize = handoff_command.run_finalize

    def tearDown(self) -> None:
        dispatcher.dispatch_ack = self._orig_ack
        dispatcher.dispatch_complete = self._orig_complete
        handoff_command.run_finalize = self._orig_finalize

    def _stub(self, name: str, ready: bool):
        def fn(*_args, **_kwargs):
            self.calls.append(name)
            return {
                "ready": ready,
                "blocked_reasons": [] if ready else [f"{name} blocked"],
                "warnings": [],
            }

        return fn

    def _finish(self, handoff):
        return dispatch_engine.finish(
            Path("."),
            Path("schedule.json"),
            Path("run-state.json"),
            "T01",
            "requirements-clarifier",
            "worker-1",
            evidence=["docs/agent-runs/run/handoffs/T01.md"],
            handoff=handoff,
        )

    def test_chains_ack_handoff_complete_in_order(self) -> None:
        dispatcher.dispatch_ack = self._stub("ack", True)
        handoff_command.run_finalize = self._stub("handoff", True)
        dispatcher.dispatch_complete = self._stub("complete", True)

        result = self._finish(Path("docs/agent-runs/run/handoffs/T01.md"))

        self.assertTrue(result["ready"])
        self.assertEqual(self.calls, ["ack", "handoff", "complete"])
        self.assertEqual(result["stage"], "complete")

    def test_ack_failure_short_circuits(self) -> None:
        dispatcher.dispatch_ack = self._stub("ack", False)
        handoff_command.run_finalize = self._stub("handoff", True)
        dispatcher.dispatch_complete = self._stub("complete", True)

        result = self._finish(Path("docs/agent-runs/run/handoffs/T01.md"))

        self.assertFalse(result["ready"])
        self.assertEqual(result["stage"], "ack")
        self.assertEqual(self.calls, ["ack"])
        self.assertIn("ack blocked", result["blocked_reasons"])

    def test_handoff_failure_short_circuits_before_complete(self) -> None:
        dispatcher.dispatch_ack = self._stub("ack", True)
        handoff_command.run_finalize = self._stub("handoff", False)
        dispatcher.dispatch_complete = self._stub("complete", True)

        result = self._finish(Path("docs/agent-runs/run/handoffs/T01.md"))

        self.assertFalse(result["ready"])
        self.assertEqual(result["stage"], "handoff")
        self.assertEqual(self.calls, ["ack", "handoff"])

    def test_handoff_optional_when_not_provided(self) -> None:
        dispatcher.dispatch_ack = self._stub("ack", True)
        handoff_command.run_finalize = self._stub("handoff", True)
        dispatcher.dispatch_complete = self._stub("complete", True)

        result = self._finish(None)

        self.assertTrue(result["ready"])
        self.assertEqual(self.calls, ["ack", "complete"])

    def test_dispatch_command_facade_exposes_finish(self) -> None:
        dispatcher.dispatch_ack = self._stub("ack", True)
        handoff_command.run_finalize = self._stub("handoff", True)
        dispatcher.dispatch_complete = self._stub("complete", True)

        result = dispatch_command.run_finish(
            Path("."),
            Path("schedule.json"),
            Path("run-state.json"),
            "T01",
            "requirements-clarifier",
            "worker-1",
            evidence=["docs/agent-runs/run/handoffs/T01.md"],
            handoff=Path("docs/agent-runs/run/handoffs/T01.md"),
        )

        self.assertTrue(result["ready"])
        self.assertEqual(self.calls, ["ack", "handoff", "complete"])


class DispatchAckPhaseGuardTest(unittest.TestCase):
    def test_phase_guard_auto_confirm_does_not_allow_worker_owned_handoff_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "phase-guard-auto-confirm:T01",
                "worker_session": "phase-guard-auto-confirm:T01",
                "spawn_confirmed_by": "phase_guard",
                "spawn_acknowledged_at": "2026-06-04T00:00:00Z",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            (run_dir / "agent-schedule.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [evidence.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Write",
                [evidence],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Worker output write blocked" in reason for reason in result["blocked_reasons"]))

    def test_manual_dispatch_ack_proof_allows_worker_owned_handoff_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "manual",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "requirements-worker-1",
                "worker_session": "requirements-worker-session-1",
                "spawn_confirmed_by": "dispatch_ack",
                "spawn_acknowledged_at": "2026-06-04T00:00:00Z",
                "manual_worker_confirmed": True,
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            (run_dir / "agent-schedule.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [evidence.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Write",
                [evidence],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_runtime_dispatch_ack_proof_allows_worker_owned_handoff_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "claude-code",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "requirements-clarifier-worker",
                "worker_session": "requirements-clarifier-session",
                "spawn_confirmed_by": "dispatch_ack",
                "spawn_acknowledged_at": "2026-06-06T01:31:07Z",
                "manual_worker_confirmed": False,
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            (run_dir / "agent-schedule.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [evidence.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Write",
                [evidence],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_dispatch_ack_recovers_phase_guard_unverified_state(self) -> None:
        """phase_guard auto-confirm leaves the dispatch in worker_running_unverified.

        That state must remain ack-able: a fresh real worker handle should be able
        to acknowledge it and upgrade unverified -> verified. Otherwise dispatch-ack
        ("not awaiting runtime spawn") and dispatch-complete ("run dispatch-ack")
        deadlock with no forward CLI transition.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "worker_running_unverified",
                "runtime": "manual",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "phase-guard-auto-confirm:T01",
                "worker_session": "phase-guard-auto-confirm:T01",
                "spawn_confirmed_by": "phase_guard",
                "spawn_acknowledged_at": "2026-06-04T00:00:00Z",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)

            result = dispatcher.dispatch_ack(
                repo,
                state_path,
                "T01",
                "requirements-clarifier",
                "requirements-worker-1",
                "requirements-worker-session-1",
            )

        self.assertNotIn(
            "Dispatch is not awaiting runtime spawn acknowledgement.",
            result.get("blocked_reasons", []),
        )
        self.assertTrue(result["ready"], result.get("blocked_reasons"))
        self.assertEqual(result["dispatch"]["status"], "worker_running")
        self.assertEqual(result["dispatch"]["spawn_confirmed_by"], "dispatch_ack")

    def test_manual_worker_packet_routes_post_write_step_through_dispatch_finish(self) -> None:
        repo = Path(".").resolve()
        packet = dispatcher.manual_worker_packet(
            repo,
            Path("docs/agent-runs/run/agent-schedule.json"),
            Path("docs/agent-runs/run/run-state.json"),
            {
                "id": "T01",
                "agent": "requirements-clarifier",
                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
            },
        )

        commands = packet["next_commands"]
        self.assertIn("dispatch-ack", commands[0])
        self.assertNotIn("--schedule", commands[0])
        self.assertIn("Fresh worker writes", commands[1])
        self.assertIn("dispatch-finish", commands[2])
        self.assertIn("--handoff docs/agent-runs/run/handoffs/01-requirements-clarifier.md", commands[2])


if __name__ == "__main__":
    unittest.main()
