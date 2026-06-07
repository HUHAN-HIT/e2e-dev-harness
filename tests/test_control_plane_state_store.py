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

from e2e_harness.engine import control_plane  # noqa: E402
from e2e_harness.engine import state_store  # noqa: E402


class ControlPlaneStateStoreTests(unittest.TestCase):
    def make_run_dir(self) -> tuple[Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        run_dir = repo / "docs" / "agent-runs" / "run"
        run_dir.mkdir(parents=True)
        return repo, run_dir

    def test_control_plane_create_writes_single_authoritative_file(self) -> None:
        repo, run_dir = self.make_run_dir()

        result = control_plane.create(repo, run_dir, run_id="docs/agent-runs/run")

        self.assertTrue(result["ready"])
        path = run_dir / "control-plane.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "e2e-dev-harness.control-plane.v1")
        self.assertEqual(data["run_id"], "docs/agent-runs/run")
        self.assertEqual(data["lifecycle"], "CREATED")
        self.assertIn("gates", data)
        self.assertIn("tasks", data)
        self.assertIn("dispatches", data)
        self.assertIn("repair_transactions", data)
        self.assertIn("artifacts", data)
        self.assertIn("coordinator", data)
        self.assertIn("projections", data)
        self.assertEqual(data["phase_lock"]["state"], "code-write-locked")

    def write_legacy_created_run(self) -> tuple[Path, Path]:
        repo, run_dir = self.make_run_dir()
        (run_dir / "run-state.json").write_text(
            json.dumps(
                {
                    "schema": "e2e-dev-harness.run-state.v1",
                    "run_id": "docs/agent-runs/run",
                    "lifecycle": "CREATED",
                    "gates": {"clarification": "pending"},
                    "dispatches": {},
                    "history": [],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "agent-schedule.json").write_text(
            json.dumps(
                {
                    "schema": "e2e-dev-harness.agent-schedule.v1",
                    "mode": "single",
                    "completion_mode": "dispatcher-confirmed",
                    "tasks": [
                        {
                            "id": "T01",
                            "agent": "requirements-clarifier",
                            "phase": "clarify",
                            "outputs": ["docs/design/example.md"],
                            "status": "planned",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / ".phase-lock").write_text(
            json.dumps(
                {
                    "schema": "e2e-dev-harness.phase-lock.v1",
                    "lifecycle": "CREATED",
                    "state": "code-write-locked",
                    "code_writes_allowed": False,
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "coordinator-summary.json").write_text(
            json.dumps({"next_action": {"command": "dispatch-beat"}}),
            encoding="utf-8",
        )
        return repo, run_dir

    def test_import_legacy_run_converges_state_into_control_plane(self) -> None:
        repo, run_dir = self.write_legacy_created_run()

        result = control_plane.import_legacy(repo, run_dir)

        self.assertTrue(result["ready"])
        data = json.loads((run_dir / "control-plane.json").read_text(encoding="utf-8"))
        self.assertEqual(data["lifecycle"], "CREATED")
        self.assertEqual(data["tasks"][0]["id"], "T01")
        self.assertEqual(data["tasks"][0]["role_group"], "design")
        self.assertEqual(data["tasks"][0]["runtime_subagent_type"], "requirements-clarifier")
        self.assertEqual(data["projections"]["run-state.json"]["mode"], "compat")

    def make_control_plane_with_task(self, task_id: str) -> tuple[Path, Path]:
        repo, run_dir = self.make_run_dir()
        control_plane.create(repo, run_dir, run_id="docs/agent-runs/run")
        path = run_dir / "control-plane.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tasks"] = [
            {
                "id": task_id,
                "agent": "requirements-clarifier",
                "phase": "clarify",
                "role_group": "design",
                "outputs": ["docs/design/example.md"],
                "status": "planned",
            }
        ]
        path.write_text(json.dumps(data), encoding="utf-8")
        return repo, run_dir

    def test_legacy_projections_are_derived_from_control_plane(self) -> None:
        repo, run_dir = self.make_control_plane_with_task("T01")

        result = control_plane.write_legacy_projections(repo, run_dir)

        self.assertTrue(result["ready"])
        state = json.loads((run_dir / "run-state.json").read_text(encoding="utf-8"))
        schedule = json.loads((run_dir / "agent-schedule.json").read_text(encoding="utf-8"))
        phase_lock = json.loads((run_dir / ".phase-lock").read_text(encoding="utf-8"))
        summary = json.loads((run_dir / "coordinator-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(state["source"], "control-plane.json")
        self.assertEqual(schedule["source"], "control-plane.json")
        self.assertEqual(schedule["tasks"][0]["id"], "T01")
        self.assertEqual(phase_lock["source"], "control-plane.json")
        self.assertEqual(summary["source"], "control-plane.json")

    def test_task_factory_fills_required_contract_for_repair_task(self) -> None:
        task = control_plane.task_contract(
            task_id="T01b",
            agent="requirements-clarifier",
            phase="clarify",
            kind="artifact_repair",
            outputs=["docs/design/example.md"],
            repair_targets=["docs/design/example.md"],
        )

        self.assertEqual(task["id"], "T01b")
        self.assertEqual(task["role_group"], "design")
        self.assertEqual(task["runtime_subagent_type"], "requirements-clarifier")
        self.assertEqual(task["dispatch_contract"], "fresh-subagent")
        self.assertEqual(task["kind"], "artifact_repair")
        self.assertEqual(task["repair_targets"], ["docs/design/example.md"])

    def test_repair_transaction_prevents_duplicate_active_repair_tasks(self) -> None:
        repo, run_dir = self.make_control_plane_with_task("T01")

        first = control_plane.open_repair_transaction(
            repo,
            run_dir,
            code="impact_summary_too_long",
            target="docs/design/example.md",
        )
        second = control_plane.open_repair_transaction(
            repo,
            run_dir,
            code="impact_summary_too_long",
            target="docs/design/example.md",
        )

        self.assertTrue(first["ready"])
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(second["status"], "already_open")
        data = json.loads((run_dir / "control-plane.json").read_text(encoding="utf-8"))
        repair_tasks = [task for task in data["tasks"] if task.get("kind") == "artifact_repair"]
        self.assertEqual(1, len(repair_tasks))

    def test_dispatch_ack_updates_control_plane_then_projects_legacy_state(self) -> None:
        repo, run_dir = self.make_control_plane_with_task("T01")
        path = run_dir / "control-plane.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        dispatch = {
            "status": "awaiting_runtime_spawn",
            "runtime": "manual",
            "current_task_id": "T01",
            "current_agent": "requirements-clarifier",
        }
        data["dispatch"] = dict(dispatch)
        data["dispatches"] = {"T01": dict(dispatch)}
        path.write_text(json.dumps(data), encoding="utf-8")
        control_plane.write_legacy_projections(repo, run_dir)

        ack = state_store.dispatch_ack(
            repo,
            run_dir / "run-state.json",
            "T01",
            "requirements-clarifier",
            "worker-1",
        )

        self.assertTrue(ack["ready"], ack.get("blocked_reasons"))
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["dispatches"]["T01"]["status"], "worker_running")
        self.assertTrue((run_dir / "run-state.json").exists())

    def test_later_dispatch_attempt_is_not_overwritten_by_stale_completed_event(self) -> None:
        repo, run_dir = self.make_control_plane_with_task("T03")
        path = run_dir / "control-plane.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        running_dispatch = {
            "status": "worker_running",
            "runtime": "claude-code",
            "current_task_id": "T03",
            "current_agent": "design-reviewer",
            "worker_handle": "fresh-reviewer-worker",
            "worker_session": "fresh-reviewer-worker",
            "started_at": "2026-06-07T02:24:42Z",
            "spawn_acknowledged_at": "2026-06-07T02:31:44Z",
            "spawn_confirmed_by": "dispatch_ack",
        }
        data["dispatch"] = dict(running_dispatch)
        data["dispatches"] = {
            "T03": {
                **running_dispatch,
                "status": "worker_completed",
                "completed_at": "2026-06-07T02:23:57Z",
                "evidence": ["docs/agent-runs/run/reviews/R1-design-review.md"],
            }
        }
        data["tasks"][0].update(
            {
                "agent": "design-reviewer",
                "phase": "r1-review",
                "role_group": "review",
                "status": "claimed",
                "owner": "design-reviewer",
                "claimed_at": "2026-06-07T02:24:42Z",
                "heartbeat_at": "2026-06-07T02:24:42Z",
                "completed_at": "2026-06-07T02:23:57Z",
                "evidence": ["docs/agent-runs/run/reviews/R1-design-review.md"],
            }
        )
        path.write_text(json.dumps(data), encoding="utf-8")
        event_dir = run_dir / "dispatch-events"
        event_dir.mkdir()
        (event_dir / "T03-completed.json").write_text(
            json.dumps(
                {
                    "schema": "e2e-dev-harness.dispatch-event.v1",
                    "event": "worker_completed",
                    "task_id": "T03",
                    "agent": "design-reviewer",
                    "evidence": ["docs/agent-runs/run/reviews/R1-design-review.md"],
                    "worker_handle": "fresh-reviewer-worker",
                    "worker_session": "fresh-reviewer-worker",
                    "created_at": "2026-06-07T02:23:57Z",
                }
            ),
            encoding="utf-8",
        )
        (event_dir / "T03-dispatched.json").write_text(
            json.dumps(
                {
                    "schema": "e2e-dev-harness.dispatch-event.v1",
                    "event": "worker_dispatched",
                    "task_id": "T03",
                    "agent": "design-reviewer",
                    "runtime": "claude-code",
                    "created_at": "2026-06-07T02:24:42Z",
                }
            ),
            encoding="utf-8",
        )

        result = control_plane.write_legacy_projections(repo, run_dir)

        self.assertTrue(result["ready"], result.get("blocked_reasons"))
        state = json.loads((run_dir / "run-state.json").read_text(encoding="utf-8"))
        schedule = json.loads((run_dir / "agent-schedule.json").read_text(encoding="utf-8"))
        self.assertEqual("worker_running", state["dispatches"]["T03"]["status"])
        self.assertEqual("worker_running", state["dispatch"]["status"])
        self.assertEqual("claimed", schedule["tasks"][0]["status"])
        self.assertNotIn("completed_at", schedule["tasks"][0])

    def test_repair_task_contracts_normalizes_tasks_and_projects_legacy_state(self) -> None:
        repo, run_dir = self.make_control_plane_with_task("T01")
        path = run_dir / "control-plane.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tasks"][0].pop("role_group", None)
        data["tasks"][0].pop("dispatch_contract", None)
        data["tasks"][0].pop("runtime_subagent_type", None)
        path.write_text(json.dumps(data), encoding="utf-8")

        result = control_plane.repair(repo, run_dir, scope="task-contracts")

        self.assertTrue(result["ready"], result.get("blocked_reasons"))
        self.assertEqual(["task-contracts"], result["scopes"])
        repaired = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("design", repaired["tasks"][0]["role_group"])
        self.assertEqual("fresh-subagent", repaired["tasks"][0]["dispatch_contract"])
        self.assertEqual("requirements-clarifier", repaired["tasks"][0]["runtime_subagent_type"])
        schedule = json.loads((run_dir / "agent-schedule.json").read_text(encoding="utf-8"))
        self.assertEqual("design", schedule["tasks"][0]["role_group"])


class ControlPlaneSsotRegression(unittest.TestCase):
    def _make_run(self, tmp: str):
        repo = Path(tmp)
        run_dir = repo / "docs" / "agent-runs" / "run"
        run_dir.mkdir(parents=True)
        control_plane.create(repo, run_dir, run_id="docs/agent-runs/run")
        # Clarify done: lifecycle CLARIFIED, only the clarify task exists in the control plane.
        control_plane.transition_lifecycle(
            repo, run_dir, "CLARIFIED", gate="clarification", gate_status="passed"
        )
        t01 = control_plane.task_contract("T01", "requirements-clarifier", "clarify", status="completed")
        data = control_plane.load(repo, run_dir)
        data["tasks"] = [t01]
        from common import atomic_write_json
        atomic_write_json(control_plane.control_plane_path(run_dir), data)
        control_plane.write_legacy_projections(repo, run_dir)
        return repo, run_dir

    def test_dispatch_ack_does_not_drop_expanded_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run_dir = self._make_run(tmp)
            # Planner expands the schedule THROUGH the control plane (P2 contract).
            expanded = [
                control_plane.task_contract("T01", "requirements-clarifier", "clarify", status="completed"),
                control_plane.task_contract("T06", "service-designer-jeepay-core", "design", service="jeepay-core"),
            ]
            control_plane.replace_tasks(repo, run_dir, expanded, lifecycle="SERVICE_DESIGN_REQUIRED")
            # A dispatch-ack for T06 must NOT shrink the schedule back to clarify-only.
            control_plane.dispatch_acknowledged(
                repo, run_dir, {"current_task_id": "T06", "current_agent": "service-designer-jeepay-core", "status": "worker_running"}
            )
            schedule = json.loads((run_dir / "agent-schedule.json").read_text(encoding="utf-8"))
            ids = [t["id"] for t in schedule["tasks"]]
            self.assertIn("T06", ids, "dispatch-ack must not drop the expanded task set")
            self.assertIn("T01", ids)

    def test_replace_tasks_persists_into_control_plane_and_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run_dir = self._make_run(tmp)
            tasks = [
                control_plane.task_contract("T01", "requirements-clarifier", "clarify", status="completed"),
                control_plane.task_contract("T02", "service-designer-core", "design", service="core"),
            ]
            result = control_plane.replace_tasks(repo, run_dir, tasks, lifecycle="SERVICE_DESIGN_REQUIRED")
            self.assertTrue(result["ready"])
            data = control_plane.load(repo, run_dir)
            self.assertEqual([t["id"] for t in data["tasks"]], ["T01", "T02"])
            self.assertEqual(data["lifecycle"], "SERVICE_DESIGN_REQUIRED")
            schedule = json.loads((run_dir / "agent-schedule.json").read_text(encoding="utf-8"))
            self.assertEqual([t["id"] for t in schedule["tasks"]], ["T01", "T02"])


if __name__ == "__main__":
    unittest.main()
