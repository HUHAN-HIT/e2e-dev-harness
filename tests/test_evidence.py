"""Command evidence, TDD evidence, and command-split tests."""
from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import command_evidence  # noqa: E402
import e2e_dev_harness  # noqa: E402
import tdd_evidence  # noqa: E402
from common import atomic_write_json, now_iso, read_json_object, split_command  # noqa: E402
from conftest import write_command_evidence  # noqa: E402


class CommandSplitTests(unittest.TestCase):
    def test_simple_graph_command_splits_without_shell(self) -> None:
        self.assertEqual(["graphify", "update", "."], split_command("graphify update ."))

    def test_shell_control_operators_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            split_command("graphify update . && echo unsafe")


class CommonHelperTests(unittest.TestCase):
    def test_read_json_object_returns_empty_for_missing_invalid_or_non_object_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            invalid = repo / "invalid.json"
            array_json = repo / "array.json"
            invalid.write_text("{not json", encoding="utf-8")
            array_json.write_text("[]", encoding="utf-8")

            self.assertEqual({}, read_json_object(None))
            self.assertEqual({}, read_json_object(repo / "missing.json"))
            self.assertEqual({}, read_json_object(invalid))
            self.assertEqual({}, read_json_object(array_json))

    def test_atomic_write_json_round_trips_utf8_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "data.json"

            atomic_write_json(target, {"message": "支付", "ok": True})

            self.assertEqual({"message": "支付", "ok": True}, json.loads(target.read_text(encoding="utf-8")))
            self.assertTrue(target.read_text(encoding="utf-8").endswith("\n"))

    def test_now_iso_returns_utc_z_timestamp(self) -> None:
        self.assertRegex(now_iso(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")




class CommandEvidenceTests(unittest.TestCase):
    def test_command_evidence_captures_exit_code_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = command_evidence.run_command(Path(tmp), f"{sys.executable} -c \"print('ok')\"", timeout_seconds=30)

        self.assertEqual(0, result["exit_code"])
        self.assertEqual("e2e-dev-harness.command-evidence.v1", result["schema"])
        self.assertIn("ok", result["stdout_tail"])
        self.assertEqual(64, len(result["stdout_sha256"]))

    def test_command_evidence_rejects_shell_control_operators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = command_evidence.run_command(Path(tmp), "python -V && echo unsafe", timeout_seconds=30)

        self.assertEqual(2, result["exit_code"])
        self.assertIn("Shell control operators", result["stderr_tail"])

    def test_command_evidence_cli_prints_compact_stdout_and_writes_full_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            output = Path("docs/agent-runs/run/evidence/command.json")
            stdout = io.StringIO()
            argv = [
                "e2e_dev_harness.py",
                "command-evidence",
                str(repo),
                "--command",
                f"{sys.executable} -c \"print('compact-cli-ok')\"",
                "--output",
                output.as_posix(),
            ]

            with patch.object(sys, "argv", argv), patch("sys.stdout", stdout):
                exit_code = e2e_dev_harness.main()

            compact = json.loads(stdout.getvalue())
            evidence = json.loads((repo / output).read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual(
            {
                "ready",
                "exit_code",
                "evidence_path",
                "stdout_sha256",
                "stderr_sha256",
                "elapsed_ms",
            },
            set(compact),
        )
        self.assertTrue(compact["ready"])
        self.assertEqual(0, compact["exit_code"])
        self.assertIn("compact-cli-ok", evidence["stdout_tail"])
        self.assertEqual(compact["stdout_sha256"], evidence["stdout_sha256"])




class TddEvidenceTests(unittest.TestCase):
    def test_basic_tdd_accepts_lightweight_red_failure_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            red = repo / "red.txt"
            red.write_text("Red test failed for expected reason in QuoteServiceTest.\n", encoding="utf-8")

            result = tdd_evidence.validate(repo, red, mode="basic")

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("basic", result["effective_mode"])

    def test_strict_tdd_blocks_red_command_that_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            red = repo / "red.json"
            write_command_evidence(red, "mvn -pl services/a -am test", exit_code=0)

            result = tdd_evidence.validate(repo, red, mode="strict")

        self.assertFalse(result["ready"])
        self.assertTrue(any("unexpectedly passed" in reason for reason in result["blocked_reasons"]))

    def test_strict_tdd_completion_requires_green_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            red = repo / "red.json"
            green = repo / "green.json"
            write_command_evidence(red, "mvn -pl services/a -am test", exit_code=1)
            write_command_evidence(green, "mvn -pl services/a -am test", exit_code=0)

            result = tdd_evidence.validate(repo, red, green, phase="completion", mode="strict")

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(1, result["red_commands"][0]["exit_code"])
        self.assertEqual(0, result["green_commands"][0]["exit_code"])

    def test_auto_tdd_uses_strict_for_critical_tier(self) -> None:
        self.assertEqual("strict", tdd_evidence.resolve_mode("auto", "critical"))
        self.assertEqual("basic", tdd_evidence.resolve_mode("auto", "standard"))




if __name__ == "__main__":
    unittest.main()
