from __future__ import annotations

import json
import sys
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import e2e_dev_harness  # noqa: E402
import harness_doctor  # noqa: E402


class HarnessDoctorTests(unittest.TestCase):
    def test_doctor_reports_tooling_and_hook_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            side_effect=lambda name: f"C:/tools/{name}.exe" if name in {"pytest", "mvn", "gitnexus"} else "",
        ):
            repo = Path(tmp)
            (repo / "pom.xml").write_text("<project />\n", encoding="utf-8")

            result = harness_doctor.evaluate(repo)

        checks = {item["id"]: item for item in result["checks"]}
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("pass", checks["python"]["status"])
        self.assertEqual("pass", checks["maven"]["status"])
        self.assertEqual("pass", checks["gitnexus"]["status"])
        self.assertEqual("warn", checks["claude-hooks"]["status"])

    def test_doctor_strict_treats_warnings_as_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            side_effect=lambda name: f"C:/tools/{name}.exe" if name in {"pytest", "mvn", "gitnexus"} else "",
        ):
            repo = Path(tmp)
            result = harness_doctor.evaluate(repo, strict=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("No common project markers" in reason for reason in result["blocked_reasons"]))

    def test_unified_cli_doctor_writes_status_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            return_value="C:/tools/tool.exe",
        ):
            repo = Path(tmp)
            status = repo / "doctor.json"
            code, result = e2e_dev_harness.doctor(
                SimpleNamespace(repo=repo, strict=False, status_file=status)
            )
            status_exists = status.exists()
            saved = json.loads(status.read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertEqual(result["schema"], saved["schema"])
        self.assertTrue(status_exists)


if __name__ == "__main__":
    unittest.main()
