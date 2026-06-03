from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_scheduler  # noqa: E402
import dispatcher  # noqa: E402
import harness_doctor  # noqa: E402
import run_state  # noqa: E402


def write_role_template(repo: Path, path: Path) -> None:
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(
        "\n".join(
            [
                "# Role",
                "",
                "## Role Boundary",
                "Own exactly one scheduled task.",
                "",
                "## Allowed Inputs",
                "Use only the context pack inputs.",
                "",
                "## Forbidden",
                "Do not inherit coordinator chat context.",
                "",
                "## Required Outputs",
                "Write only scheduled outputs.",
                "",
                "## Done When",
                "Return evidence paths for scheduled outputs.",
            ]
        ),
        encoding="utf-8",
    )


def write_dispatch_fixture(repo: Path) -> tuple[Path, Path]:
    run_dir = repo / "docs" / "agent-runs" / "run"
    schedule = run_dir / "agent-schedule.json"
    state_path = run_dir / "run-state.json"
    role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
    input_path = Path("docs/agent-runs/run/handoffs/01-requirements.md")
    output_path = Path("docs/agent-runs/run/service-plans/order-service/code-agent.md")
    write_role_template(repo, role_template)
    handoff = repo / input_path
    handoff.parent.mkdir(parents=True, exist_ok=True)
    evidence = run_dir / "evidence" / "requirements-summary.md"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("Requirements are ready.\n", encoding="utf-8")
    evidence_ref = evidence.relative_to(repo).as_posix()
    evidence_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
    handoff.write_text(
        "\n".join(
            [
                "---",
                "agent: requirements-clarifier",
                "agent_id: requirements-agent",
                "status: ready",
                "inputs:",
                "  - user request",
                "outputs:",
                f"  - {evidence_ref}",
                "input_hashes:",
                "  - user-request sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "output_hashes:",
                f"  - {evidence_ref} sha256:{evidence_hash}",
                "consumed_by:",
                "  - code-developer",
                "open_questions: None",
                "---",
                "",
                "## Summary",
                "Requirements are clarified.",
                "",
                "## Facts Used",
                "The requested order service scope and scheduled worker boundary were reviewed.",
                "",
                "## Decisions Made",
                "The implementation worker may use the generated context pack as its only input.",
                "",
                "## Open Questions",
                "None",
                "",
                "## Downstream Assumptions",
                "The worker writes only the scheduled service plan output.",
                "",
                "## Verification Evidence",
                f"Evidence file {evidence_ref} was written and hashed.",
            ]
        ),
        encoding="utf-8",
    )
    handoff.with_suffix(".ready.json").write_text(
        json.dumps(
            {
                "path": handoff.name,
                "sha256": hashlib.sha256(handoff.read_bytes()).hexdigest(),
                "producer_agent": "requirements-agent",
                "status": "ready",
            }
        ),
        encoding="utf-8",
    )
    state = run_state.build_state(
        "docs/agent-runs/run",
        "multi",
        ["services/order-service"],
        "docs/agent-runs/run/artifact-registry.json",
        "IMPLEMENTED",
    )
    run_state.write_state(repo, state_path, state)
    schedule.parent.mkdir(parents=True, exist_ok=True)
    schedule.write_text(
        json.dumps(
            {
                "schema": "e2e-dev-harness.agent-schedule.v1",
                "completion_mode": "dispatcher-confirmed",
                "require_role_templates": True,
                "tasks": [
                    {
                        "id": "T10",
                        "agent": "code-developer-order-service",
                        "phase": "implement",
                        "role_group": "code",
                        "service": "services/order-service",
                        "inputs": [input_path.as_posix()],
                        "outputs": [output_path.as_posix()],
                        "role_template": role_template.as_posix(),
                        "status": "planned",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return schedule, state_path


class RuntimeAdapterContractTests(unittest.TestCase):
    def test_runtime_adapter_registry_preserves_legacy_capability_shapes(self) -> None:
        import runtime_adapters  # noqa: PLC0415

        claude = runtime_adapters.adapter_for("claude")
        codex = runtime_adapters.adapter_for("codex-app")
        manual = runtime_adapters.adapter_for("gemini")

        self.assertEqual(dispatcher.runtime_capabilities("claude-code"), claude.capabilities())
        self.assertEqual("multi_agent_v1.spawn_agent", codex.capabilities()["spawn_tool"])
        self.assertFalse(manual.capabilities()["supports_subagent"])
        self.assertEqual("gemini", manual.capabilities()["runtime"])

    def test_adapter_spawn_preserves_existing_task_and_codex_request_shapes(self) -> None:
        import runtime_adapters  # noqa: PLC0415

        task = {"id": "T10", "agent": "code-developer", "outputs": ["docs/out.md"]}
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state = schedule.parent / "run-state.json"
            schedule.parent.mkdir(parents=True, exist_ok=True)

            task_request = runtime_adapters.adapter_for("claude-code").spawn(task, "prompt", schedule, state, repo)
            codex_request = runtime_adapters.adapter_for("codex").spawn(task, "prompt", schedule, state, repo)
            manual_request = runtime_adapters.adapter_for("manual").spawn(task, "prompt", schedule, state, repo)

        self.assertEqual("Task", task_request["tool"])
        self.assertEqual("prompt", task_request["arguments"]["prompt"])
        self.assertIn("dispatch-ack", task_request["ack_command"])
        self.assertEqual("multi_agent_v1.spawn_agent", codex_request["tool"])
        self.assertFalse(codex_request["arguments"]["fork_context"])
        self.assertIsNone(manual_request)

    def test_dispatch_ack_uses_runtime_adapter_ack_contract(self) -> None:
        class RecordingAdapter:
            def __init__(self) -> None:
                self.ack_calls: list[tuple[str, str, str]] = []

            def ack(self, task: dict, worker_handle: str, worker_session: str = "") -> dict:
                self.ack_calls.append((task["id"], worker_handle, worker_session))
                return {
                    "task_id": task["id"],
                    "worker_handle": worker_handle,
                    "worker_session": worker_session,
                    "runtime_adapter": "recording",
                }

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            dispatch_result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")
            adapter = RecordingAdapter()

            with patch.object(dispatcher.runtime_adapters, "adapter_for", return_value=adapter):
                result = dispatcher.dispatch_ack(
                    repo,
                    state_path,
                    "T10",
                    "code-developer-order-service",
                    "worker-123",
                    "session-123",
                )

        self.assertTrue(dispatch_result["ready"], dispatch_result["blocked_reasons"])
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual([("T10", "worker-123", "session-123")], adapter.ack_calls)
        self.assertEqual("recording", result["dispatch"]["runtime_adapter"])

    def test_dispatch_complete_uses_runtime_adapter_complete_contract(self) -> None:
        class RecordingAdapter:
            def __init__(self) -> None:
                self.complete_calls: list[tuple[str, list[str]]] = []

            def complete(self, task: dict, evidence: list[str] | None = None) -> dict:
                values = evidence or []
                self.complete_calls.append((task["id"], values))
                return {"task_id": task["id"], "evidence": values, "runtime_adapter": "recording"}

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")
            dispatcher.dispatch_ack(
                repo,
                state_path,
                "T10",
                "code-developer-order-service",
                "worker-123",
                "session-123",
            )
            evidence = "docs/agent-runs/run/service-plans/order-service/code-agent.md"
            evidence_path = repo / evidence
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            implementation_summary = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-summary.md"
            implementation_summary.parent.mkdir(parents=True, exist_ok=True)
            implementation_summary.write_text("implementation evidence\n", encoding="utf-8")
            implementation_ref = implementation_summary.relative_to(repo).as_posix()
            implementation_hash = hashlib.sha256(implementation_summary.read_bytes()).hexdigest()
            input_ref = "docs/agent-runs/run/handoffs/01-requirements.md"
            input_hash = hashlib.sha256((repo / input_ref).read_bytes()).hexdigest()
            evidence_path.write_text(
                "\n".join(
                    [
                        "---",
                        "agent: code-developer",
                        "agent_id: worker-123",
                        "status: ready",
                        "inputs:",
                        f"  - {input_ref}",
                        "outputs:",
                        f"  - {implementation_ref}",
                        "input_hashes:",
                        f"  - {input_ref} sha256:{input_hash}",
                        "output_hashes:",
                        f"  - {implementation_ref} sha256:{implementation_hash}",
                        "consumed_by:",
                        "  - coordinator",
                        "open_questions: None",
                        "---",
                        "",
                        "## Summary",
                        "Implementation evidence is ready.",
                        "",
                        "## Facts Used",
                        "The scheduled task context pack and requirements handoff were reviewed.",
                        "",
                        "## Decisions Made",
                        "The code-developer task can be marked complete with dispatcher confirmation.",
                        "",
                        "## Open Questions",
                        "None",
                        "",
                        "## Downstream Assumptions",
                        "The coordinator will use the listed evidence path for dispatch completion.",
                        "",
                        "## Verification Evidence",
                        f"Evidence file {implementation_ref} was written and hashed.",
                    ]
                ),
                encoding="utf-8",
            )
            evidence_path.with_suffix(".ready.json").write_text(
                json.dumps(
                    {
                        "path": evidence_path.name,
                        "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                        "producer_agent": "worker-123",
                        "status": "ready",
                    }
                ),
                encoding="utf-8",
            )
            adapter = RecordingAdapter()

            with patch.object(dispatcher.runtime_adapters, "adapter_for", return_value=adapter):
                result = dispatcher.dispatch_complete(
                    repo,
                    schedule,
                    state_path,
                    "T10",
                    "code-developer-order-service",
                    [evidence],
                )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual([("T10", [evidence])], adapter.complete_calls)
        self.assertEqual("recording", result["runtime_completion"]["runtime_adapter"])


class EventLogContractTests(unittest.TestCase):
    def test_event_log_appends_ordered_events_and_replays_snapshots(self) -> None:
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "docs" / "agent-runs" / "run"
            first = event_log.append_event(run_dir, "worker_dispatched", {"task_id": "T10"})
            second = event_log.append_event(run_dir, "worker_completed", {"task_id": "T10"})
            events = event_log.read_events(run_dir)
            replay = event_log.replay_dispatch_status(events)

        self.assertEqual("000001-worker-dispatched.json", first.name)
        self.assertEqual("000002-worker-completed.json", second.name)
        self.assertEqual(["worker_dispatched", "worker_completed"], [item["event"] for item in events])
        self.assertEqual("worker_completed", replay["T10"]["status"])

    def test_dispatch_next_double_writes_legacy_dispatch_event_and_enterprise_event(self) -> None:
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)

            result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")
            run_dir = state_path.parent
            events = event_log.read_events(run_dir)
            legacy_event_exists = (run_dir / "dispatch-events" / "T10-dispatched.json").exists()

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(legacy_event_exists)
        self.assertTrue(any(item["event"] == "worker_dispatched" and item["task_id"] == "T10" for item in events))

    def test_dispatch_complete_writes_gate_passed_event_for_red_ready_transition(self) -> None:
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            review = Path("docs/agent-runs/run/reviews/R2-test-review.md")
            role_template = Path("docs/agent-runs/run/agent-roles/semantic-reviewer.md")
            write_role_template(repo, role_template)
            (repo / review).parent.mkdir(parents=True, exist_ok=True)
            (repo / review).write_text("review evidence\n", encoding="utf-8")
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T02",
                "current_agent": "test-reviewer",
                "worker_handle": "review-worker",
                "worker_session": "review-worker-session",
                "spawn_acknowledged_at": "2026-05-31T00:00:00Z",
            }
            state["dispatches"] = {"T02": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {"id": "T01", "agent": "test-case-developer", "phase": "tdd-red", "status": "completed"},
                            {
                                "id": "T02",
                                "agent": "test-reviewer",
                                "phase": "r2-review",
                                "role_group": "review",
                                "inputs": ["docs/agent-runs/run/review-requests/R2-test-review-request.md"],
                                "outputs": [review.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "test-reviewer",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            event_dir = run_dir / "dispatch-events"
            event_dir.mkdir(parents=True, exist_ok=True)
            (event_dir / "T01-completed.json").write_text(
                json.dumps({"event": "worker_completed", "task_id": "T01", "agent": "test-case-developer"}),
                encoding="utf-8",
            )

            with patch.object(dispatcher.reviewer_gate, "validate", return_value={"ready": True, "blocked_reasons": [], "warnings": [], "covered_phases": ["test"]}):
                result = dispatcher.dispatch_complete(repo, schedule, state_path, "T02", "test-reviewer", [review.as_posix()])
            events = event_log.read_events(run_dir)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(any(item["event"] == "gate_passed" and item["gate"] == "tdd_red" for item in events))


class PluginRegistryContractTests(unittest.TestCase):
    def test_empty_plugin_config_is_equivalent_to_builtin_defaults(self) -> None:
        import plugin_registry  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            registry = plugin_registry.load_registry(repo)

        self.assertEqual("e2e-dev-harness.registry.v1", registry["schema"])
        self.assertEqual([], registry["custom_gates"])
        self.assertEqual([], registry["scanners"])
        self.assertEqual([], registry["policy_packs"])
        self.assertEqual("", registry["template_override_dir"])

    def test_plugin_config_registers_named_extension_points(self) -> None:
        import plugin_registry  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            config = repo / ".e2e" / "config.yaml"
            config.parent.mkdir()
            config.write_text(
                "\n".join(
                    [
                        "custom_gates:",
                        "  - acme.security_gate",
                        "scanners:",
                        "  - acme.python_scanner",
                        "policy_packs:",
                        "  - acme.enterprise_policy",
                        "template_override_dir: .e2e/templates",
                    ]
                ),
                encoding="utf-8",
            )

            registry = plugin_registry.load_registry(repo)

        self.assertEqual(["acme.security_gate"], registry["custom_gates"])
        self.assertEqual(["acme.python_scanner"], registry["scanners"])
        self.assertEqual(["acme.enterprise_policy"], registry["policy_packs"])
        self.assertEqual(".e2e/templates", registry["template_override_dir"])

    def test_plugin_registry_loads_local_provider_factories_without_harness_source_edits(self) -> None:
        import plugin_registry  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            config = repo / ".e2e" / "config.yaml"
            providers = repo / ".e2e" / "providers"
            providers.mkdir(parents=True)
            config.write_text(
                "\n".join(
                    [
                        "custom_gates:",
                        "  - acme_provider:security_gate",
                    ]
                ),
                encoding="utf-8",
            )
            (providers / "acme_provider.py").write_text(
                "\n".join(
                    [
                        "def security_gate():",
                        "    return {'name': 'acme-security', 'kind': 'gate'}",
                    ]
                ),
                encoding="utf-8",
            )

            registry = plugin_registry.load_registry(repo)
            loaded = plugin_registry.load_providers(repo, "custom_gates", registry)

        self.assertEqual([], loaded["warnings"])
        self.assertEqual([{"name": "acme-security", "kind": "gate"}], loaded["providers"])


class DoctorTimelineContractTests(unittest.TestCase):
    def test_state_doctor_includes_event_timeline_and_single_recommended_command(self) -> None:
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")

            result = harness_doctor.evaluate(repo, state=state_path)

        timeline = result["run_timeline"]
        self.assertTrue(timeline)
        self.assertEqual("worker_dispatched", timeline[0]["event"])
        self.assertEqual("dispatch-complete", result["failure_taxonomy"][0]["code"])
        self.assertIn("dispatch-complete", result["recommended_command"])

    def test_state_doctor_blocks_event_log_snapshot_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["dispatch"]["status"] = "worker_completed"
            state["dispatches"]["T10"]["status"] = "worker_completed"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            result = harness_doctor.evaluate(repo, state=state_path)

        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(result["ready"])
        self.assertEqual("fail", checks["state-event-log"]["status"])
        self.assertIn("T10", checks["state-event-log"]["message"])
        self.assertIn("event replay", checks["state-event-log"]["message"])


if __name__ == "__main__":
    unittest.main()
