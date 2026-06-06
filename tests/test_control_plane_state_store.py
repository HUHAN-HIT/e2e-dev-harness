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


if __name__ == "__main__":
    unittest.main()
