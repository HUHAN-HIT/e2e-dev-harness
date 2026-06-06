"""Harness artifact lifecycle garbage-collection tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"


def write_run(run_dir: Path, lifecycle: str, age_days: int = 0, pinned: bool = False) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run-state.json").write_text(
        json.dumps(
            {
                "schema": "e2e-dev-harness.run-state.v1",
                "run_id": run_dir.as_posix(),
                "lifecycle": lifecycle,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "coordinator-results").mkdir()
    (run_dir / "coordinator-results" / "next.json").write_text('{"ready": true}\n', encoding="utf-8")
    if pinned:
        (run_dir / ".gc-pin").write_text("keep\n", encoding="utf-8")
    if age_days:
        stamp = time.time() - (age_days * 24 * 60 * 60)
        for path in [run_dir, run_dir / "run-state.json", run_dir / "coordinator-results", run_dir / "coordinator-results" / "next.json"]:
            os.utime(path, (stamp, stamp))


class GcRunCliTests(unittest.TestCase):
    def test_gc_run_dry_run_reports_old_archived_runs_without_deleting_protected_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            runs = repo / "docs" / "agent-runs"
            old_archived = runs / "2026-01-01-old"
            latest_archived = runs / "2026-06-01-latest"
            active = runs / "2026-01-02-active"
            pinned = runs / "2026-01-03-pinned"
            write_run(old_archived, "ARCHIVED", age_days=90)
            write_run(latest_archived, "ARCHIVED", age_days=1)
            write_run(active, "PLANNED", age_days=90)
            write_run(pinned, "ARCHIVED", age_days=90, pinned=True)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "e2e_dev_harness.py"),
                    "gc:run",
                    str(repo),
                    "--agent-runs",
                    "docs/agent-runs",
                    "--keep-latest",
                    "1",
                    "--max-age-days",
                    "30",
                    "--json-full",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["ready"], payload)
            self.assertTrue(payload["dry_run"])
            self.assertEqual(1, payload["delete_candidate_count"])
            by_run = {item["run_id"]: item for item in payload["runs"]}
            self.assertEqual("would_delete", by_run["2026-01-01-old"]["decision"])
            self.assertEqual("keep_latest", by_run["2026-06-01-latest"]["decision"])
            self.assertEqual("active_lifecycle", by_run["2026-01-02-active"]["decision"])
            self.assertEqual("pinned", by_run["2026-01-03-pinned"]["decision"])
            self.assertTrue(old_archived.exists(), "dry-run must not delete eligible runs")
            self.assertTrue(active.exists())
            self.assertTrue(pinned.exists())

    def test_gc_run_rejects_negative_retention_values_before_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            old_archived = repo / "docs" / "agent-runs" / "2026-01-01-old"
            write_run(old_archived, "ARCHIVED", age_days=90)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "e2e_dev_harness.py"),
                    "gc:run",
                    str(repo),
                    "--agent-runs",
                    "docs/agent-runs",
                    "--max-age-days",
                    "-1",
                    "--execute",
                    "--json-full",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(2, completed.returncode)
            self.assertIn("max-age-days must be non-negative", completed.stderr)
            self.assertTrue(old_archived.exists(), "invalid retention policy must not delete runs")

    def test_gc_run_execute_prunes_old_coordinator_results_without_deleting_retained_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            retained = repo / "docs" / "agent-runs" / "2026-06-01-retained"
            write_run(retained, "ARCHIVED", age_days=1)
            results_dir = retained / "coordinator-results"
            old_result = results_dir / "20260101T000000Z-next.json"
            latest_result = results_dir / "20260601T000000Z-next.json"
            old_result.write_text('{"old": true}\n', encoding="utf-8")
            latest_result.write_text('{"latest": true}\n', encoding="utf-8")
            (results_dir / "index.jsonl").write_text('{"schema":"index"}\n', encoding="utf-8")
            old_stamp = time.time() - (90 * 24 * 60 * 60)
            latest_stamp = time.time() - (1 * 24 * 60 * 60)
            os.utime(old_result, (old_stamp, old_stamp))
            os.utime(latest_result, (latest_stamp, latest_stamp))

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "e2e_dev_harness.py"),
                    "gc:run",
                    str(repo),
                    "--agent-runs",
                    "docs/agent-runs",
                    "--keep-results-latest",
                    "2",
                    "--execute",
                    "--json-full",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(1, payload["deleted_result_count"])
            self.assertTrue(retained.exists())
            self.assertFalse(old_result.exists())
            self.assertTrue(latest_result.exists())
            self.assertTrue((results_dir / "index.jsonl").exists())

    def test_gc_run_dry_run_reports_old_coordinator_result_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            retained = repo / "docs" / "agent-runs" / "2026-06-01-retained"
            write_run(retained, "ARCHIVED", age_days=1)
            results_dir = retained / "coordinator-results"
            old_result = results_dir / "20260101T000000Z-next.json"
            latest_result = results_dir / "20260601T000000Z-next.json"
            old_result.write_text('{"old": true}\n', encoding="utf-8")
            latest_result.write_text('{"latest": true}\n', encoding="utf-8")
            (results_dir / "index.jsonl").write_text('{"schema":"index"}\n', encoding="utf-8")
            old_stamp = time.time() - (90 * 24 * 60 * 60)
            latest_stamp = time.time() - (1 * 24 * 60 * 60)
            os.utime(old_result, (old_stamp, old_stamp))
            os.utime(latest_result, (latest_stamp, latest_stamp))

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "e2e_dev_harness.py"),
                    "gc:run",
                    str(repo),
                    "--agent-runs",
                    "docs/agent-runs",
                    "--keep-results-latest",
                    "2",
                    "--json-full",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["dry_run"])
            self.assertEqual(1, payload["result_delete_candidate_count"])
            self.assertIn("docs/agent-runs/2026-06-01-retained/coordinator-results/20260101T000000Z-next.json", payload["would_delete_results"])
            self.assertEqual(0, payload["deleted_result_count"])
            self.assertTrue(old_result.exists(), "dry-run must not delete coordinator result candidates")


if __name__ == "__main__":
    unittest.main()
