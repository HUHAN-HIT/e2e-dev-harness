"""dispatch-finish: post-spawn one-shot chaining (ack -> handoff finalize -> complete).

These tests pin the *orchestration* contract of the new single-worker fast path:
- the three deterministic post-spawn steps run in order;
- any failing step short-circuits the rest (no silent bypass);
- handoff finalize is optional.

Isolation is unchanged: dispatch_engine.finish still requires a real worker
handle (forwarded to dispatch_ack) and still runs the full dispatch_complete
gate. We stub the underlying steps to keep the test fast and focused on the
chaining logic this module adds.
"""
from __future__ import annotations

import json
import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
FIXTURES = ROOT / "tests" / "fixtures"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import dispatcher  # noqa: E402
import phase_guard  # noqa: E402
import run_state  # noqa: E402
from e2e_harness.cli.commands import dispatch as dispatch_command  # noqa: E402
from e2e_harness.cli.commands import handoff as handoff_command  # noqa: E402
from e2e_harness.engine import control_plane  # noqa: E402
from e2e_harness.engine import dispatch_engine  # noqa: E402


def write_role_template(repo: Path, path: Path) -> None:
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(
        "# Role\n\n## Role Boundary\nOwn one task.\n\n## Allowed Inputs\nInput.\n\n## Forbidden\nNo coordinator context.\n\n## Required Outputs\nOutput.\n\n## Done When\nDone.\n",
        encoding="utf-8",
    )


