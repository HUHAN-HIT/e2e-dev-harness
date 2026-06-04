from __future__ import annotations

import json
import hashlib
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

import agent_scheduler  # noqa: E402
import cross_service_dependency_scan  # noqa: E402
import coordinator_flow  # noqa: E402
import dispatcher  # noqa: E402
import harness_doctor  # noqa: E402
import implementation_gate  # noqa: E402
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


def write_service_design_fixture(repo: Path) -> tuple[Path, Path, Path]:
    run_dir = repo / "docs" / "agent-runs" / "run"
    state_path = run_dir / "run-state.json"
    schedule_path = run_dir / "agent-schedule.json"
    design = repo / "docs" / "design" / "feature.md"
    service_design = run_dir / "service-designs" / "order-service.md"
    design.parent.mkdir(parents=True, exist_ok=True)
    service_design.parent.mkdir(parents=True, exist_ok=True)
    design.write_text(
        "\n".join(
            [
                "# Feature",
                "",
                "## Acceptance Criteria",
                "- AC-1 Quote is returned.",
            ]
        ),
        encoding="utf-8",
    )
    service_design.write_text(
        "\n".join(
            [
                "## Service Scope",
                "- Service/module: services/order-service",
                "- Allowed edit scope:",
                "  - services/order-service/",
                "",
                "## Global Intent Summary",
                "- Restated user intent: Return a quote.",
                "- This service's responsibility: Create quote response.",
                "",
                "## Mapped Acceptance Criteria",
                "| AC | global requirement | service responsibility | local tests |",
                "| --- | --- | --- | --- |",
                "| AC-1 | Quote is returned | Create quote response | OrderServiceTest |",
                "",
                "## Runtime Path",
                "- OrderController#create -> OrderService#create -> OrderRepository#save",
                "",
                "## Service-local TDD Plan",
                "- First red test: OrderServiceTest should fail before implementation",
                "- Expected failure: quote response is missing",
                "- Minimal green implementation: return persisted quote",
                "- Refactor checks: keep service boundary unchanged",
                "- Required Maven command: mvn -pl services/order-service -am test",
                "",
                "## Dependency Boundary",
                "- Independent service change: yes, local persistence only",
                "- HTTP/API dependencies: None",
                "- MQ/DMQ/Kafka dependencies: None",
                "- Shared DB/schema/config/security dependencies: None",
                "- Required contracts or explicit non-applicability: None",
                "",
                "## Test Impact",
                "- Service-local test impact plan: mvn -pl services/order-service -am test",
                "- Broadened verification: mvn test",
            ]
        ),
        encoding="utf-8",
    )
    state = run_state.build_state(
        "docs/agent-runs/run",
        "multi",
        ["services/order-service"],
        "docs/agent-runs/run/artifact-registry.json",
        "SERVICE_DESIGN_REQUIRED",
    )
    run_state.write_state(repo, state_path, state)
    schedule_path.parent.mkdir(parents=True, exist_ok=True)
    schedule_path.write_text(
        json.dumps(
            {
                "schema": "e2e-dev-harness.agent-schedule.v1",
                "completion_mode": "dispatcher-confirmed",
                "tasks": [
                    {
                        "id": "T20",
                        "agent": "service-designer-order-service",
                        "phase": "service-design",
                        "status": "completed",
                        "outputs": [service_design.relative_to(repo).as_posix()],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    event_dir = run_dir / "dispatch-events"
    event_dir.mkdir(parents=True, exist_ok=True)
    (event_dir / "T20-completed.json").write_text(
        json.dumps(
            {
                "event": "worker_completed",
                "task_id": "T20",
                "agent": "service-designer-order-service",
            }
        ),
        encoding="utf-8",
    )
    return design, state_path, service_design


class TargetPackageStructureTests(unittest.TestCase):
    def test_target_package_wrappers_preserve_existing_script_contracts(self) -> None:
        from e2e_harness.domain import execution_packet  # noqa: PLC0415
        from e2e_harness.engine import event_store  # noqa: PLC0415
        from e2e_harness.adapters.runtime import base as runtime_base  # noqa: PLC0415

        packet = execution_packet.for_lifecycle("PLANNED", {}, "python next")
        capabilities = runtime_base.adapter_for("codex").capability_contract()

        self.assertEqual("e2e-dev-harness.execution-packet.v1", packet["schema"])
        self.assertEqual("PLANNED", packet["lifecycle"])
        self.assertEqual("codex", capabilities.runtime)
        self.assertEqual("e2e-dev-harness.event.v1", event_store.SCHEMA)

    def test_engine_facades_preserve_low_risk_cli_contracts(self) -> None:
        from e2e_harness.engine import dispatch_engine, doctor as doctor_engine, recovery  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "code-agent.md"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text("worker evidence\n", encoding="utf-8")

            doctor_result = doctor_engine.evaluate(repo, state=state_path)
            recovery_result = recovery.plan(
                repo,
                state_path,
                schedule,
                "T10",
                "code-developer-order-service",
                [evidence.relative_to(repo).as_posix()],
            )
            capabilities = dispatch_engine.runtime_capabilities("codex")

        self.assertEqual("e2e-dev-harness.doctor.v1", doctor_result["schema"])
        self.assertEqual("e2e-dev-harness.recovery-plan.v1", recovery_result["schema"])
        self.assertEqual("codex", capabilities["runtime"])


class DomainModelContractTests(unittest.TestCase):
    def test_domain_objects_round_trip_with_schema_versions(self) -> None:
        from e2e_harness.domain.models import (  # noqa: PLC0415
            DispatchRecord,
            EvidenceRef,
            ExecutionPacket,
            GateResult,
            LifecycleTransition,
            RunState,
            TaskSchedule,
        )

        state = RunState(
            run_id="docs/agent-runs/run",
            lifecycle="PLANNED",
            selected_mode="single-review",
            services=["services/order-service"],
        )
        transition = LifecycleTransition(
            from_lifecycle="PLANNED",
            to_lifecycle="RED_READY",
            gate="tdd_red",
            evidence="docs/agent-runs/run/evidence/tdd-red.json",
            status="passed",
        )
        schedule = TaskSchedule(tasks=[{"id": "T10", "agent": "code-developer", "status": "planned"}])
        dispatch = DispatchRecord(task_id="T10", agent="code-developer", runtime="codex", status="worker_running")
        evidence = EvidenceRef(
            path="docs/agent-runs/run/evidence/tdd-red.json",
            sha256="a" * 64,
            type="unit-test",
            producer="test-case-developer",
            validation_status="validated",
        )
        gate = GateResult(ready=False, blocked_reasons=["missing evidence"], warnings=["review pending"])
        packet = ExecutionPacket(
            lifecycle="PLANNED",
            objective="Dispatch TDD workers.",
            primary_command="python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-beat .",
        )

        self.assertEqual("e2e-dev-harness.run-state.v1", RunState.from_dict(state.to_dict()).schema)
        self.assertEqual("RED_READY", LifecycleTransition.from_dict(transition.to_dict()).to_lifecycle)
        self.assertEqual("e2e-dev-harness.agent-schedule.v1", TaskSchedule.from_dict(schedule.to_dict()).schema)
        self.assertEqual("worker_running", DispatchRecord.from_dict(dispatch.to_dict()).status)
        self.assertEqual("validated", EvidenceRef.from_dict(evidence.to_dict()).validation_status)
        self.assertEqual(["missing evidence"], GateResult.from_dict(gate.to_dict()).blocked_reasons)
        self.assertEqual(
            "e2e-dev-harness.execution-packet.v1",
            ExecutionPacket.from_dict(packet.to_dict()).schema,
        )


class StateStoreContractTests(unittest.TestCase):
    def test_state_store_writes_lifecycle_event_before_compatibility_snapshot(self) -> None:
        from e2e_harness.engine import state_store  # noqa: PLC0415
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            run_state.write_state(repo, state_path, state)

            result = state_store.transition_lifecycle(
                repo,
                state_path,
                "RED_READY",
                gate="tdd_red",
                gate_status="passed",
            )
            events = event_log.read_events(state_path.parent)
            snapshot = json.loads((state_path.parent / "snapshots" / "run-state.json").read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("lifecycle_transition", events[-1]["event"])
        self.assertEqual("RED_READY", events[-1]["to"])
        self.assertEqual("RED_READY", snapshot["lifecycle"])

    def test_state_store_records_schedule_claim_and_completion_events(self) -> None:
        from e2e_harness.engine import state_store  # noqa: PLC0415
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
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
                        "agent_id: code-developer-order-service",
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
                        "The code-developer task can be marked complete through the state store.",
                        "",
                        "## Open Questions",
                        "None",
                        "",
                        "## Downstream Assumptions",
                        "The coordinator will use the listed evidence path for task completion.",
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
                        "producer_agent": "code-developer-order-service",
                        "status": "ready",
                    }
                ),
                encoding="utf-8",
            )

            claim = state_store.claim_task(repo, schedule, "T10", "code-developer-order-service", state_path)
            complete = state_store.complete_task(
                repo,
                schedule,
                "T10",
                "code-developer-order-service",
                state_path,
                [evidence],
            )
            events = event_log.read_events(state_path.parent)
            projected = json.loads((state_path.parent / "snapshots" / "agent-schedule.json").read_text(encoding="utf-8"))

        self.assertTrue(claim["ready"], claim["blocked_reasons"])
        self.assertTrue(complete["ready"], complete["blocked_reasons"])
        self.assertIn("schedule_task_claimed", [item["event"] for item in events])
        self.assertIn("schedule_task_completed", [item["event"] for item in events])
        self.assertEqual("completed", projected["tasks"][0]["status"])

    def test_agent_task_cli_claim_writes_event_and_projection(self) -> None:
        import e2e_dev_harness  # noqa: PLC0415
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            stdout = io.StringIO()
            argv = [
                "e2e_dev_harness.py",
                "agent-task",
                str(repo),
                "--schedule",
                schedule.relative_to(repo).as_posix(),
                "--state",
                state_path.relative_to(repo).as_posix(),
                "--action",
                "claim",
                "--task-id",
                "T10",
                "--agent",
                "code-developer-order-service",
            ]
            with patch.object(sys, "argv", argv), patch("sys.stdout", stdout):
                exit_code = e2e_dev_harness.main()
            events = event_log.read_events(state_path.parent)
            projected = json.loads((state_path.parent / "snapshots" / "agent-schedule.json").read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertIn("schedule_task_claimed", [item["event"] for item in events])
        self.assertEqual("claimed", projected["tasks"][0]["status"])
        self.assertEqual("code-developer-order-service", projected["tasks"][0]["owner"])

    def test_service_design_transition_writes_event_and_projection(self) -> None:
        import e2e_dev_harness  # noqa: PLC0415
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design, state_path, service_design = write_service_design_fixture(repo)
            code, result = e2e_dev_harness.service_design(
                type(
                    "Args",
                    (),
                    {
                        "repo": repo,
                        "global_design": design.relative_to(repo),
                        "service_design_dir": None,
                        "service_design": [service_design.relative_to(repo)],
                        "emit_template": None,
                        "run_state": state_path.relative_to(repo),
                        "status_file": None,
                    },
                )()
            )
            events = event_log.read_events(state_path.parent)
            projected = json.loads((state_path.parent / "snapshots" / "run-state.json").read_text(encoding="utf-8"))

        self.assertEqual(0, code, result)
        self.assertTrue(result["run_state_transition"]["ready"], result["run_state_transition"]["blocked_reasons"])
        self.assertIn("lifecycle_transition", [item["event"] for item in events])
        self.assertEqual("PLANNED", events[-1]["to"])
        self.assertEqual("service_design", events[-1]["gate"])
        self.assertEqual("PLANNED", projected["lifecycle"])
        self.assertEqual("passed", projected["gates"]["service_design"])


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

    def test_runtime_adapter_exposes_typed_contract_without_breaking_dict_api(self) -> None:
        import runtime_adapters  # noqa: PLC0415

        adapter = runtime_adapters.adapter_for("codex")
        typed = adapter.capability_contract()
        task = {"id": "T10", "agent": "code-developer", "outputs": ["docs/out.md"]}
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state = schedule.parent / "run-state.json"
            schedule.parent.mkdir(parents=True, exist_ok=True)
            spawn = adapter.spawn_contract(task, "prompt", schedule, state, repo)

        self.assertEqual("codex", typed.runtime)
        self.assertEqual("multi_agent_v1.spawn_agent", typed.spawn_tool)
        self.assertEqual("dispatch_requested", spawn.status)
        self.assertEqual("T10", spawn.task_id)
        self.assertEqual(
            [
                "planned",
                "dispatch_requested",
                "worker_spawned",
                "worker_acknowledged",
                "worker_running",
                "worker_completed",
                "evidence_validated",
                "task_closed",
            ],
            runtime_adapters.RUNTIME_STATUS_SEQUENCE,
        )

    def test_runtime_adapter_action_contracts_convert_to_legacy_dicts(self) -> None:
        import runtime_adapters  # noqa: PLC0415

        task = {"id": "T10", "agent": "code-developer"}
        adapter = runtime_adapters.adapter_for("codex")

        ack = adapter.ack_contract(task, "worker-123", "session-123")
        complete = adapter.complete_contract(task, ["docs/out.md"])
        recover = adapter.recover_contract(task, "worker lost")

        self.assertEqual("worker_acknowledged", ack.status)
        self.assertEqual("worker_completed", complete.status)
        self.assertEqual("recovery_requested", recover.status)
        self.assertEqual("worker-123", ack.to_legacy()["worker_handle"])
        self.assertEqual(["docs/out.md"], complete.to_legacy()["evidence"])
        self.assertEqual("worker lost", recover.to_legacy()["reason"])

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

    def test_runtime_adapter_package_exposes_runtime_specific_modules(self) -> None:
        from e2e_harness.adapters.runtime import claude_code, codex_multi_agent, manual  # noqa: PLC0415

        claude = claude_code.adapter()
        codex = codex_multi_agent.adapter()
        manual_adapter = manual.adapter("opencode")

        self.assertEqual("Task", claude.spawn({"id": "T1", "agent": "dev"}, {}, "prompt").request["tool"])
        codex_spawn = codex.spawn({"id": "T2", "agent": "dev"}, {}, "prompt")
        self.assertEqual("multi_agent_v1.spawn_agent", codex_spawn.request["tool"])
        self.assertFalse(codex_spawn.request["arguments"]["fork_context"])
        self.assertIsNone(manual_adapter.spawn({"id": "T3", "agent": "dev"}, {}, "prompt").request)

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

    def test_event_log_projects_compatibility_snapshots_from_events(self) -> None:
        import event_log  # noqa: PLC0415

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

            projection = event_log.write_snapshot_projections(state_path.parent, state_path, schedule)
            projected_state = json.loads((state_path.parent / "snapshots" / "run-state.json").read_text(encoding="utf-8"))
            projected_schedule = json.loads((state_path.parent / "snapshots" / "agent-schedule.json").read_text(encoding="utf-8"))

        self.assertEqual("e2e-dev-harness.snapshot-projection.v1", projection["schema"])
        self.assertEqual("worker_running", projected_state["dispatches"]["T10"]["status"])
        self.assertEqual("agent-schedule.json", projected_schedule["source_snapshot"])

    def test_event_log_state_api_replays_and_reports_first_mismatch(self) -> None:
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            event_log.append_state_event(
                state_path.parent,
                "worker_acknowledged",
                {"task_id": "T10", "agent": "code-developer-order-service"},
                state_path=state_path,
                schedule_path=schedule,
            )
            events = event_log.read_events(state_path.parent)
            replayed_state = event_log.replay_run_state(events, json.loads(state_path.read_text(encoding="utf-8")))
            replayed_schedule = event_log.replay_schedule(events, json.loads(schedule.read_text(encoding="utf-8")))
            state = json.loads(json.dumps(replayed_state))
            state["dispatches"]["T10"]["status"] = "worker_completed"
            mismatch = event_log.first_snapshot_mismatch(events, state, replayed_schedule)

        self.assertEqual("worker_running", replayed_state["dispatches"]["T10"]["status"])
        self.assertEqual("planned", replayed_schedule["tasks"][0]["status"])
        self.assertEqual("T10", mismatch["task_id"])
        self.assertEqual("worker_running", mismatch["event_status"])

    def test_event_log_replays_lifecycle_gates_and_schedule_statuses(self) -> None:
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "docs" / "agent-runs" / "run"
            base_state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            base_schedule = {
                "schema": "e2e-dev-harness.agent-schedule.v1",
                "tasks": [{"id": "T10", "agent": "code-developer", "status": "planned"}],
            }

            event_log.append_event(
                run_dir,
                "lifecycle_transition",
                {"from": "PLANNED", "to": "RED_READY", "gate": "tdd_red", "gate_status": "passed"},
            )
            event_log.append_event(run_dir, "schedule_task_claimed", {"task_id": "T10", "agent": "code-developer"})
            event_log.append_event(run_dir, "gate_blocked", {"gate": "implementation", "blocked_reasons": ["missing manifest"]})
            events = event_log.read_events(run_dir)
            replayed_state = event_log.replay_run_state(events, base_state)
            replayed_schedule = event_log.replay_schedule(events, base_schedule)

        self.assertEqual("RED_READY", replayed_state["lifecycle"])
        self.assertEqual("passed", replayed_state["gates"]["tdd_red"])
        self.assertEqual("blocked", replayed_state["gates"]["implementation"])
        self.assertEqual("claimed", replayed_schedule["tasks"][0]["status"])
        self.assertEqual("code-developer", replayed_schedule["tasks"][0]["owner"])


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

    def test_doctor_surfaces_registry_provider_health(self) -> None:
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
                        "scanners:",
                        "  - missing_provider:scanner",
                    ]
                ),
                encoding="utf-8",
            )
            (providers / "acme_provider.py").write_text(
                "def security_gate():\n    return {'name': 'acme-security', 'kind': 'gate'}\n",
                encoding="utf-8",
            )

            result = harness_doctor.evaluate(repo)

        health = result["extension_provider_health"]
        gate_health = next(item for item in health if item["extension_point"] == "custom_gates")
        scanner_health = next(item for item in health if item["extension_point"] == "scanners")
        self.assertTrue(gate_health["ready"], gate_health)
        self.assertFalse(scanner_health["ready"], scanner_health)
        self.assertIn("missing_provider", scanner_health["warnings"][0])

    def test_implementation_gate_executes_custom_gate_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            providers = repo / ".e2e" / "providers"
            providers.mkdir(parents=True)
            (repo / ".e2e" / "config.yaml").write_text(
                "custom_gates:\n  - acme_gate:security_gate\n",
                encoding="utf-8",
            )
            (providers / "acme_gate.py").write_text(
                "\n".join(
                    [
                        "class SecurityGate:",
                        "    name = 'acme-security'",
                        "    phases = ['planning']",
                        "    def validate(self, request):",
                        "        return {'ready': False, 'blocked_reasons': ['custom security blocked'], 'warnings': []}",
                        "def security_gate():",
                        "    return SecurityGate()",
                    ]
                ),
                encoding="utf-8",
            )

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(repo=repo, phase="planning")
            )

        self.assertIn("Custom gate acme-security: custom security blocked", result["blocked_reasons"])
        self.assertEqual("acme-security", result["custom_gates"]["providers"][0]["name"])

    def test_dependency_scan_executes_scanner_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            providers = repo / ".e2e" / "providers"
            providers.mkdir(parents=True)
            (repo / ".e2e" / "config.yaml").write_text("scanners:\n  - acme_scan:python_scanner\n", encoding="utf-8")
            (providers / "acme_scan.py").write_text(
                "\n".join(
                    [
                        "class PythonScanner:",
                        "    name = 'python-scope'",
                        "    languages = ['python']",
                        "    def discover_scope(self, repo, request):",
                        "        return {'ready': True, 'services': ['services/api'], 'dependencies': [], 'warnings': ['custom scanner ran']}",
                        "def python_scanner():",
                        "    return PythonScanner()",
                    ]
                ),
                encoding="utf-8",
            )

            result = cross_service_dependency_scan.scan(repo, gitnexus_mode="off", write_reports=False)

        self.assertEqual("python-scope", result["scanner_providers"]["providers"][0]["name"])
        self.assertIn("custom scanner ran", result["warnings"])

    def test_execution_packet_applies_policy_packs_as_tightening_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            providers = repo / ".e2e" / "providers"
            providers.mkdir(parents=True)
            (repo / ".e2e" / "config.yaml").write_text("policy_packs:\n  - acme_policy:tight_policy\n", encoding="utf-8")
            (providers / "acme_policy.py").write_text(
                "\n".join(
                    [
                        "class TightPolicy:",
                        "    name = 'tight-policy'",
                        "    def apply(self, request):",
                        "        return {",
                        "            'allowed_writes': ['docs/agent-runs/run'],",
                        "            'forbidden_actions': ['skip policy review'],",
                        "            'required_evidence': ['policy review evidence'],",
                        "        }",
                        "def tight_policy():",
                        "    return TightPolicy()",
                    ]
                ),
                encoding="utf-8",
            )

            packet = coordinator_flow.execution_packet_for_lifecycle(
                "PLANNED",
                {"run_id": "docs/agent-runs/run"},
                "codex",
                {"allowed_writes": ["docs/agent-runs/run", "src"], "command": "python next"},
                repo=repo,
            )

        self.assertEqual(["docs/agent-runs/run"], packet["allowed_writes"])
        self.assertIn("skip policy review", packet["forbidden_actions"])
        self.assertIn("policy review evidence", packet["required_evidence"])
        self.assertEqual(["tight-policy"], packet["policy_packs"]["applied"])

    def test_plugin_provider_contract_normalizes_results_and_provider_metadata(self) -> None:
        import plugin_registry  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            providers = repo / ".e2e" / "providers"
            providers.mkdir(parents=True)
            (repo / ".e2e" / "config.yaml").write_text(
                "\n".join(
                    [
                        "custom_gates:",
                        "  - acme_gate:security_gate",
                        "scanners:",
                        "  - acme_scan:scanner",
                    ]
                ),
                encoding="utf-8",
            )
            (providers / "acme_gate.py").write_text(
                "\n".join(
                    [
                        "class SecurityGate:",
                        "    name = 'acme-security'",
                        "    phases = 'planning'",
                        "    def validate(self, request):",
                        "        return False",
                        "def security_gate():",
                        "    return SecurityGate()",
                    ]
                ),
                encoding="utf-8",
            )
            (providers / "acme_scan.py").write_text(
                "\n".join(
                    [
                        "class Scanner:",
                        "    name = 'python-scope'",
                        "    languages = 'python'",
                        "    def discover_scope(self, repo, request):",
                        "        return True",
                        "def scanner():",
                        "    return Scanner()",
                    ]
                ),
                encoding="utf-8",
            )

            registry = plugin_registry.load_registry(repo)
            gate = plugin_registry.run_custom_gates(
                repo,
                implementation_gate.GateRequest(repo=repo, phase="planning"),
                registry,
            )
            scan = plugin_registry.run_scanners(repo, {}, registry)

        self.assertFalse(gate["ready"])
        self.assertIn("acme-security", gate["providers"][0]["name"])
        self.assertEqual(["planning"], gate["providers"][0]["phases"])
        self.assertEqual(["python"], scan["providers"][0]["languages"])
        self.assertTrue(scan["ready"], scan["blocked_reasons"])

    def test_template_override_dir_resolves_custom_templates(self) -> None:
        import plugin_registry  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            template = repo / ".e2e" / "templates" / "handoffs" / "worker.md"
            template.parent.mkdir(parents=True)
            template.write_text("custom handoff template\n", encoding="utf-8")
            (repo / ".e2e" / "config.yaml").write_text(
                "template_override_dir: .e2e/templates\n",
                encoding="utf-8",
            )

            resolved = plugin_registry.resolve_template(repo, "handoffs/worker.md", default_text="builtin template")

        self.assertEqual("custom handoff template\n", resolved["text"])
        self.assertTrue(resolved["overridden"])
        self.assertEqual(".e2e/templates/handoffs/worker.md", resolved["path"])


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
        self.assertEqual("T10", result["first_inconsistent_event"]["task_id"])
        self.assertEqual("worker_dispatched", result["first_inconsistent_event"]["event_status"])
        self.assertGreaterEqual(result["metrics_summary"]["event_count"], 1)
        self.assertEqual(1, result["metrics_summary"]["mismatch_count"])
        self.assertIn("state-event-log", result["replay_report"]["checks"])

    def test_recovery_plan_writes_auditable_recovery_request_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "code-agent.md"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text("worker evidence\n", encoding="utf-8")

            result = harness_doctor.recovery_plan(
                repo,
                state=state_path,
                schedule=schedule,
                task_id="T10",
                agent="code-developer-order-service",
                evidence=[evidence.relative_to(repo).as_posix()],
            )

        self.assertEqual("e2e-dev-harness.recovery-plan.v1", result["schema"])
        self.assertFalse(result["ready"])
        self.assertIn("dispatch-status", result["recovery_request_command"])
        self.assertIn("--write-recovery-request", result["recovery_request_command"])
        self.assertEqual("T10", result["recovery_request"]["task_id"])
        self.assertIn(evidence.relative_to(repo).as_posix(), result["recovery_request"]["evidence_hashes"])
        self.assertEqual("approval_required", result["recovery_approval_status"]["status"])

    def test_recover_cli_emits_compact_recovery_plan_and_full_result(self) -> None:
        import e2e_dev_harness  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "code-agent.md"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text("worker evidence\n", encoding="utf-8")
            stdout = io.StringIO()
            argv = [
                "e2e_dev_harness.py",
                "recover",
                str(repo),
                "--state",
                state_path.relative_to(repo).as_posix(),
                "--schedule",
                schedule.relative_to(repo).as_posix(),
                "--task-id",
                "T10",
                "--agent",
                "code-developer-order-service",
                "--evidence",
                evidence.relative_to(repo).as_posix(),
            ]
            with patch.object(sys, "argv", argv), patch("sys.stdout", stdout):
                exit_code = e2e_dev_harness.main()
            payload = json.loads(stdout.getvalue())
            full_result = json.loads((repo / payload["full_result_path"]).read_text(encoding="utf-8"))

        self.assertEqual(2, exit_code)
        self.assertEqual("RECOVER", payload["workflow_stage"])
        self.assertIn("full_result_path", payload)
        self.assertEqual("e2e-dev-harness.recovery-plan.v1", full_result["schema"])
        self.assertIn("--write-recovery-request", full_result["recovery_request_command"])

    def test_timeline_cli_emits_compact_run_timeline_and_full_report(self) -> None:
        import e2e_dev_harness  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")
            stdout = io.StringIO()
            argv = [
                "e2e_dev_harness.py",
                "timeline",
                str(repo),
                "--state",
                state_path.relative_to(repo).as_posix(),
            ]
            with patch.object(sys, "argv", argv), patch("sys.stdout", stdout):
                exit_code = e2e_dev_harness.main()
            payload = json.loads(stdout.getvalue())
            full_result = json.loads((repo / payload["full_result_path"]).read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual("TIMELINE", payload["workflow_stage"])
        self.assertIn("full_result_path", payload)
        self.assertIn("command_event_path", payload)
        self.assertEqual(1, payload["event_count"])
        self.assertEqual("worker_dispatched", payload["latest_event"]["event"])
        self.assertEqual("e2e-dev-harness.timeline-report.v1", full_result["schema"])
        self.assertEqual("docs/agent-runs/run", full_result["run_id"])
        self.assertEqual("worker_dispatched", full_result["events"][0]["event"])


class CliCommandFacadeContractTests(unittest.TestCase):
    def test_cli_command_modules_preserve_doctor_recover_and_runtime_capability_contracts(self) -> None:
        from e2e_harness.cli.commands import doctor as doctor_command  # noqa: PLC0415
        from e2e_harness.cli.commands import recover as recover_command  # noqa: PLC0415
        from e2e_harness.cli.commands import runtime_capabilities  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "code-agent.md"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text("worker evidence\n", encoding="utf-8")

            doctor_result = doctor_command.run(repo, strict=False, state=state_path)
            recover_result = recover_command.run(
                repo,
                state=state_path,
                schedule=schedule,
                task_id="T10",
                agent="code-developer-order-service",
                evidence=[evidence.relative_to(repo).as_posix()],
            )
            capabilities = runtime_capabilities.run("codex")

        self.assertEqual("e2e-dev-harness.doctor.v1", doctor_result["schema"])
        self.assertEqual("e2e-dev-harness.recovery-plan.v1", recover_result["schema"])
        self.assertEqual("codex", capabilities["runtime"])
        self.assertTrue(capabilities["ready"])

    def test_runtime_capabilities_cli_emits_legacy_compact_shape(self) -> None:
        import e2e_dev_harness  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            stdout = io.StringIO()
            argv = ["e2e_dev_harness.py", "runtime-capabilities", str(repo), "--runtime", "codex"]
            with patch.object(sys, "argv", argv), patch("sys.stdout", stdout):
                exit_code = e2e_dev_harness.main()
            payload = json.loads(stdout.getvalue())
            event_path = repo / payload["command_event_path"]
            event = json.loads(event_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual("codex", payload["runtime"])
        self.assertTrue(payload["ready"])
        self.assertIn("full_result_path", payload)
        self.assertIn("command_event_path", payload)
        self.assertEqual(".e2e", event["run_id"])
        self.assertEqual("runtime-capabilities", event["command"])
        self.assertEqual("UNKNOWN", event["lifecycle"])


if __name__ == "__main__":
    unittest.main()
