"""Node installer smoke tests."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "tools" / "install-e2e-dev-harness.mjs"


class NodeInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node is not available")

    def run_installer(self, *args: str) -> tuple[int, dict]:
        completed = subprocess.run(
            ["node", str(INSTALLER), *args, "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            self.fail(
                f"installer did not return JSON\nexit={completed.returncode}\nstdout={completed.stdout}\nstderr={completed.stderr}\nerror={error}"
            )
        return completed.returncode, payload

    def test_dry_run_plans_codex_install_without_writing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            code, payload = self.run_installer(
                "--install-root",
                str(target),
                "--target",
                "codex",
                "--skip-python-cli",
                "--skip-external",
            )

            self.assertEqual(0, code, payload)
            self.assertFalse(payload["executed"])
            self.assertEqual(["codex"], payload["targets"])
            self.assertEqual("dry-run", payload["mode"])
            self.assertFalse((target / ".codex" / "skills" / "e2e-dev-harness").exists())
            self.assertIn("copy-skill", [action["id"] for action in payload["actions"]])

    def test_yes_copies_skill_and_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            code, payload = self.run_installer(
                "--install-root",
                str(target),
                "--target",
                "codex",
                "--skip-python-cli",
                "--skip-external",
                "--yes",
            )

            skill_dir = target / ".codex" / "skills" / "e2e-dev-harness"
            manifest = target / ".e2e-dev-harness-install.json"
            self.assertEqual(0, code, payload)
            self.assertTrue(payload["executed"])
            self.assertTrue(skill_dir.exists())
            self.assertTrue((skill_dir / "SKILL.md").exists())
            self.assertTrue(manifest.exists())
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(["codex"], manifest_payload["targets"])
            self.assertEqual(str(skill_dir), manifest_payload["installed_skills"][0]["path"])

    def test_external_dependencies_are_not_installed_unless_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            code, payload = self.run_installer(
                "--install-root",
                str(target),
                "--target",
                "codex",
                "--skip-python-cli",
            )

            self.assertEqual(0, code, payload)
            external_actions = [
                action for action in payload["actions"]
                if action["id"] in {"install-gitnexus", "install-graphify"}
            ]
            self.assertEqual([], external_actions)
            self.assertIn("gitnexus", payload["checks"])
            self.assertIn("graphify", payload["checks"])


if __name__ == "__main__":
    unittest.main()