def write_ready_handoff(repo: Path, path: Path, agent_id: str = "requirements-agent") -> None:
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    evidence = full.parents[1] / "evidence" / "requirements-summary.md"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("Requirements clarification evidence.\n", encoding="utf-8")
    evidence_ref = evidence.relative_to(repo).as_posix()
    evidence_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
    full.write_text(
        (
            "---\n"
            "agent: requirements-clarifier\n"
            f"agent_id: {agent_id}\n"
            "status: ready\n"
            "inputs:\n"
            "  - user request\n"
            "outputs:\n"
            f"  - {evidence_ref}\n"
            "input_hashes:\n"
            "  - user-request sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
            "output_hashes:\n"
            f"  - {evidence_ref} sha256:{evidence_hash}\n"
            "consumed_by:\n"
            "  - implementation-planner\n"
            "open_questions: None\n"
            "---\n\n"
            "## Summary\n"
            "Requirements are clarified for dispatch.\n\n"
            "## Facts Used\n"
            "User request and service scope were reviewed.\n\n"
            "## Decisions Made\n"
            "The downstream task may use the scheduled context pack.\n\n"
            "## Open Questions\n"
            "None\n\n"
            "## Downstream Assumptions\n"
            "The implementation agent will stay inside scheduled outputs.\n\n"
            "## Verification Evidence\n"
            "Ready marker hash matches this handoff file.\n"
        ),
        encoding="utf-8",
    )
    full.with_suffix(".ready.json").write_text(
        json.dumps(
            {
                "path": full.name,
                "sha256": hashlib.sha256(full.read_bytes()).hexdigest(),
                "producer_agent": agent_id,
                "status": "ready",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


class DispatchFinishOrchestrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []
        self._orig_ack = dispatcher.dispatch_ack
        self._orig_complete = dispatcher.dispatch_complete
        self._orig_finalize = handoff_command.run_finalize

    def tearDown(self) -> None:
        dispatcher.dispatch_ack = self._orig_ack
        dispatcher.dispatch_complete = self._orig_complete
        handoff_command.run_finalize = self._orig_finalize

    def _stub(self, name: str, ready: bool):
        def fn(*_args, **_kwargs):
            self.calls.append(name)
            return {
                "ready": ready,
                "blocked_reasons": [] if ready else [f"{name} blocked"],
                "warnings": [],
            }

        return fn

    def _finish(self, handoff):
        return dispatch_engine.finish(
            Path("."),
            Path("schedule.json"),
            Path("run-state.json"),
            "T01",
            "requirements-clarifier",
            "worker-1",
            evidence=["docs/agent-runs/run/handoffs/T01.md"],
            handoff=handoff,
        )

    def test_chains_ack_handoff_complete_in_order(self) -> None:
        dispatcher.dispatch_ack = self._stub("ack", True)
        handoff_command.run_finalize = self._stub("handoff", True)
        dispatcher.dispatch_complete = self._stub("complete", True)

        result = self._finish(Path("docs/agent-runs/run/handoffs/T01.md"))

        self.assertTrue(result["ready"])
        self.assertEqual(self.calls, ["ack", "handoff", "complete"])
        self.assertEqual(result["stage"], "complete")

    def test_ack_failure_short_circuits(self) -> None:
        dispatcher.dispatch_ack = self._stub("ack", False)
        handoff_command.run_finalize = self._stub("handoff", True)
        dispatcher.dispatch_complete = self._stub("complete", True)

        result = self._finish(Path("docs/agent-runs/run/handoffs/T01.md"))

        self.assertFalse(result["ready"])
        self.assertEqual(result["stage"], "ack")
        self.assertEqual(self.calls, ["ack"])
        self.assertIn("ack blocked", result["blocked_reasons"])

    def test_handoff_failure_short_circuits_before_complete(self) -> None:
        dispatcher.dispatch_ack = self._stub("ack", True)
        handoff_command.run_finalize = self._stub("handoff", False)
        dispatcher.dispatch_complete = self._stub("complete", True)

        result = self._finish(Path("docs/agent-runs/run/handoffs/T01.md"))

        self.assertFalse(result["ready"])
        self.assertEqual(result["stage"], "handoff")
        self.assertEqual(self.calls, ["ack", "handoff"])

    def test_handoff_optional_when_not_provided(self) -> None:
        dispatcher.dispatch_ack = self._stub("ack", True)
        handoff_command.run_finalize = self._stub("handoff", True)
        dispatcher.dispatch_complete = self._stub("complete", True)

        result = self._finish(None)

        self.assertTrue(result["ready"])
        self.assertEqual(self.calls, ["ack", "complete"])

    def test_dispatch_command_facade_exposes_finish(self) -> None:
        dispatcher.dispatch_ack = self._stub("ack", True)
        handoff_command.run_finalize = self._stub("handoff", True)
        dispatcher.dispatch_complete = self._stub("complete", True)

        result = dispatch_command.run_finish(
            Path("."),
            Path("schedule.json"),
            Path("run-state.json"),
            "T01",
            "requirements-clarifier",
            "worker-1",
            evidence=["docs/agent-runs/run/handoffs/T01.md"],
            handoff=Path("docs/agent-runs/run/handoffs/T01.md"),
        )

        self.assertTrue(result["ready"])
        self.assertEqual(self.calls, ["ack", "handoff", "complete"])


class DispatchAckPhaseGuardTest(unittest.TestCase):
    def copy_fixture(self, name: str) -> tuple[Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        run_dir = repo / "docs" / "agent-runs" / "run"
        shutil.copytree(FIXTURES / name, run_dir)
        return repo, run_dir

    def _write_dispatcher_prompt_fixture(self, repo: Path, task: dict | None) -> tuple[Path, str]:
        run_dir = repo / "docs" / "agent-runs" / "run"
        state_path = run_dir / "run-state.json"
        context_pack = run_dir / "context-packs" / "T01c.json"
        schedule_path = run_dir / "agent-schedule.json"
        run_dir.mkdir(parents=True, exist_ok=True)
        state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
        state["dispatch"] = {
            "status": "awaiting_runtime_spawn",
            "runtime": "manual",
            "current_task_id": "T01c",
            "current_agent": "requirements-clarifier",
        }
        state["dispatches"] = {"T01c": dict(state["dispatch"])}
        run_state.write_state(repo, state_path, state)
        (run_dir / ".phase-lock").write_text(
            json.dumps(
                {
                    "schema": "e2e-dev-harness.phase-lock.v1",
                    "run_id": "run",
                    "lifecycle": "CREATED",
                    "state": "code-write-locked",
                }
            ),
            encoding="utf-8",
        )
        schedule = {"schema": "e2e-dev-harness.agent-schedule.v1", "tasks": [task] if task else []}
        schedule_path.write_text(json.dumps(schedule), encoding="utf-8")
        context_pack.parent.mkdir(parents=True, exist_ok=True)
        context_pack.write_text(
            json.dumps(
                {
                    "schema": "e2e-dev-harness.context-pack.v1",
                    "task": {"id": "T01c", "agent": "requirements-clarifier"},
                    "schedule": schedule_path.as_posix(),
                }
            ),
            encoding="utf-8",
        )
        prompt = (
            "Task ID: T01c\n"
            f"Context Pack: {context_pack.as_posix()}\n"
            "Repair the Impact Summary and preserve code references without writing implementation code."
        )
        return run_dir, prompt

    def test_created_repair_worker_prompt_with_code_word_uses_contract_not_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir, prompt = self._write_dispatcher_prompt_fixture(
                repo,
                {
                    "id": "T01c",
                    "agent": "requirements-clarifier",
                    "phase": "clarify",
                    "role_group": "design",
                    "dispatch_contract": "fresh-subagent",
                    "runtime_subagent_type": "requirements-clarifier",
                    "status": "claimed",
                    "owner": "requirements-clarifier",
                },
            )

            result = phase_guard.validate_action(repo, "Task", [], run_dir=run_dir, task_text=prompt)

        self.assertTrue(result["ready"], result.get("blocked_reasons"))

    def test_dispatcher_prompt_missing_task_contract_fails_as_schedule_contract_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir, prompt = self._write_dispatcher_prompt_fixture(repo, None)

            result = phase_guard.validate_action(repo, "Task", [], run_dir=run_dir, task_text=prompt)

        self.assertFalse(result["ready"])
        self.assertIn("schedule_contract_invalid", result.get("blocked_reason_codes", []))

    def test_petalpay_t01c_created_repair_spawn_is_allowed_after_contract_import(self) -> None:
        repo, run_dir = self.copy_fixture("petalpay-created-repair-deadlock")
        prompt = (run_dir / "dispatch-spawn-requests" / "T01c-prompt.md").read_text(encoding="utf-8")

        imported = control_plane.import_legacy(repo, run_dir)
        result = phase_guard.validate_action(repo, "Task", [], run_dir=run_dir, task_text=prompt)

        self.assertTrue(imported["ready"], imported.get("diagnostics"))
        self.assertTrue(result["ready"], result.get("blocked_reasons"))

    def test_created_clarifier_spawn_hook_uses_schedule_role_not_prompt_keywords(self) -> None:
        repo, run_dir = self.copy_fixture("petalpay-created-repair-deadlock")
        prompt = (run_dir / "dispatch-spawn-requests" / "T01c-prompt.md").read_text(encoding="utf-8")
        hook_text = json.dumps(
            {
                "tool_name": "Task",
                "tool_input": {
                    "description": "T01c requirements-clarifier",
                    "prompt": prompt,
                    "subagent_type": "requirements-clarifier",
                },
            }
        )

        imported = control_plane.import_legacy(repo, run_dir)
        tool, paths = phase_guard.parse_hook_input(hook_text)
        task_text = phase_guard.extract_task_text(hook_text)
        result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], run_dir=run_dir, task_text=task_text)

        self.assertTrue(imported["ready"], imported.get("diagnostics"))
        self.assertEqual("Task", tool)
        self.assertTrue(result["ready"], result.get("blocked_reasons"))

    def test_created_clarifier_markdown_prompt_uses_schedule_role_not_code_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir, _prompt = self._write_dispatcher_prompt_fixture(
                repo,
                {
                    "id": "T01c",
                    "agent": "requirements-clarifier",
                    "phase": "clarify",
                    "role_group": "design",
                    "dispatch_contract": "fresh-subagent",
                    "runtime_subagent_type": "requirements-clarifier",
                    "status": "claimed",
                    "owner": "requirements-clarifier",
                },
            )
            prompt = (
                "You are a fresh isolated worker. Your role is requirements-clarifier.\n\n"
                "## Task ID\n"
                "T01c\n\n"
                "## Context Pack\n"
                "`docs/agent-runs/run/context-packs/T01c.json`\n\n"
                "## Forbidden\n"
                "- Production/test code edits\n"
                "- Implementation planning\n"
            )
            hook_text = json.dumps(
                {
                    "tool_name": "Agent",
                    "tool_input": {
                        "description": "T01c requirements-clarifier",
                        "prompt": prompt,
                        "subagent_type": "general-purpose",
                    },
                }
            )

            tool, paths = phase_guard.parse_hook_input(hook_text)
            task_text = phase_guard.extract_task_text(hook_text)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], run_dir=run_dir, task_text=task_text)

        self.assertTrue(result["ready"], result.get("blocked_reasons"))

    def test_phase_guard_auto_confirm_does_not_allow_worker_owned_handoff_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "phase-guard-auto-confirm:T01",
                "worker_session": "phase-guard-auto-confirm:T01",
                "spawn_confirmed_by": "phase_guard",
                "spawn_acknowledged_at": "2026-06-04T00:00:00Z",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            (run_dir / "agent-schedule.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [evidence.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Write",
                [evidence],
                run_dir=Path("docs/agent-runs/run"),
                actor_session="requirements-worker-session-1",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Worker output write blocked" in reason for reason in result["blocked_reasons"]))

    def test_created_coordinator_cannot_write_any_active_worker_owned_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            evidence = Path("docs/agent-runs/run/evidence/requirements-summary.md")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "awaiting_runtime_spawn",
                "runtime": "codex",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            (run_dir / "agent-schedule.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [handoff.as_posix(), evidence.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Write",
                [handoff, evidence],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        message = " ".join(result["blocked_reasons"])
        self.assertIn(handoff.as_posix(), message)
        self.assertIn(evidence.as_posix(), message)
        self.assertIn("dispatch-finish", message)
        self.assertIn("fresh worker", message.lower())

    def test_fact_forcing_shell_write_to_worker_output_still_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/evidence/requirements-summary.md")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "awaiting_runtime_spawn",
                "runtime": "codex",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            (run_dir / "agent-schedule.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [evidence.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "powershell",
                [evidence],
                run_dir=Path("docs/agent-runs/run"),
                command_text=f"Set-Content -Path {evidence.as_posix()} -Value 'fact summary'",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Worker output write blocked" in reason for reason in result["blocked_reasons"]))

    def test_dispatch_beat_cli_can_tee_response_while_passing_control_paths_as_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            schedule = Path("docs/agent-runs/run/agent-schedule.json")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)
            (run_dir / ".phase-lock").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.phase-lock.v1",
                        "run_id": "run",
                        "lifecycle": "CREATED",
                        "state": "code-write-locked",
                    }
                ),
                encoding="utf-8",
            )
            (repo / schedule).write_text(json.dumps({"tasks": []}), encoding="utf-8")

            command = (
                "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-beat . "
                "--schedule docs/agent-runs/run/agent-schedule.json "
                "--state docs/agent-runs/run/run-state.json "
                "| tee docs/agent-runs/run/cli-responses/dispatch-beat.json"
            )
            result = phase_guard.validate_action(
                repo,
                "Bash",
                [
                    schedule,
                    Path("docs/agent-runs/run/run-state.json"),
                    Path("docs/agent-runs/run/cli-responses/dispatch-beat.json"),
                ],
                run_dir=Path("docs/agent-runs/run"),
                command_text=command,
            )

        self.assertTrue(result["ready"], result.get("blocked_reasons"))

    def test_quoted_harness_cli_can_tee_response_while_passing_control_paths_as_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            schedule = Path("docs/agent-runs/run/agent-schedule.json")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)
            (run_dir / ".phase-lock").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.phase-lock.v1",
                        "run_id": "run",
                        "lifecycle": "CREATED",
                        "state": "code-write-locked",
                    }
                ),
                encoding="utf-8",
            )
            (repo / schedule).write_text(json.dumps({"tasks": []}), encoding="utf-8")

            command = (
                phase_guard.harness_cli_command(
                    "dispatch-beat",
                    ".",
                    "--schedule",
                    "docs/agent-runs/run/agent-schedule.json",
                    "--state",
                    "docs/agent-runs/run/run-state.json",
                )
                + " | tee docs/agent-runs/run/cli-responses/dispatch-beat.json"
            )
            result = phase_guard.validate_action(
                repo,
                "Bash",
                [
                    schedule,
                    Path("docs/agent-runs/run/run-state.json"),
                    Path("docs/agent-runs/run/cli-responses/dispatch-beat.json"),
                ],
                run_dir=Path("docs/agent-runs/run"),
                command_text=command,
            )

        self.assertTrue(result["ready"], result.get("blocked_reasons"))

    def test_install_hooks_cli_can_repair_project_hook_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)
            (run_dir / ".phase-lock").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.phase-lock.v1",
                        "run_id": "run",
                        "lifecycle": "CREATED",
                        "state": "code-write-locked",
                    }
                ),
                encoding="utf-8",
            )
            settings = Path(".claude/settings.json")
            command = (
                "python skills/e2e-dev-harness/scripts/install_hooks.py . --runtime claude --json "
                "| tee docs/agent-runs/run/cli-responses/install-hooks.json"
            )
            result = phase_guard.validate_action(
                repo,
                "Bash",
                [settings, Path("docs/agent-runs/run/cli-responses/install-hooks.json")],
                run_dir=Path("docs/agent-runs/run"),
                command_text=command,
            )

        self.assertTrue(result["ready"], result.get("blocked_reasons"))

    def test_guidance_uses_invocable_harness_script_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            guidance = phase_guard.guidance_for_lifecycle(repo, None, "CREATED")

        expected = str(SCRIPTS / "e2e_dev_harness.py")
        self.assertIn(sys.executable, guidance["next_valid_command"])
        self.assertIn(expected, guidance["next_valid_command"])
        self.assertNotIn("e2e_dev_harness.py next .", guidance["next_valid_command"])

    def test_shell_discovery_command_with_python_module_probe_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            command = (
                "which e2e_dev_harness.py 2>&1; "
                "which e2e-harness 2>&1; "
                "python -m e2e_dev_harness --help 2>&1 | head -5"
            )

            result = phase_guard.validate_action(repo, "Bash", [], command_text=command)

        self.assertTrue(result["ready"], result.get("blocked_reasons"))

    def test_manual_dispatch_ack_proof_allows_worker_owned_handoff_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "manual",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "requirements-worker-1",
                "worker_session": "requirements-worker-session-1",
                "spawn_confirmed_by": "dispatch_ack",
                "spawn_acknowledged_at": "2026-06-04T00:00:00Z",
                "manual_worker_confirmed": True,
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            (run_dir / "agent-schedule.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [evidence.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Write",
                [evidence],
                run_dir=Path("docs/agent-runs/run"),
                actor_session="requirements-worker-session-1",
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_runtime_dispatch_ack_proof_allows_worker_owned_handoff_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "claude-code",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "requirements-clarifier-worker",
                "worker_session": "requirements-clarifier-session",
                "spawn_confirmed_by": "dispatch_ack",
                "spawn_acknowledged_at": "2026-06-06T01:31:07Z",
                "manual_worker_confirmed": False,
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            (run_dir / "agent-schedule.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [evidence.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Write",
                [evidence],
                run_dir=Path("docs/agent-runs/run"),
                actor_session="requirements-clarifier-session",
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_runtime_dispatch_ack_proof_allows_all_scheduled_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            evidence = Path("docs/agent-runs/run/evidence/requirements-summary.md")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "requirements-clarifier-worker",
                "worker_session": "requirements-clarifier-session",
                "spawn_confirmed_by": "dispatch_ack",
                "spawn_acknowledged_at": "2026-06-06T01:31:07Z",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            (run_dir / "agent-schedule.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [handoff.as_posix(), evidence.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Write",
                [handoff, evidence],
                run_dir=Path("docs/agent-runs/run"),
                actor_session="requirements-clarifier-session",
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_created_dispatch_ack_without_actor_session_cannot_update_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "requirements-clarifier-worker",
                "worker_session": "requirements-clarifier-session",
                "spawn_confirmed_by": "dispatch_ack",
                "spawn_acknowledged_at": "2026-06-06T01:31:07Z",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            (run_dir / "agent-schedule.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [handoff.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Write",
                [handoff],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertIn("Requirements-clarifier artifact write blocked", result["blocked_reasons"][0])

    def test_created_running_clarifier_without_dispatch_ack_cannot_update_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "requirements-clarifier-worker",
                "worker_session": "requirements-clarifier-session",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            evidence = Path("docs/agent-runs/run/evidence/requirements-summary.md")
            (run_dir / "agent-schedule.json").write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "outputs": [evidence.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Update",
                [handoff],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        message = " ".join(result["blocked_reasons"])
        self.assertIn("Requirements-clarifier artifact write blocked", message)
        self.assertIn("dispatch-ack", message)

    def test_created_bash_harness_internal_handoff_repair_debugging_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Bash",
                [],
                run_dir=Path("docs/agent-runs/run"),
                command_text="grep -R \"open_questions\" .claude/skills/e2e-dev-harness/scripts/handoff_gate.py",
            )

        self.assertFalse(result["ready"])
        message = " ".join(result["blocked_reasons"])
        self.assertIn("CREATED coordinator must dispatch", message)
        self.assertIn("requirements-clarifier", message)
        self.assertIn("artifact repair worker", message)

    def test_created_bash_git_bash_wide_handoff_gate_scan_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Bash",
                [],
                run_dir=Path("docs/agent-runs/run"),
                command_text='find C:/Users/me/.claude/skills/e2e-dev-harness/scripts -name "handoff_gate.py" 2>/dev/null | head -3',
            )

        self.assertFalse(result["ready"])
        self.assertEqual("created_harness_internal_debugging", result["coordinator_tool_budget"]["classification"])

    def test_created_bash_small_non_internal_read_only_command_stays_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Bash",
                [],
                run_dir=Path("docs/agent-runs/run"),
                command_text="cat docs/agent-runs/run/run-state.json",
            )

        self.assertTrue(result["ready"], result.get("blocked_reasons"))

    def test_coordinator_high_output_shell_is_blocked_and_recorded_as_tool_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)
            (run_dir / "session-checkpoint.json").write_text(
                json.dumps({"created_at": "2026-06-06T00:00:00Z"}),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Bash",
                [],
                run_dir=run_dir,
                command_text="python -m unittest discover -s tests",
            )
            event_path = Path(result["coordinator_tool_event_path"])
            event = json.loads(event_path.read_text(encoding="utf-8"))

        self.assertFalse(result["ready"])
        self.assertIn("coordinator_tool_budget", result)
        self.assertIn("command-evidence", " ".join(result["blocked_reasons"]))
        self.assertEqual("Bash", event["tool"])
        self.assertEqual("blocked_high_output_shell", event["classification"])
        self.assertEqual("2026-06-06T00:00:00Z", event["checkpoint_created_at"])
        self.assertRegex(event["command_sha256"], r"^[0-9a-f]{64}$")


class DispatchFinishHandoffContractTest(unittest.TestCase):
    def test_ready_handoff_with_worker_proof_completes_t01_and_writes_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            state = run_state.build_state("run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "waiting_dispatch",
                "runtime": "manual",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                                "outputs": [handoff.as_posix()],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatch_engine.finish(
                repo,
                schedule,
                state_path,
                "T01",
                "requirements-clarifier",
                "manual-worker-1",
                evidence=[handoff.as_posix()],
                handoff=None,
            )
            updated_schedule = json.loads(schedule.read_text(encoding="utf-8"))
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))
            event = json.loads((run_dir / "dispatch-events" / "T01-completed.json").read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("completed", updated_schedule["tasks"][0]["status"])
        self.assertEqual("worker_completed", updated_state["dispatch"]["status"])
        self.assertEqual("worker_completed", event["event"])
        self.assertEqual("T01", event["task_id"])

    def test_body_contract_failure_returns_worker_only_repair_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            write_role_template(repo, role_template)
            (repo / handoff).parent.mkdir(parents=True, exist_ok=True)
            (repo / handoff).write_text(
                "---\nagent: requirements-clarifier\nagent_id: worker-1\nstatus: ready\ninputs:\n  - user request\noutputs:\n  - docs/agent-runs/run/evidence/requirements-summary.md\ninput_hashes:\n  - user sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\noutput_hashes:\n  - docs/agent-runs/run/evidence/requirements-summary.md sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\nconsumed_by:\n  - implementation-planner\nopen_questions: None\n---\n\n# Agent Handoff\n",
                encoding="utf-8",
            )
            state = run_state.build_state("run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "waiting_dispatch",
                "runtime": "manual",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                                "outputs": [handoff.as_posix()],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatch_engine.finish(
                repo,
                schedule,
                state_path,
                "T01",
                "requirements-clarifier",
                "manual-worker-1",
                evidence=[handoff.as_posix()],
                handoff=None,
            )

        self.assertFalse(result["ready"])
        self.assertEqual("complete", result["stage"])
        self.assertFalse(result["coordinator_action"]["code_writes_allowed"])
        self.assertEqual("spawn_or_resume_worker", result["coordinator_action"]["required_action"])
        self.assertIn("ready body section", " ".join(result["blocked_reasons"]))

    def test_handoff_finalize_failure_returns_artifact_repair_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            handoff_path = repo / handoff
            text = handoff_path.read_text(encoding="utf-8").replace(
                "## Open Questions\nNone",
                "## Open Questions\nThe earlier concern is resolved; no user input is needed.",
            )
            handoff_path.write_text(text, encoding="utf-8")
            handoff_path.with_suffix(".ready.json").unlink()
            state = run_state.build_state("run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "waiting_dispatch",
                "runtime": "manual",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                                "outputs": [handoff.as_posix()],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatch_engine.finish(
                repo,
                schedule,
                state_path,
                "T01",
                "requirements-clarifier",
                "manual-worker-1",
                evidence=[handoff.as_posix()],
                handoff=handoff,
            )

        self.assertFalse(result["ready"])
        self.assertEqual("handoff", result["stage"])
        self.assertEqual("artifact_repair", result["coordinator_action"]["required_action"])
        self.assertEqual("artifact_repair", result["next_required"]["phase"])
        self.assertIn("open_questions_not_literal_none", result["blocker_codes"])
        self.assertEqual([handoff.as_posix()], result["forbidden_artifact_writes"])

    def test_dispatch_ack_recovers_phase_guard_unverified_state(self) -> None:
        """phase_guard auto-confirm leaves the dispatch in worker_running_unverified.

        That state must remain ack-able: a fresh real worker handle should be able
        to acknowledge it and upgrade unverified -> verified. Otherwise dispatch-ack
        ("not awaiting runtime spawn") and dispatch-complete ("run dispatch-ack")
        deadlock with no forward CLI transition.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "worker_running_unverified",
                "runtime": "manual",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "phase-guard-auto-confirm:T01",
                "worker_session": "phase-guard-auto-confirm:T01",
                "spawn_confirmed_by": "phase_guard",
                "spawn_acknowledged_at": "2026-06-04T00:00:00Z",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)

            result = dispatcher.dispatch_ack(
                repo,
                state_path,
                "T01",
                "requirements-clarifier",
                "requirements-worker-1",
                "requirements-worker-session-1",
            )

        self.assertNotIn(
            "Dispatch is not awaiting runtime spawn acknowledgement.",
            result.get("blocked_reasons", []),
        )
        self.assertTrue(result["ready"], result.get("blocked_reasons"))
        self.assertEqual(result["dispatch"]["status"], "worker_running")
        self.assertEqual(result["dispatch"]["spawn_confirmed_by"], "dispatch_ack")

    def test_manual_worker_packet_routes_post_write_step_through_dispatch_finish(self) -> None:
        repo = Path(".").resolve()
        packet = dispatcher.manual_worker_packet(
            repo,
            Path("docs/agent-runs/run/agent-schedule.json"),
            Path("docs/agent-runs/run/run-state.json"),
            {
                "id": "T01",
                "agent": "requirements-clarifier",
                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
            },
        )

        commands = packet["next_commands"]
        self.assertIn("dispatch-ack", commands[0])
        self.assertNotIn("--schedule", commands[0])
        self.assertIn("Fresh worker writes", commands[1])
        self.assertIn("dispatch-finish", commands[2])
        self.assertIn("--handoff docs/agent-runs/run/handoffs/01-requirements-clarifier.md", commands[2])

    def test_requirements_clarifier_packet_requires_worker_self_check_without_gate_authority(self) -> None:
        repo = Path(".").resolve()
        packet = dispatcher.manual_worker_packet(
            repo,
            Path("docs/agent-runs/run/agent-schedule.json"),
            Path("docs/agent-runs/run/run-state.json"),
            {
                "id": "T01",
                "agent": "requirements-clarifier",
                "phase": "clarify",
                "outputs": [
                    "docs/design/feature.md",
                    "docs/agent-runs/run/handoffs/01-requirements-clarifier.md",
                ],
            },
        )

        requirements = packet["handoff_completion_requirements"]
        self_check = requirements["worker_self_check"]
        self.assertTrue(self_check["required"])
        self.assertTrue(any("clarify" in item for item in self_check["required_commands"]))
        self.assertTrue(any("handoff" in item for item in self_check["required_commands"]))
        self.assertIn("control-plane revalidates", self_check["authority"])

    def test_ready_handoff_guidance_orders_hashes_before_final_dispatch_finish(self) -> None:
        task = {
            "id": "T01",
            "agent": "requirements-clarifier",
            "inputs": ["docs/agent-runs/run/context-packs/T01.json"],
            "outputs": [
                "docs/agent-runs/run/evidence/requirements-summary.md",
                "docs/agent-runs/run/handoffs/01-requirements-clarifier.md",
            ],
        }

        requirements = dispatcher.ready_handoff_completion_requirements(task)
        prompt = "\n".join(dispatcher.ready_handoff_prompt_lines(task))
        steps = "\n".join(requirements["required_steps"])
        self_check_commands = "\n".join(requirements["worker_self_check"]["required_commands"])

        self.assertIn("all declared input/output artifacts", steps)
        self.assertIn("after the final Markdown content is stable", steps)
        self.assertIn("last completion step", steps)
        self.assertIn("dispatch-finish --handoff", steps)
        self.assertIn("all declared input/output artifacts", prompt)
        self.assertIn("stable Markdown", prompt)
        self.assertIn("last", prompt)
        self.assertIn("dispatch-finish --handoff", self_check_commands)
        self.assertNotIn("Run handoff --path ... --agent ... or dispatch-finish", steps)
        self.assertNotIn("Run handoff --path ... --agent ... or dispatch-finish", self_check_commands)

    def test_manual_worker_packet_prefers_dispatch_finish_over_bare_handoff_finalize(self) -> None:
        repo = Path(".").resolve()
        packet = dispatcher.manual_worker_packet(
            repo,
            Path("docs/agent-runs/run/agent-schedule.json"),
            Path("docs/agent-runs/run/run-state.json"),
            {
                "id": "T01",
                "agent": "requirements-clarifier",
                "inputs": ["docs/agent-runs/run/context-packs/T01.json"],
                "outputs": [
                    "docs/agent-runs/run/evidence/requirements-summary.md",
                    "docs/agent-runs/run/handoffs/01-requirements-clarifier.md",
                ],
            },
        )

        text = "\n".join(packet["next_commands"])

        self.assertIn("Final worker step", text)
        self.assertIn("hash all declared input/output artifacts", text)
        self.assertIn("stable Markdown", text)
        self.assertIn("dispatch-finish", packet["next_commands"][-1])
        self.assertIn("--handoff docs/agent-runs/run/handoffs/01-requirements-clarifier.md", packet["next_commands"][-1])
        self.assertNotIn("handoff finalize", text.lower())


if __name__ == "__main__":
    unittest.main()
