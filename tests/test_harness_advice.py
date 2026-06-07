from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import harness_advice  # noqa: E402
import harness_doctor  # noqa: E402
import install_hooks  # noqa: E402
import phase_guard  # noqa: E402
import run_state  # noqa: E402
from e2e_harness.engine import control_plane  # noqa: E402


def write_control_plane_fixture(
    repo: Path,
    *,
    dispatch_task_id: str,
    task_ids: list[str],
    repair_transactions: dict | None = None,
) -> Path:
    """Build a control-plane.json with the given dispatch and task set, projected to legacy state.

    ``repair_transactions`` is injected into the control plane BEFORE legacy projections are
    written so the projections stay consistent (repair transactions are not part of any
    projection payload) and only the stale-transaction blocker can fire on its own.
    """
    run_dir = repo / "docs" / "agent-runs" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    control_plane.create(repo, run_dir, run_id="docs/agent-runs/run")
    tasks = [
        control_plane.task_contract(task_id, "service-designer-core", "design", service="core")
        for task_id in task_ids
    ]
    data = control_plane.load(repo, run_dir)
    data["tasks"] = tasks
    data["dispatch"] = {"current_task_id": dispatch_task_id, "current_agent": "service-designer-core", "status": "worker_running"}
    if repair_transactions is not None:
        data["repair_transactions"] = repair_transactions
    from common import atomic_write_json

    atomic_write_json(control_plane.control_plane_path(run_dir), data)
    control_plane.write_legacy_projections(repo, run_dir)
    return run_dir / "run-state.json"


def write_pending_dispatch_fixture(repo: Path) -> Path:
    """Build a CREATED run whose T01 dispatch awaits a runtime worker spawn."""
    run_dir = repo / "docs" / "agent-runs" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifact-registry.json").write_text(
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
        "status": "awaiting_runtime_spawn",
        "current_task_id": "T01",
        "current_agent": "requirements-clarifier",
        "context_pack": "docs/agent-runs/run/context-packs/T01.json",
    }
    state["dispatches"] = {"T01": dict(state["dispatch"])}
    run_state.write_state(repo, state_path, state)
    return state_path


class HarnessAdviceGuidanceTests(unittest.TestCase):
    def test_advice_is_silent_without_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = harness_advice.advice_for_repo(repo)
        self.assertFalse(result["active_run"])
        self.assertEqual("", harness_advice.format_advice(result))

    def test_advice_surfaces_pending_dispatch_spawn_and_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_pending_dispatch_fixture(repo)
            result = harness_advice.advice_for_repo(repo)
        self.assertTrue(result["active_run"])
        self.assertEqual("CREATED", result["lifecycle"])
        pending = result["pending_dispatch"]
        self.assertEqual("T01", pending["task_id"])
        self.assertIn("T01-spawn-request.json", pending["spawn_request"])
        self.assertIn("dispatch-ack", pending["ack_command"])
        text = harness_advice.format_advice(result)
        self.assertIn("T01", text)
        self.assertIn("requirements-clarifier", text)
        self.assertIn("dispatch-ack", text)
        self.assertIn("CREATED", text)

    def test_advice_reminds_worker_owns_scheduled_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_pending_dispatch_fixture(repo)
            text = harness_advice.format_advice(harness_advice.advice_for_repo(repo))
        self.assertIn("impact-analysis.json", text)
        self.assertIn("worker", text.lower())

    def test_created_advice_keeps_coordinator_relay_only_for_requirements_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_pending_dispatch_fixture(repo)
            text = harness_advice.format_advice(harness_advice.advice_for_repo(repo))

        self.assertIn("coordinator only dispatches, acknowledges, and relays worker output", text)
        self.assertIn("must not write or repair the requirements handoff locally", text)

    def test_advice_reuses_phase_guard_guidance(self) -> None:
        # Single source of truth: advice must equal phase_guard's own compact guidance.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_pending_dispatch_fixture(repo)
            lock = phase_guard.discover_lock(repo.resolve(), None, None)
            expected = phase_guard.compact_guidance_result(
                phase_guard.guidance_from_lock(repo.resolve(), lock)
            )
            result = harness_advice.advice_for_repo(repo)
        self.assertEqual(expected.get("next_single_action"), result["next_single_action"])

    def test_advice_degrades_silently_on_malformed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "broken"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / ".phase-lock").write_text("{ not json", encoding="utf-8")
            result = harness_advice.advice_for_repo(repo)
        # A broken run must never raise or block a session; advice stays silent.
        self.assertIn("active_run", result)
        self.assertEqual("", harness_advice.format_advice(result))


class HarnessAdviceMainTests(unittest.TestCase):
    def test_main_emits_guidance_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_pending_dispatch_fixture(repo)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = harness_advice.main([str(repo)])
            output = buffer.getvalue()
        self.assertEqual(0, code)
        self.assertIn("T01", output)

    def test_main_silent_and_exits_zero_without_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = harness_advice.main([str(repo)])
            output = buffer.getvalue()
        self.assertEqual(0, code)
        self.assertEqual("", output.strip())

    def test_main_json_mode_is_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_pending_dispatch_fixture(repo)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = harness_advice.main([str(repo), "--json"])
            payload = json.loads(buffer.getvalue())
        self.assertEqual(0, code)
        self.assertTrue(payload["active_run"])
        self.assertEqual("T01", payload["pending_dispatch"]["task_id"])


