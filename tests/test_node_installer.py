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

    def test_project_root_routes_hooks_and_doctor_to_business_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "home"
            project = Path(tmp) / "business-project"
            project.mkdir()

            code, payload = self.run_installer(
                "--install-root",
                str(install_root),
                "--target",
                "claude",
                "--project-root",
                str(project),
                "--skip-python-cli",
                "--skip-external",
                "--with-hooks",
                "--runtime",
                "claude",
                "--doctor",
            )

            self.assertEqual(0, code, payload)
            self.assertEqual(str(project.resolve()), payload["project_root"])
            actions = {action["id"]: action for action in payload["actions"]}
            self.assertIn("install-hooks", actions)
            self.assertIn("doctor", actions)
            self.assertEqual(str(project.resolve()), actions["install-hooks"]["project_root"])
            self.assertIn("e2e-dev-harness", actions["install-hooks"]["scripts_dir"])
            self.assertIn(str(project.resolve()), actions["doctor"]["command"])
            self.assertIn("e2e_dev_harness.py", actions["doctor"]["command"])

    def test_full_preset_keeps_common_setup_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "home"
            project = Path(tmp) / "business-project"
            project.mkdir()

            code, payload = self.run_installer(
                "--install-root",
                str(install_root),
                "--project",
                str(project),
                "--full",
            )

            self.assertEqual(0, code, payload)
            self.assertEqual(str(ROOT.resolve()), payload["repo"])
            self.assertEqual(["codex", "claude", "agents"], payload["targets"])
            self.assertEqual(str(project.resolve()), payload["project_root"])
            self.assertIn("install-hooks", [action["id"] for action in payload["actions"]])
            self.assertIn("doctor", [action["id"] for action in payload["actions"]])
            self.assertTrue(payload["install_external"])
            self.assertEqual("claude", payload["runtime"])

    def test_sync_preset_is_fast_skill_copy_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "home"

            code, payload = self.run_installer(
                "--install-root",
                str(install_root),
                "--sync",
            )

            self.assertEqual(0, code, payload)
            self.assertEqual(["sync"], payload["presets"])
            self.assertEqual(["codex", "claude", "agents"], payload["targets"])
            self.assertTrue(payload["skip_python_cli"])
            self.assertFalse(payload["install_external"])
            self.assertEqual(["copy-skill"], [action["id"] for action in payload["actions"]])

    def test_project_preset_installs_hooks_and_doctor_without_pip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "home"
            project = Path(tmp) / "business-project"
            project.mkdir()

            code, payload = self.run_installer(
                "--install-root",
                str(install_root),
                "--project",
                str(project),
            )

            self.assertEqual(0, code, payload)
            self.assertEqual(["project"], payload["presets"])
            self.assertEqual(["codex", "claude", "agents"], payload["targets"])
            self.assertTrue(payload["skip_python_cli"])
            self.assertEqual(str(project.resolve()), payload["project_root"])
            actions = [action["id"] for action in payload["actions"]]
            self.assertIn("copy-skill", actions)
            self.assertIn("install-hooks", actions)
            self.assertIn("doctor", actions)
            self.assertNotIn("install-python-cli", actions)

    def test_hooks_only_skips_skill_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "home"
            project = Path(tmp) / "business-project"
            project.mkdir()

            code, payload = self.run_installer(
                "--install-root",
                str(install_root),
                "--project-root",
                str(project),
                "--hooks-only",
            )

            self.assertEqual(0, code, payload)
            self.assertEqual(["hooks-only"], payload["presets"])
            self.assertTrue(payload["skip_skill_copy"])
            self.assertEqual(["install-hooks"], [action["id"] for action in payload["actions"]])

    def test_doctor_only_skips_skill_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "home"
            project = Path(tmp) / "business-project"
            project.mkdir()

            code, payload = self.run_installer(
                "--install-root",
                str(install_root),
                "--project-root",
                str(project),
                "--doctor-only",
            )

            self.assertEqual(0, code, payload)
            self.assertEqual(["doctor-only"], payload["presets"])
            self.assertTrue(payload["skip_skill_copy"])
            self.assertEqual(["doctor"], [action["id"] for action in payload["actions"]])

    def test_yes_installs_v2_phase_and_stop_hooks_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "home"
            project = Path(tmp) / "business-project"
            project.mkdir()
            root_settings = ROOT / ".claude" / "settings.json"
            root_settings_before = root_settings.read_bytes() if root_settings.exists() else None

            code, payload = self.run_installer(
                "--install-root",
                str(install_root),
                "--target",
                "claude",
                "--project-root",
                str(project),
                "--skip-python-cli",
                "--skip-external",
                "--with-hooks",
                "--runtime",
                "claude",
                "--yes",
            )

            self.assertEqual(0, code, payload)
            settings_path = project / ".claude" / "settings.json"
            self.assertTrue(settings_path.exists())
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            pre = json.dumps(settings["hooks"]["PreToolUse"])
            stop = json.dumps(settings["hooks"]["Stop"])
            self.assertIn("phase_guard.py", pre)
            self.assertIn("stop_guard.py", stop)
            self.assertNotIn("__HARNESS_SCRIPTS__", pre + stop)
            # hooks must point at the installed v2 skill scripts dir
            self.assertIn("e2e-dev-harness", pre)
            # installer must not touch the dev repo's own settings
            root_settings_after = root_settings.read_bytes() if root_settings.exists() else None
            self.assertEqual(root_settings_before, root_settings_after)
            self.assertIn("install-hooks", [result["action"] for result in payload["action_results"]])

    def test_project_root_must_exist_when_hooks_are_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "home"
            project = Path(tmp) / "missing-project"

            code, payload = self.run_installer(
                "--install-root",
                str(install_root),
                "--target",
                "claude",
                "--project-root",
                str(project),
                "--skip-python-cli",
                "--skip-external",
                "--with-hooks",
                "--runtime",
                "claude",
            )

            self.assertEqual(2, code)
            self.assertFalse(payload["ready"])
            self.assertTrue(any("Project root does not exist" in reason for reason in payload["blocked_reasons"]))


if __name__ == "__main__":
    unittest.main()
