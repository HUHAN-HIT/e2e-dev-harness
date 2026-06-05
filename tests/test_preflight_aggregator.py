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
import install_hooks  # noqa: E402


VALID_DIR_GRAPH = """\
schema: e2e-dev-harness.dir-graph.v1
directories:
  - path: docs
    role: documentation
    required: true
  - path: skills/e2e-dev-harness
    role: harness-skill
    required: true
protected_paths:
  - path: skills/e2e-dev-harness/scripts
    policy: harness-control-plane
state_machine:
  lifecycles: [CREATED, CLARIFIED, SERVICE_DESIGN_REQUIRED, PLANNED, RED_READY, WAITING_DISPATCH, IMPLEMENTED, REVIEWED, VERIFIED, ARCHIVED, REWORK_REQUIRED]
  gate_transitions:
    clarification: CLARIFIED
    service_design: PLANNED
    tdd_red: RED_READY
    implementation: IMPLEMENTED
    completion: VERIFIED
    archive: ARCHIVED
pipeline:
  - lifecycle: CREATED
    phase: clarify
  - lifecycle: CLARIFIED
    phase: r1-design-review
  - lifecycle: SERVICE_DESIGN_REQUIRED
    phase: service-design
  - lifecycle: PLANNED
    phase: plan-tdd-red-r2
  - lifecycle: RED_READY
    phase: implementation-gate
  - lifecycle: IMPLEMENTED
    phase: implement-or-complete
  - lifecycle: REVIEWED
    phase: completion
  - lifecycle: VERIFIED
    phase: archive
skill_contracts:
  - role: requirements-clarifier
    read_scope: root-instructions
    write_scope: clarification-handoff
  - role: use-case-designer
    read_scope: clarified-requirements
    write_scope: use-case-handoff
  - role: implementation-planner
    read_scope: clarified-design
    write_scope: implementation-plan
  - role: test-case-developer
    read_scope: implementation-plan
    write_scope: test-evidence
  - role: code-developer
    read_scope: context-pack
    write_scope: claimed-service-scope
  - role: semantic-reviewer
    read_scope: handoff-and-evidence
    write_scope: semantic-review
  - role: coverage-reviewer
    read_scope: coverage-matrix
    write_scope: coverage-review
"""


INVALID_DIR_GRAPH = VALID_DIR_GRAPH.replace("path: docs", "path: missing-required-dir", 1)


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
    def test_missing_dir_graph_is_optional_for_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state = _write_state(repo, "CLARIFIED")

            result = harness.aggregate_preflight_blockers(repo, state)

            self.assertTrue(result["ready"])
            self.assertEqual([], result["blockers"])

    def test_valid_dir_graph_contract_does_not_block_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "docs").mkdir()
            (repo / "skills" / "e2e-dev-harness" / "scripts").mkdir(parents=True)
            (repo / ".e2e").mkdir()
            (repo / ".e2e" / "dir-graph.yaml").write_text(VALID_DIR_GRAPH, encoding="utf-8")
            state = _write_state(repo, "CLARIFIED")

            result = harness.aggregate_preflight_blockers(repo, state)

            self.assertTrue(result["ready"], result["blockers"])
            self.assertEqual([], result["blockers"])

    def test_invalid_dir_graph_contract_blocks_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "docs").mkdir()
            (repo / "skills" / "e2e-dev-harness" / "scripts").mkdir(parents=True)
            (repo / ".e2e").mkdir()
            (repo / ".e2e" / "dir-graph.yaml").write_text(INVALID_DIR_GRAPH, encoding="utf-8")
            state = _write_state(repo, "CLARIFIED")

            result = harness.aggregate_preflight_blockers(repo, state)

            self.assertFalse(result["ready"])
            blocker = result["blockers"][0]
            self.assertEqual("dir_graph_contract", blocker["gate"])
            self.assertEqual("BLK_DIR_GRAPH_CONTRACT", blocker["code"])
            self.assertIn("missing-required-dir", blocker["message"])

    def test_created_state_consolidates_clarification_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state = _write_state(repo, "CREATED")

            result = harness.aggregate_preflight_blockers(repo, state)

        self.assertFalse(result["ready"])
        self.assertEqual(2, len(result["blockers"]))
        blocker = result["blockers"][0]
        self.assertEqual("runtime_hook", blocker["gate"])
        self.assertEqual("BLK_RUNTIME_HOOK", blocker["code"])
        self.assertEqual("CREATED", blocker["return_phase"])
        self.assertEqual(1, blocker["order"])
        self.assertIn("install_hooks", blocker["minimal_fix"])
        self.assertEqual(blocker["minimal_fix"], result["next_single_action"])
        self.assertEqual("clarification", result["blockers"][1]["gate"])

    def test_missing_runtime_hook_blocks_dispatch_preflight_with_install_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state = _write_state(repo, "PLANNED")

            result = harness.aggregate_preflight_blockers(repo, state)

        self.assertFalse(result["ready"])
        blocker = result["blockers"][0]
        self.assertEqual("runtime_hook", blocker["gate"])
        self.assertEqual("BLK_RUNTIME_HOOK", blocker["code"])
        self.assertEqual("PLANNED", blocker["return_phase"])
        self.assertIn("install_hooks", blocker["message"])
        self.assertIn("install_hooks", blocker["minimal_fix"])
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
            install_hooks.install(repo, "claude")
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
