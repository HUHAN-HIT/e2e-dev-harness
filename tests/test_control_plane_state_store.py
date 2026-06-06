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


if __name__ == "__main__":
    unittest.main()
