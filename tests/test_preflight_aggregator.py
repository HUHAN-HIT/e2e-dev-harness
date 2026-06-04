"""Single-pass preflight aggregator: consolidate all applicable gate blockers.

The aggregator answers, in one call, "what blocks the current run-state and what
is the single next action?" so the coordinator fixes the whole blocker chain at
once instead of hitting one gate, fixing it, then hitting the next.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import e2e_dev_harness as harness  # noqa: E402


def _write_state(repo: Path, lifecycle: str) -> Path:
    state = repo / "docs" / "agent-runs" / "run" / "run-state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"lifecycle": lifecycle, "run_id": "r1"}),
        encoding="utf-8",
    )
    return state


def _write_multi_state(repo: Path, lifecycle: str) -> Path:
    state = repo / "docs" / "agent-runs" / "run" / "run-state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps(
            {
                "lifecycle": lifecycle,
                "run_id": "r1",
                "selected_mode": "multi",
                "services": ["svc-a", "svc-b"],
            }
        ),
        encoding="utf-8",
    )
    return state


def _write_schedule(state_path: Path, tasks: list) -> Path:
    schedule = state_path.parent / "agent-schedule.json"
    schedule.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
    return schedule


class PreflightAggregatorTests(unittest.TestCase):
    def test_created_state_consolidates_clarification_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state = _write_state(repo, "CREATED")

            result = harness.aggregate_preflight_blockers(repo, state)

            self.assertFalse(result["ready"])
            self.assertEqual(1, len(result["blockers"]))
            blocker = result["blockers"][0]
            self.assertEqual("clarification", blocker["gate"])
            self.assertEqual("CREATED", blocker["return_phase"])
            self.assertEqual(1, blocker["order"])
            self.assertIn("agent-schedule.json", blocker["message"])
            self.assertTrue(blocker["code"].startswith("BLK_"))
            self.assertTrue(blocker["minimal_fix"])
            self.assertEqual(blocker["minimal_fix"], result["next_single_action"])

    def test_state_without_applicable_gate_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state = _write_state(repo, "CLARIFIED")

            result = harness.aggregate_preflight_blockers(repo, state)

            self.assertTrue(result["ready"])
            self.assertEqual([], result["blockers"])
            self.assertEqual("", result["next_single_action"])

    def test_multi_service_planned_consolidates_tdd_red_dispatch_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state = _write_multi_state(repo, "PLANNED")
            _write_schedule(
                state,
                [
                    {
                        "id": "t-red",
                        "agent": "tdd-red-author",
                        "phase": "tdd-red",
                        "service": "svc-a",
                        "status": "pending",
                    },
                    {
                        "id": "t-r2",
                        "agent": "r2-reviewer",
                        "phase": "r2-review",
                        "status": "pending",
                    },
                ],
            )

            result = harness.aggregate_preflight_blockers(repo, state)

            self.assertFalse(result["ready"])
            gates = [blocker["gate"] for blocker in result["blockers"]]
            self.assertIn("tdd_red", gates)
            blocker = next(b for b in result["blockers"] if b["gate"] == "tdd_red")
            self.assertEqual("PLANNED", blocker["return_phase"])
            self.assertTrue(blocker["code"].startswith("BLK_"))
            self.assertTrue(blocker["minimal_fix"])
            self.assertTrue(blocker["message"])

    def test_single_service_planned_skips_tdd_red_dispatch_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state = _write_state(repo, "PLANNED")
            _write_schedule(
                state,
                [
                    {
                        "id": "t-red",
                        "agent": "tdd-red-author",
                        "phase": "tdd-red",
                        "service": "svc-a",
                        "status": "pending",
                    },
                ],
            )

            result = harness.aggregate_preflight_blockers(repo, state)

            self.assertTrue(result["ready"])
            self.assertEqual([], result["blockers"])

    def test_preflight_command_blocks_with_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state = _write_state(repo, "CREATED")
            args = argparse.Namespace(
                repo=repo,
                state=state,
                status_file=None,
                json_full=False,
            )

            exit_code, result = harness.preflight(args)

            self.assertEqual(2, exit_code)
            self.assertFalse(result["ready"])
            self.assertGreaterEqual(len(result["blockers"]), 1)

    def test_preflight_command_facade_preserves_status_file_contract(self) -> None:
        from e2e_harness.cli.commands import preflight as preflight_command  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state = _write_state(repo, "CREATED")
            status_file = repo / "preflight-status.json"

            exit_code, result = preflight_command.run(repo, state=state, status_file=status_file)
            status = json.loads(status_file.read_text(encoding="utf-8"))

            self.assertEqual(2, exit_code)
            self.assertFalse(result["ready"])
            self.assertEqual(result, status)
            self.assertGreaterEqual(len(result["blockers"]), 1)


if __name__ == "__main__":
    unittest.main()
