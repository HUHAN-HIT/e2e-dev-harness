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
import run_state  # noqa: E402


def write_state_doctor_fixture(repo: Path) -> Path:
    run_dir = repo / "docs" / "agent-runs" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    registry = run_dir / "artifact-registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "e2e-dev-harness.artifact-registry.v1",
                "run_id": "docs/agent-runs/run",
                "selected_mode": "single",
                "services": [],
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    state_path = run_dir / "run-state.json"
    state = run_state.build_state(
        "docs/agent-runs/run",
        "single",
        [],
        "docs/agent-runs/run/artifact-registry.json",
        "CREATED",
    )
    state["dispatch"] = {
        "status": "worker_completed",
        "current_task_id": "T01",
        "current_agent": "requirements-clarifier",
    }
    state["dispatches"] = {
        "T01": {
            "status": "worker_completed",
            "current_task_id": "T01",
            "current_agent": "requirements-clarifier",
        }
    }
    run_state.write_state(repo, state_path, state)
    (run_dir / "agent-schedule.json").write_text(
        json.dumps(
            {
                "schema": "e2e-dev-harness.agent-schedule.v1",
                "completion_mode": "dispatcher-confirmed",
                "tasks": [
                    {
                        "id": "T01",
                        "agent": "requirements-clarifier",
                        "phase": "clarify",
                        "status": "completed",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    event_dir = run_dir / "dispatch-events"
    event_dir.mkdir()
    (event_dir / "T01-completed.json").write_text(
        json.dumps(
            {
                "schema": "e2e-dev-harness.dispatch-event.v1",
                "event": "worker_completed",
                "task_id": "T01",
                "agent": "requirements-clarifier",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "coordinator-summary.json").write_text(
        json.dumps(
            {
                "schema": "e2e-dev-harness.coordinator-summary.v1",
                "run_id": "docs/agent-runs/run",
                "lifecycle": "CREATED",
            }
        ),
        encoding="utf-8",
    )
    return state_path


class HarnessDoctorTests(unittest.TestCase):
    def test_doctor_warns_when_dir_graph_is_missing(self) -> None:
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
        self.assertEqual("warn", checks["dir-graph"]["status"])
        self.assertIn(".e2e/dir-graph.yaml", checks["dir-graph"]["message"])

    def test_doctor_blocks_dir_graph_pipeline_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            side_effect=lambda name: f"C:/tools/{name}.exe" if name in {"pytest", "mvn", "gitnexus"} else "",
        ):
            repo = Path(tmp)
            (repo / "pom.xml").write_text("<project />\n", encoding="utf-8")
            graph_dir = repo / ".e2e"
            graph_dir.mkdir()
            (graph_dir / "dir-graph.yaml").write_text(
                "\n".join(
                    [
                        "schema: e2e-dev-harness.dir-graph.v1",
                        "directories:",
                        "  - path: docs",
                        "protected_paths: []",
                        "state_machine:",
                        "  lifecycles: [CREATED, CLARIFIED, SERVICE_DESIGN_REQUIRED, PLANNED, RED_READY, WAITING_DISPATCH, IMPLEMENTED, REVIEWED, REWORK_REQUIRED, VERIFIED, ARCHIVED]",
                        "  gate_transitions:",
                        "    clarification: CLARIFIED",
                        "    service_design: PLANNED",
                        "    tdd_red: RED_READY",
                        "    implementation: IMPLEMENTED",
                        "    completion: VERIFIED",
                        "    archive: ARCHIVED",
                        "pipeline:",
                        "  - lifecycle: CREATED",
                        "    phase: clarify",
                        "skill_contracts:",
                        "  - role: requirements-clarifier",
                        "    write_scope: docs/agent-runs/<run>/handoffs",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = harness_doctor.evaluate(repo)

        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(result["ready"])
        self.assertEqual("fail", checks["dir-graph"]["status"])
        self.assertIn("pipeline does not match", checks["dir-graph"]["message"])

    def test_doctor_blocks_dir_graph_missing_worker_role_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            side_effect=lambda name: f"C:/tools/{name}.exe" if name in {"pytest", "mvn", "gitnexus"} else "",
        ):
            repo = Path(tmp)
            (repo / "pom.xml").write_text("<project />\n", encoding="utf-8")
            graph_dir = repo / ".e2e"
            graph_dir.mkdir()
            (graph_dir / "dir-graph.yaml").write_text(
                "\n".join(
                    [
                        "schema: e2e-dev-harness.dir-graph.v1",
                        "directories:",
                        "  - path: docs",
                        "protected_paths: []",
                        "state_machine:",
                        "  lifecycles: [CREATED, CLARIFIED, SERVICE_DESIGN_REQUIRED, PLANNED, RED_READY, WAITING_DISPATCH, IMPLEMENTED, REVIEWED, REWORK_REQUIRED, VERIFIED, ARCHIVED]",
                        "  gate_transitions:",
                        "    clarification: CLARIFIED",
                        "    service_design: PLANNED",
                        "    tdd_red: RED_READY",
                        "    implementation: IMPLEMENTED",
                        "    completion: VERIFIED",
                        "    archive: ARCHIVED",
                        "pipeline:",
                        "  - lifecycle: CREATED",
                        "    phase: clarify",
                        "  - lifecycle: CLARIFIED",
                        "    phase: r1-design-review",
                        "  - lifecycle: SERVICE_DESIGN_REQUIRED",
                        "    phase: service-design",
                        "  - lifecycle: PLANNED",
                        "    phase: plan-tdd-red-r2",
                        "  - lifecycle: RED_READY",
                        "    phase: implementation-gate",
                        "  - lifecycle: IMPLEMENTED",
                        "    phase: implement-or-complete",
                        "  - lifecycle: REVIEWED",
                        "    phase: completion",
                        "  - lifecycle: VERIFIED",
                        "    phase: archive",
                        "skill_contracts:",
                        "  - role: requirements-clarifier",
                        "    write_scope: docs/agent-runs/<run>/handoffs",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = harness_doctor.evaluate(repo)

        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(result["ready"])
        self.assertEqual("fail", checks["dir-graph"]["status"])
        self.assertIn("missing worker role contracts", checks["dir-graph"]["message"])
        self.assertIn("code-developer", checks["dir-graph"]["message"])

    def test_doctor_blocks_dir_graph_unknown_worker_role_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            side_effect=lambda name: f"C:/tools/{name}.exe" if name in {"pytest", "mvn", "gitnexus"} else "",
        ):
            repo = Path(tmp)
            (repo / "pom.xml").write_text("<project />\n", encoding="utf-8")
            graph_dir = repo / ".e2e"
            graph_dir.mkdir()
            (graph_dir / "dir-graph.yaml").write_text(
                "\n".join(
                    [
                        "schema: e2e-dev-harness.dir-graph.v1",
                        "directories:",
                        "  - path: docs",
                        "protected_paths: []",
                        "state_machine:",
                        "  lifecycles: [CREATED, CLARIFIED, SERVICE_DESIGN_REQUIRED, PLANNED, RED_READY, WAITING_DISPATCH, IMPLEMENTED, REVIEWED, REWORK_REQUIRED, VERIFIED, ARCHIVED]",
                        "  gate_transitions:",
                        "    clarification: CLARIFIED",
                        "    service_design: PLANNED",
                        "    tdd_red: RED_READY",
                        "    implementation: IMPLEMENTED",
                        "    completion: VERIFIED",
                        "    archive: ARCHIVED",
                        "pipeline:",
                        "  - lifecycle: CREATED",
                        "    phase: clarify",
                        "  - lifecycle: CLARIFIED",
                        "    phase: r1-design-review",
                        "  - lifecycle: SERVICE_DESIGN_REQUIRED",
                        "    phase: service-design",
                        "  - lifecycle: PLANNED",
                        "    phase: plan-tdd-red-r2",
                        "  - lifecycle: RED_READY",
                        "    phase: implementation-gate",
                        "  - lifecycle: IMPLEMENTED",
                        "    phase: implement-or-complete",
                        "  - lifecycle: REVIEWED",
                        "    phase: completion",
                        "  - lifecycle: VERIFIED",
                        "    phase: archive",
                        "skill_contracts:",
                        "  - role: requirements-clarifier",
                        "  - role: use-case-designer",
                        "  - role: implementation-planner",
                        "  - role: test-case-developer",
                        "  - role: code-developer",
                        "  - role: semantic-reviewer",
                        "  - role: coverage-reviewer",
                        "  - role: reviewer",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = harness_doctor.evaluate(repo)

        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(result["ready"])
        self.assertEqual("fail", checks["dir-graph"]["status"])
        self.assertIn("unknown worker roles", checks["dir-graph"]["message"])
        self.assertIn("reviewer", checks["dir-graph"]["message"])

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
        self.assertEqual("warn", checks["opencode-hooks"]["status"])

    def test_doctor_reports_ready_opencode_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            side_effect=lambda name: f"C:/tools/{name}.exe" if name in {"pytest", "mvn", "gitnexus"} else "",
        ):
            repo = Path(tmp)
            (repo / "pom.xml").write_text("<project />\n", encoding="utf-8")
            import install_hooks  # noqa: PLC0415

            install_hooks.install(repo, "opencode")

            result = harness_doctor.evaluate(repo)

        checks = {item["id"]: item for item in result["checks"]}
        self.assertEqual("pass", checks["opencode-hooks"]["status"])

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

    def test_state_doctor_blocks_completed_schedule_with_running_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            return_value="C:/tools/tool.exe",
        ):
            repo = Path(tmp)
            state_path = write_state_doctor_fixture(repo)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["dispatch"]["status"] = "worker_running"
            state["dispatches"]["T01"]["status"] = "worker_running"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            code, result = e2e_dev_harness.doctor(
                SimpleNamespace(repo=repo, strict=False, status_file=None, state=state_path)
            )

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertTrue(any("T01" in reason and "worker_running" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("dispatch-complete" in item["remediation"] for item in result["checks"] if item["id"] == "state-dispatch-tasks"))

    def test_state_doctor_blocks_completed_schedule_missing_dispatch_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            return_value="C:/tools/tool.exe",
        ):
            repo = Path(tmp)
            state_path = write_state_doctor_fixture(repo)
            (state_path.parent / "dispatch-events" / "T01-completed.json").unlink()

            code, result = e2e_dev_harness.doctor(
                SimpleNamespace(repo=repo, strict=False, status_file=None, state=state_path)
            )

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertTrue(any("T01-completed.json" in reason for reason in result["blocked_reasons"]))

    def test_state_doctor_blocks_stale_phase_lock_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            return_value="C:/tools/tool.exe",
        ):
            repo = Path(tmp)
            state_path = write_state_doctor_fixture(repo)
            lock_path = state_path.parent / run_state.PHASE_LOCK
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["lifecycle"] = "IMPLEMENTED"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            code, result = e2e_dev_harness.doctor(
                SimpleNamespace(repo=repo, strict=False, status_file=None, state=state_path)
            )

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertTrue(any(".phase-lock lifecycle IMPLEMENTED does not match run-state lifecycle CREATED" in reason for reason in result["blocked_reasons"]))

    def test_state_doctor_warns_on_stale_coordinator_summary_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            return_value="C:/tools/tool.exe",
        ):
            repo = Path(tmp)
            state_path = write_state_doctor_fixture(repo)
            summary_path = state_path.parent / "coordinator-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["lifecycle"] = "PLANNED"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")

            code, result = e2e_dev_harness.doctor(
                SimpleNamespace(repo=repo, strict=False, status_file=None, state=state_path)
            )

        self.assertEqual(0, code)
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(any("coordinator-summary lifecycle PLANNED does not match run-state lifecycle CREATED" in warning for warning in result["warnings"]))
        self.assertTrue(any("rebuild coordinator summary" in item["remediation"] for item in result["checks"] if item["id"] == "state-coordinator-summary"))

    def test_state_doctor_warns_legacy_waiting_dispatch_lifecycle_should_migrate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            return_value="C:/tools/tool.exe",
        ):
            repo = Path(tmp)
            state_path = write_state_doctor_fixture(repo)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["lifecycle"] = "WAITING_DISPATCH"
            state["dispatch"] = {
                "status": "waiting_dispatch",
                "runtime": "manual",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            schedule_path = state_path.parent / "agent-schedule.json"
            schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
            schedule["tasks"][0]["status"] = "claimed"
            schedule_path.write_text(json.dumps(schedule), encoding="utf-8")

            code, result = e2e_dev_harness.doctor(
                SimpleNamespace(repo=repo, strict=False, status_file=None, state=state_path)
            )

        checks = {item["id"]: item for item in result["checks"]}
        self.assertEqual(0, code)
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("warn", checks["state-lifecycle"]["status"])
        self.assertIn("WAITING_DISPATCH", checks["state-lifecycle"]["message"])
        self.assertIn("dispatches", checks["state-lifecycle"]["remediation"])

    def test_state_doctor_blocks_missing_lifecycle_with_single_repair_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            return_value="C:/tools/tool.exe",
        ):
            repo = Path(tmp)
            state_path = write_state_doctor_fixture(repo)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.pop("lifecycle")
            state_path.write_text(json.dumps(state), encoding="utf-8")

            code, result = e2e_dev_harness.doctor(
                SimpleNamespace(repo=repo, strict=False, status_file=None, state=state_path)
            )

        checks = {item["id"]: item for item in result["checks"]}
        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertEqual("fail", checks["state-lifecycle"]["status"])
        self.assertIn("missing", checks["state-lifecycle"]["message"])
        self.assertIn("run-state.json", checks["state-lifecycle"]["remediation"])
        self.assertTrue(any("lifecycle is missing" in reason for reason in result["blocked_reasons"]))

    def test_state_doctor_passes_consistent_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            harness_doctor.shutil,
            "which",
            return_value="C:/tools/tool.exe",
        ):
            repo = Path(tmp)
            state_path = write_state_doctor_fixture(repo)

            code, result = e2e_dev_harness.doctor(
                SimpleNamespace(repo=repo, strict=False, status_file=None, state=state_path)
            )

        self.assertEqual(0, code)
        self.assertTrue(result["ready"], result["blocked_reasons"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertEqual("pass", checks["state-dispatch-tasks"]["status"])
        self.assertEqual("pass", checks["state-phase-lock"]["status"])


if __name__ == "__main__":
    unittest.main()