class AdviceHookWiringTests(unittest.TestCase):
    def test_claude_install_wires_advice_session_hooks_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            install_hooks.install(repo, "claude")
            install_hooks.install(repo, "claude")  # second install must stay idempotent
            settings = repo / ".claude" / "settings.json"
            config = json.loads(settings.read_text(encoding="utf-8"))
        hooks = config["hooks"]
        self.assertIn("SessionStart", hooks)
        self.assertIn("UserPromptSubmit", hooks)
        self.assertEqual(1, len(hooks["SessionStart"]))
        self.assertEqual(1, len(hooks["UserPromptSubmit"]))
        # PreToolUse/Stop counts are unaffected by the advisory hooks.
        self.assertEqual(1, len(hooks["PreToolUse"]))
        self.assertEqual(1, len(hooks["Stop"]))
        session_cmd = hooks["SessionStart"][0]["hooks"][0]["command"]
        self.assertIn("harness_advice.py", session_cmd)
        self.assertIn(str(repo.resolve()), session_cmd)
        # The advisory hook must not carry the blocking phase_guard.
        self.assertNotIn("phase_guard.py", session_cmd)

    def test_claude_install_preserves_user_session_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "SessionStart": [
                                {
                                    "matcher": "",
                                    "hooks": [{"type": "command", "command": "echo user-hook"}],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            install_hooks.install(repo, "claude")
            config = json.loads(settings.read_text(encoding="utf-8"))
        commands = [
            entry["hooks"][0]["command"]
            for entry in config["hooks"]["SessionStart"]
        ]
        self.assertTrue(any("echo user-hook" in command for command in commands))
        self.assertTrue(any("harness_advice.py" in command for command in commands))


class ControlPlaneAuthorityTests(unittest.TestCase):
    def test_navigation_authority_primary_is_control_plane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = write_control_plane_fixture(repo, dispatch_task_id="T01", task_ids=["T01"])
            summary = harness_doctor.state_navigation_summary(repo, state_path)
        authority = summary["authority"]
        self.assertEqual(authority["primary"], control_plane.CONTROL_PLANE_FILE)
        self.assertEqual(authority["primary"], "control-plane.json")
        # run-state.json is now a derived projection, not the source of truth.
        self.assertIn("run-state.json", authority["derived"])

    def test_navigation_map_default_authority_primary_is_control_plane(self) -> None:
        import navigation_map

        default_authority = navigation_map.DEFAULT_AUTHORITY
        self.assertEqual(default_authority["primary"], "control-plane.json")
        self.assertIn("run-state.json", default_authority["derived"])


class ControlPlaneDivergenceTests(unittest.TestCase):
    def test_dispatch_referencing_unknown_task_is_primary_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            # Dispatch points at T06 but the task set has no T06 -> schedule/dispatch split.
            state_path = write_control_plane_fixture(repo, dispatch_task_id="T06", task_ids=["T01"])
            summary = harness_doctor.state_navigation_summary(repo, state_path)
        names = [str(check.get("name", "")) for check in summary["checks"]]
        self.assertIn("state-control-plane-divergence", names)
        divergence = next(
            check for check in summary["checks"] if check.get("name") == "state-control-plane-divergence"
        )
        self.assertEqual(divergence["status"], "fail")
        # The real divergence must be the primary blocker, ahead of any stale-transaction check.
        self.assertEqual(summary["primary_blocker_code"], "state-control-plane-divergence")

    def test_divergence_outranks_co_present_stale_transaction_blocker(self) -> None:
        """Ranking guarantee: when BOTH the divergence and a genuine stale repair transaction
        fail simultaneously, divergence must still be selected as the primary blocker. Seeding
        only the divergence (as above) is trivial -- the stale-tx check is co-present here so a
        future reorder that lets the stale-tx blocker win would fail this test."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            # (b) A genuinely stale repair transaction: active status ("opened") with an
            # opened_at well beyond DEFAULT_LEASE_SECONDS (1800s) -> control_plane_consistency_check
            # emits the "control-plane-repair-transaction-stale" blocker, so state-control-plane FAILs
            # on its own. repair_transactions is not part of any projection, so this is the only
            # blocker it triggers (no projection-drift masking the ranking comparison).
            stale_opened_at = (
                datetime.now(timezone.utc) - timedelta(seconds=harness_doctor.agent_scheduler.DEFAULT_LEASE_SECONDS + 600)
            ).isoformat()
            repair_transactions = {
                "RT01": {
                    "id": "RT01",
                    "status": "opened",
                    "opened_at": stale_opened_at,
                    "repair_code": "control-plane-projection-drift",
                }
            }
            # (a) The divergence: dispatch points at T06 but the task set has no T06.
            state_path = write_control_plane_fixture(
                repo,
                dispatch_task_id="T06",
                task_ids=["T01"],
                repair_transactions=repair_transactions,
            )
            summary = harness_doctor.state_navigation_summary(repo, state_path)
        checks_by_name = {str(check.get("name", "")): check for check in summary["checks"]}
        # Both blockers are live simultaneously, so the ranking comparison is non-trivial.
        self.assertEqual(checks_by_name["state-control-plane-divergence"]["status"], "fail")
        self.assertIn("state-control-plane", checks_by_name)
        self.assertEqual(checks_by_name["state-control-plane"]["status"], "fail")
        self.assertIn("control-plane-repair-transaction-stale", checks_by_name["state-control-plane"]["message"])
        # Divergence WINS over the co-present stale-transaction blocker.
        self.assertEqual(summary["primary_blocker_code"], "state-control-plane-divergence")


if __name__ == "__main__":
    unittest.main()
