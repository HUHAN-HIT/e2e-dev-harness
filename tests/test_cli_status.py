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


class CliStatusTests(unittest.TestCase):
    def test_write_status_creates_parent_and_preserves_json_format(self) -> None:
        from e2e_harness.cli.status import write_status  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            status_file = Path(tmp) / "nested" / "status.json"
            payload = {"ready": True, "message": "ok"}

            write_status(status_file, payload)
            text = status_file.read_text(encoding="utf-8")

        self.assertTrue(text.endswith("\n"))
        self.assertEqual(payload, json.loads(text))
        self.assertIn('  "ready": true', text)

    def test_write_status_noops_when_path_missing(self) -> None:
        from e2e_harness.cli.status import write_status  # noqa: PLC0415

        write_status(None, {"ready": True})


if __name__ == "__main__":
    unittest.main()
