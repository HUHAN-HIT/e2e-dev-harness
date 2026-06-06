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


if __name__ == "__main__":
    unittest.main()
