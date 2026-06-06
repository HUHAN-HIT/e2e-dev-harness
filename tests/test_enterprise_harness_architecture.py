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


def write_clarify_fixture(repo: Path) -> tuple[Path, Path]:
    run_dir = repo / "docs" / "agent-runs" / "run"
    state_path = run_dir / "run-state.json"
    schedule_path = run_dir / "agent-schedule.json"
    design = repo / "docs" / "design" / "feature.md"
    handoff_ref = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
    role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
    summary = run_dir / "evidence" / "requirements-summary.md"
    handoff = repo / handoff_ref
    design.parent.mkdir(parents=True, exist_ok=True)
    summary.parent.mkdir(parents=True, exist_ok=True)
    handoff.parent.mkdir(parents=True, exist_ok=True)
    write_role_template(repo, role_template)
    design.write_text(
        "\n".join(
            [
                "# Feature",
                "",
                "## Restated Intent",
                "- The user wants a quote returned.",
                "- User confirmation: confirmed-by: user @2026-06-04",
                "",
                "## Goal",
                "- Return checkout quotes.",
                "",
                "## Scope",
                "- services/order-service",
                "",
                "## Use Cases",
                "- Customer requests a checkout quote.",
                "",
                "## Acceptance Criteria",
                "- AC-1 Checkout quote is returned.",
                "",
                "## Test Design",
                "- QuoteServiceTest covers quote creation.",
                "",
                "## Open Questions",
                "None. confirmed-by: user @2026-06-04",
            ]
        ),
        encoding="utf-8",
    )
    summary.write_text("Requirements clarification evidence.\n", encoding="utf-8")
    summary_ref = summary.relative_to(repo).as_posix()
    summary_hash = hashlib.sha256(summary.read_bytes()).hexdigest()
    handoff.write_text(
        "\n".join(
            [
                "---",
                "agent: requirements-clarifier",
                "agent_id: requirements-clarifier",
                "status: ready",
                "inputs:",
                "  - user request",
                "outputs:",
                f"  - {summary_ref}",
                "input_hashes:",
                "  - user-request sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "output_hashes:",
                f"  - {summary_ref} sha256:{summary_hash}",
                "consumed_by:",
                "  - coordinator",
                "open_questions: None",
                "---",
                "",
                "## Summary",
                "Requirements are clarified.",
                "",
                "## Facts Used",
                "The user request and design scope were reviewed.",
                "",
                "## Decisions Made",
                "The clarified design may advance to planning.",
                "",
                "## Open Questions",
                "None",
                "",
                "## Downstream Assumptions",
                "The coordinator will run the planning gate next.",
                "",
                "## Verification Evidence",
                f"Evidence file {summary_ref} was written and hashed.",
            ]
        ),
        encoding="utf-8",
    )
    handoff.with_suffix(".ready.json").write_text(
        json.dumps(
            {
                "path": handoff.name,
                "sha256": hashlib.sha256(handoff.read_bytes()).hexdigest(),
                "producer_agent": "requirements-clarifier",
                "status": "ready",
            }
        ),
        encoding="utf-8",
    )
    state = run_state.build_state(
        "docs/agent-runs/run",
        "single",
        [],
        "docs/agent-runs/run/artifact-registry.json",
        "CREATED",
    )
    state["dispatch"] = {
        "status": "worker_running",
        "runtime": "codex",
        "current_task_id": "T01",
        "current_agent": "requirements-clarifier",
        "worker_handle": "worker-T01",
        "worker_session": "worker-session-T01",
    }
    state["dispatches"] = {"T01": state["dispatch"]}
    run_state.write_state(repo, state_path, state)
    schedule_path.parent.mkdir(parents=True, exist_ok=True)
    schedule_path.write_text(
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
                        "inputs": [],
                        "outputs": [handoff_ref.as_posix()],
                        "role_template": role_template.as_posix(),
                        "status": "claimed",
                        "owner": "requirements-clarifier",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    complete = dispatcher.dispatch_complete(
        repo,
        schedule_path,
        state_path,
        "T01",
        "requirements-clarifier",
        [handoff_ref.as_posix()],
    )
    if not complete["ready"]:
        raise AssertionError(complete["blocked_reasons"])
    return design, state_path


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

    def test_clarify_transition_writes_event_and_projection(self) -> None:
        import e2e_dev_harness  # noqa: PLC0415
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design, state_path = write_clarify_fixture(repo)
            code, result = e2e_dev_harness.clarify(
                type(
                    "Args",
                    (),
                    {
                        "repo": repo,
                        "design_doc": design.relative_to(repo),
                        "run_state": state_path.relative_to(repo),
                        "require_intent": True,
                        "require_user_confirmation": True,
                        "status_file": None,
                    },
                )()
            )
            events = event_log.read_events(state_path.parent)
            projected = json.loads((state_path.parent / "snapshots" / "run-state.json").read_text(encoding="utf-8"))

        self.assertEqual(0, code, result)
        self.assertTrue(result["run_state_transition"]["ready"], result["run_state_transition"]["blocked_reasons"])
        self.assertIn("lifecycle_transition", [item["event"] for item in events])
        self.assertEqual("CLARIFIED", events[-1]["to"])
        self.assertEqual("clarification", events[-1]["gate"])
        self.assertEqual("CLARIFIED", projected["lifecycle"])
        self.assertEqual("passed", projected["gates"]["clarification"])

    def test_gate_transition_writes_event_and_projection(self) -> None:
        import e2e_dev_harness  # noqa: PLC0415
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            red = state_path.parent / "evidence" / "red-test.txt"
            red.parent.mkdir(parents=True, exist_ok=True)
            red.write_text("expected failure\n", encoding="utf-8")
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            run_state.write_state(repo, state_path, state)
            args = type(
                "Args",
                (),
                {
                    "repo": repo,
                    "design_doc": None,
                    "kg_status_file": None,
                    "phase": "implementation",
                    "red_test_evidence": red,
                    "coverage_matrix": None,
                    "unit_test_evidence": None,
                    "business_review": None,
                    "memory_updates": None,
                    "skip_spring_static_check": False,
                    "rework_dir": None,
                    "dependency_report": None,
                    "implementation_manifest": None,
                    "review_dir": None,
                    "contract_dir": None,
                    "require_contracts": False,
                    "require_handoffs": False,
                    "require_semantic_reviews": False,
                    "review_profile": None,
                    "handoff_dir": None,
                    "requirements_archive": None,
                    "require_requirements_archive": False,
                    "strict_workflow": False,
                    "changed_files": None,
                    "test_impact_plan": None,
                    "base_ref": None,
                    "checkpoint_mode": "off",
                    "confirmation_dir": None,
                    "require_intent": False,
                    "tdd_mode": "auto",
                    "workflow_tier": "auto",
                    "run_state": state_path.relative_to(repo),
                    "state": None,
                    "no_harness_state": False,
                    "harness_state_approval": None,
                    "require_gitnexus_evidence": "auto",
                    "gitnexus_degradation": None,
                    "status_file": None,
                },
            )()
            gate_payload = {
                "phase": "implementation",
                "ready": True,
                "blocked_reasons": [],
                "warnings": [],
                "knowledge_graph_status_loaded": True,
                "tdd": {"ready": True, "red_evidence": red.relative_to(repo).as_posix()},
                "semantic_reviews": {"ready": True, "covered_phases": ["design", "test"]},
            }
            with patch.object(e2e_dev_harness.implementation_gate, "validate_gate_request", return_value=gate_payload):
                code, result = e2e_dev_harness.gate(args)
            events = event_log.read_events(state_path.parent)
            projected = json.loads((state_path.parent / "snapshots" / "run-state.json").read_text(encoding="utf-8"))

        self.assertEqual(0, code, result)
        self.assertTrue(result["run_state_transition"]["ready"], result["run_state_transition"]["blocked_reasons"])
        self.assertIn("lifecycle_transition", [item["event"] for item in events])
        self.assertEqual("IMPLEMENTED", events[-1]["to"])
        self.assertEqual("implementation", events[-1]["gate"])
        self.assertEqual("IMPLEMENTED", projected["lifecycle"])
        self.assertEqual("passed", projected["gates"]["implementation"])


class RuntimeAdapterContractTests(unittest.TestCase):
    def test_layered_package_exposes_policy_scanner_ci_and_engine_facades(self) -> None:
        from e2e_harness.adapters.ci import github_actions  # noqa: PLC0415
        from e2e_harness.adapters.scanners import generic, java_spring  # noqa: PLC0415
        from e2e_harness.engine import gate_runner, orchestrator  # noqa: PLC0415
        from e2e_harness.policies import (  # noqa: PLC0415
            context_budget_policy,
            lifecycle_policy,
            review_policy,
            write_policy,
        )
        from e2e_harness.templates import resolver  # noqa: PLC0415

        self.assertTrue(callable(gate_runner.run))
        self.assertTrue(callable(orchestrator.next_step))
        self.assertTrue(callable(generic.discover_scope))
        self.assertTrue(callable(java_spring.discover_scope))
        self.assertTrue(callable(github_actions.summarize_checks))
        self.assertTrue(callable(lifecycle_policy.guidance_for_lifecycle))
        self.assertTrue(callable(write_policy.validate_action))
        self.assertTrue(callable(review_policy.default_profile))
        self.assertTrue(callable(context_budget_policy.context_budget))
        self.assertTrue(callable(resolver.resolve_template))

    def test_runtime_adapter_registry_preserves_legacy_capability_shapes(self) -> None:
        import runtime_adapters  # noqa: PLC0415

        claude = runtime_adapters.adapter_for("claude")
        codex = runtime_adapters.adapter_for("codex-app")
        manual = runtime_adapters.adapter_for("gemini")

        self.assertEqual(dispatcher.runtime_capabilities("claude-code"), claude.capabilities())
        self.assertEqual("multi_agent_v1.spawn_agent", codex.capabilities()["spawn_tool"])
        self.assertFalse(manual.capabilities()["supports_subagent"])
        self.assertEqual("gemini", manual.capabilities()["runtime"])

    def test_unknown_runtime_adapter_fallback_is_visible_in_capabilities(self) -> None:
        import runtime_adapters  # noqa: PLC0415

        capabilities = runtime_adapters.adapter_for("gemini").capabilities()

        self.assertEqual("gemini", capabilities["runtime"])
        self.assertEqual("manual", capabilities["fallback_runtime"])
        self.assertTrue(capabilities["unknown_runtime"])
        self.assertIn("Unknown runtime", capabilities["warning"])

    def test_runtime_capabilities_facade_surfaces_unknown_runtime_warning(self) -> None:
        from e2e_harness.engine import dispatch_engine  # noqa: PLC0415

        result = dispatch_engine.runtime_capabilities("gemini")

        self.assertTrue(result["ready"])
        self.assertEqual("gemini", result["runtime"])
        self.assertEqual("manual", result["fallback_runtime"])
        self.assertTrue(result["unknown_runtime"])
        self.assertTrue(any("Unknown runtime" in warning for warning in result["warnings"]))

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
                "worker_running_unverified",
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

    def test_event_log_reads_jsonl_and_legacy_json_events_in_sequence_order(self) -> None:
        import event_log  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "docs" / "agent-runs" / "run"
            events_dir = run_dir / "events"
            events_dir.mkdir(parents=True)
            (events_dir / "events.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"schema": event_log.SCHEMA, "sequence": 1, "event": "worker_dispatched", "task_id": "T10"}),
                        "{bad json",
                        json.dumps({"schema": event_log.SCHEMA, "sequence": 3, "event": "gate_passed", "gate": "tdd_red"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (events_dir / "000002-worker-completed.json").write_text(
                json.dumps({"schema": event_log.SCHEMA, "sequence": 2, "event": "worker_completed", "task_id": "T10"}),
                encoding="utf-8",
            )

            events = event_log.read_events(run_dir)

        self.assertEqual(["worker_dispatched", "worker_completed", "gate_passed"], [item["event"] for item in events])
        self.assertEqual("events.jsonl:1", events[0]["path"])
        self.assertEqual("000002-worker-completed.json", events[1]["path"])

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

    def test_event_log_projects_snapshots_from_control_plane_when_present(self) -> None:
        import event_log  # noqa: PLC0415
        from e2e_harness.engine import control_plane  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            control_plane.create(repo, run_dir, "docs/agent-runs/run")
            path = run_dir / "control-plane.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["tasks"] = [{"id": "T01", "agent": "requirements-clarifier", "phase": "clarify", "status": "planned"}]
            path.write_text(json.dumps(data), encoding="utf-8")

            projection = event_log.write_snapshot_projections(run_dir)
            root_state = json.loads((run_dir / "run-state.json").read_text(encoding="utf-8"))
            snapshot_state = json.loads((run_dir / "snapshots" / "run-state.json").read_text(encoding="utf-8"))

        self.assertEqual("e2e-dev-harness.snapshot-projection.v1", projection["schema"])
        self.assertEqual("control-plane.json", root_state["source"])
        self.assertEqual("control-plane.json", snapshot_state["source"])

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
    def test_navigation_map_projection_reports_you_are_here_and_single_action(self) -> None:
        import navigation_map  # noqa: PLC0415

        state = {
            "run_id": "run",
            "lifecycle": "CREATED",
            "dispatches": {
                "T01": {
                    "status": "awaiting_runtime_spawn",
                    "runtime": "codex",
                    "current_agent": "requirements-clarifier",
                    "context_pack": "docs/agent-runs/run/context-packs/T01.json",
                    "invocation_path": "docs/agent-runs/run/dispatch-invocations/T01.json",
                }
            },
        }
        action = {
            "workflow_stage": "CLARIFY",
            "phase": "clarify",
            "dispatch_command": "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-beat . --max-workers 1",
            "allowed_writes": ["docs/agent-runs/run/design.md"],
            "blocked_writes": ["src/**"],
            "forbidden_local_actions": ["do not edit production code"],
        }
        execution_packet = {
            "schema": "e2e-dev-harness.execution-packet.v1",
            "lifecycle": "CREATED",
            "phase": "clarify",
            "objective": "Clarify intent and scope through the bootstrap requirements worker before planning.",
            "primary_command": action["dispatch_command"],
            "required_actions": ["Dispatch the requirements-clarifier worker."],
            "required_evidence": ["confirmed Restated Intent and closed Open Questions in the design doc"],
            "forbidden_actions": ["do not edit production code"],
            "completion_checks": ["run-state lifecycle becomes CLARIFIED"],
            "next_gate": "clarification",
        }

        result = navigation_map.build(
            repo=Path("C:/repo"),
            state_path=Path("C:/repo/docs/agent-runs/run/run-state.json"),
            state=state,
            lifecycle="CREATED",
            workflow_stage="CLARIFY",
            ready=False,
            blocked_reasons=["Runtime hook is not ready"],
            warnings=["Session checkpoint is stale"],
            action=action,
            preflight={"ready": False, "blockers": ["dispatch ack missing"], "next_single_action": "run dispatch-ack"},
            execution_packet=execution_packet,
            checkpoint={"checkpoint": "docs/agent-runs/run/session-checkpoint.json"},
            coordinator_summary_path="docs/agent-runs/run/coordinator-summary.json",
        )

        self.assertEqual("e2e-dev-harness.navigation-map.v1", result["schema"])
        self.assertEqual({"lifecycle": "CREATED", "workflow_stage": "CLARIFY", "phase": "clarify"}, result["you_are_here"])
        self.assertFalse(result["status"]["ready"])
        self.assertEqual(["Runtime hook is not ready", "dispatch ack missing"], result["status"]["blocked_by"])
        self.assertEqual("run dispatch-ack", result["next_single_action"]["command"])
        self.assertEqual("preflight", result["next_single_action"]["source"])
        self.assertEqual("T01", result["active_work"][0]["task_id"])
        self.assertEqual(["docs/agent-runs/run/design.md"], result["allowed_now"])
        self.assertIn("do not edit production code", result["forbidden_now"])
        self.assertEqual(["confirmed Restated Intent and closed Open Questions in the design doc"], result["required_evidence"])
        self.assertEqual("docs/agent-runs/run/run-state.json", result["artifacts"]["run_state"])

    def test_navigation_map_does_not_show_completed_worker_as_active_work(self) -> None:
        import navigation_map  # noqa: PLC0415

        result = navigation_map.build(
            repo=Path("C:/repo"),
            state_path=Path("C:/repo/docs/agent-runs/run/run-state.json"),
            state={
                "run_id": "run",
                "lifecycle": "CREATED",
                "dispatches": {
                    "T01": {
                        "status": "worker_completed",
                        "runtime": "claude-code",
                        "current_agent": "requirements-clarifier",
                        "context_pack": "docs/agent-runs/run/context-packs/T01.json",
                    }
                },
            },
            lifecycle="CREATED",
            workflow_stage="CLARIFY",
            ready=True,
            blocked_reasons=[],
            warnings=[],
            action={"workflow_stage": "CLARIFY", "phase": "clarify", "command": "dispatch-beat"},
            preflight={},
            execution_packet={"phase": "clarify", "objective": "Clarify before planning."},
            checkpoint={},
        )

        self.assertEqual([], result["active_work"])

    def test_cli_command_modules_preserve_start_contracts(self) -> None:
        from e2e_harness.cli.commands import start as start_command  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            code, result = start_command.run(
                repo,
                feature="Refund MQ",
                request="Publish refund notification after success.",
                run_id="run",
            )
            design = Path(result["design_doc"])
            state_path = Path(result["run_state"])
            lock_path = Path(result["phase_lock"])
            schedule_path = Path(result["agent_schedule"])
            workflow_path = Path(result["workflow_plan"])
            registry_path = Path(result["artifact_registry"])
            design_text = design.read_text(encoding="utf-8")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            registry = json.loads(registry_path.read_text(encoding="utf-8"))

        self.assertEqual(0, code, result)
        self.assertTrue(result["ready"])
        self.assertEqual("Refund MQ", result["feature"])
        self.assertEqual("run", result["run_id"])
        self.assertIn("## Restated Intent", design_text)
        self.assertEqual("CREATED", state["lifecycle"])
        self.assertEqual("bootstrap", state["selected_mode"])
        self.assertEqual("code-write-locked", lock["state"])
        self.assertEqual("bootstrap", schedule["selected_mode"])
        self.assertEqual("dispatcher-confirmed", schedule["completion_mode"])
        self.assertEqual("requirements-clarifier", schedule["tasks"][0]["agent"])
        self.assertEqual("clarify", schedule["tasks"][0]["phase"])
        self.assertEqual("e2e-dev-harness.workflow-plan.v1", workflow["schema"])
        self.assertEqual("standard", workflow["selected_profile"])
        self.assertTrue(any(item["type"] == "workflow_plan" for item in registry["artifacts"]))
        self.assertEqual("clarify", result["next"]["phase"])
        self.assertEqual([], result["blocked_reasons"])

    def test_cli_command_modules_preserve_plan_contracts(self) -> None:
        from e2e_harness.cli.commands import plan as plan_command  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "services" / "order-service" / "src" / "main").mkdir(parents=True)
            (repo / "services" / "order-service" / "pom.xml").write_text("<project />\n", encoding="utf-8")
            (repo / "pom.xml").write_text(
                "<project><modules><module>services/order-service</module></modules></project>\n",
                encoding="utf-8",
            )
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                "\n".join(
                    [
                        "# Feature",
                        "",
                        "## Goal",
                        "- Return a quote.",
                        "",
                        "## Scope",
                        "- services/order-service",
                        "",
                        "## Use Cases",
                        "- Create quote.",
                        "",
                        "## Acceptance Criteria",
                        "- AC-1 Quote is returned.",
                        "",
                        "## Test Design",
                        "- Unit test first.",
                        "",
                        "## Open Questions",
                        "None",
                    ]
                ),
                encoding="utf-8",
            )
            code, result = plan_command.run(
                repo,
                mode="single-review",
                design_doc=design.relative_to(repo),
                agent_run_dir="docs/agent-runs/run",
                run_date="2026-05-31",
                service_scope="affected",
                paths_requested=["services/order-service"],
                create_archive=True,
            )
            artifacts = result["handoff_artifacts"]
            state = json.loads((repo / artifacts["run_state"]).read_text(encoding="utf-8"))
            schedule = json.loads((repo / artifacts["agent_schedule"]).read_text(encoding="utf-8"))
            registry = json.loads((repo / artifacts["artifact_registry"]).read_text(encoding="utf-8"))
            requirements_exists = (repo / artifacts["requirements"]).exists()
            exec_plan_exists = (repo / artifacts["exec_plan"]).exists()
            kg_status_exists = (repo / artifacts["knowledge_graph_status"]).exists()
            exec_plan_text = (repo / artifacts["exec_plan"]).read_text(encoding="utf-8")

        self.assertEqual(0, code, result)
        self.assertEqual("single-review", result["selected_mode"])
        self.assertEqual(["services/order-service"], result["selected_services"])
        self.assertEqual("PLANNED", state["lifecycle"])
        self.assertEqual("e2e-dev-harness.agent-schedule.v1", schedule["schema"])
        self.assertEqual("e2e-dev-harness.artifact-registry.v1", registry["schema"])
        self.assertTrue(requirements_exists)
        self.assertTrue(exec_plan_exists)
        self.assertTrue(kg_status_exists)
        self.assertIn("Agent Protocol", exec_plan_text)

    def test_cli_command_modules_preserve_prepare_contracts(self) -> None:
        from e2e_harness.cli.commands import prepare as prepare_command  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            status_file = repo / "prepare-status.json"
            code, result = prepare_command.run(
                repo,
                agent_mode="off",
                superpowers_mode="off",
                memory_mode="off",
                agent_orchestration_mode="off",
                dependency_scan_mode="off",
                status_file=status_file,
            )
            status = json.loads(status_file.read_text(encoding="utf-8"))

        self.assertEqual(0, code, result)
        self.assertEqual(str(repo.resolve()), result["repo"])
        self.assertFalse(result["agent_instructions"]["enabled"])
        self.assertFalse(result["orchestration"]["enabled"])
        self.assertFalse(result["cross_service_dependencies"]["enabled"])
        self.assertEqual([], result["blocked_components"])
        self.assertEqual(result, status)

    def test_cli_command_modules_preserve_verify_contracts(self) -> None:
        import e2e_dev_harness  # noqa: PLC0415
        from e2e_harness.cli.commands import verify as verify_command  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            status_file = repo / "verify-status.json"
            with patch.object(e2e_dev_harness, "prepare", return_value=(0, {"blocked": False})):
                code, result = verify_command.run(
                    repo,
                    phase="planning",
                    skip_maven=True,
                    status_file=status_file,
                )
            status = json.loads(status_file.read_text(encoding="utf-8"))

        self.assertEqual(0, code, result)
        self.assertEqual("planning", result["workflow"]["phase"])
        self.assertTrue(result["maven"]["skipped"])
        self.assertEqual(result, status)

    def test_cli_command_modules_preserve_install_contracts(self) -> None:
        from e2e_harness.cli.commands import install as install_command  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            status_file = repo / "install-status.json"
            code, result = install_command.run(
                repo,
                target="all",
                install_root=repo / "home",
                source_skill_dir=ROOT / "skills" / "e2e-dev-harness",
                runtime="claude",
                full=True,
                yes=False,
                install_external=False,
                skip_external=True,
                with_hooks=False,
                doctor=False,
                status_file=status_file,
            )
            status = json.loads(status_file.read_text(encoding="utf-8"))

        self.assertEqual(0, code, result)
        self.assertEqual("e2e-dev-harness.install.v1", result["schema"])
        self.assertEqual(str(repo.resolve()), result["project_root"])
        self.assertFalse(result["executed"])
        self.assertEqual(["codex", "claude", "agents"], result["targets"])
        self.assertIn("copy-skill", [action["id"] for action in result["actions"]])
        self.assertEqual(result, status)

    def test_cli_command_modules_preserve_next_contracts(self) -> None:
        import e2e_dev_harness  # noqa: PLC0415
        from e2e_harness.cli.commands import next as next_command  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            payload = {
                "ready": True,
                "workflow_stage": "CLARIFY",
                "next": {"phase": "clarify"},
                "blocked_reasons": [],
            }
            with patch.object(e2e_dev_harness.coordinator_flow, "next_step", return_value=(0, payload)):
                code, result = next_command.run(repo, state=Path("docs/agent-runs/run/run-state.json"))

        self.assertEqual(0, code)
        self.assertEqual(payload, result)

    def test_coordinator_summary_persists_navigation_map_additively(self) -> None:
        import coordinator_summary  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            run_dir.mkdir(parents=True)
            state_path = run_dir / "run-state.json"
            state = {
                "run_id": "run",
                "lifecycle": "CREATED",
                "dispatches": {
                    "T01": {
                        "status": "worker_completed",
                        "runtime": "claude-code",
                        "current_agent": "requirements-clarifier",
                    }
                },
            }
            result = {
                "ready": True,
                "lifecycle": "CREATED",
                "next": {
                    "phase": "clarify",
                    "command": "Dispatch the bootstrap requirements-clarifier worker.",
                    "next_single_action": "Run dispatch-beat --max-workers 1 for mechanical clarification repair task T01b.",
                },
                "navigation_map": {
                    "schema": "e2e-dev-harness.navigation-map.v1",
                    "you_are_here": {
                        "lifecycle": "CREATED",
                        "workflow_stage": "CLARIFY",
                        "phase": "clarify",
                    },
                    "status": {"ready": True, "health": "ready", "blocked_by": []},
                    "next_single_action": {
                        "command": "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-beat . --max-workers 1",
                        "source": "next_action",
                    },
                    "active_work": [],
                    "allowed_now": ["docs/agent-runs/run/design.md"],
                    "forbidden_now": ["src/**"],
                    "required_evidence": ["requirements handoff"],
                    "completion_checks": ["run-state lifecycle becomes CLARIFIED"],
                    "artifacts": {"run_state": "docs/agent-runs/run/run-state.json"},
                },
            }

            summary = coordinator_summary.write(repo, state_path, state, result=result)
            payload = json.loads(Path(summary["coordinator_summary"]).read_text(encoding="utf-8"))

        self.assertTrue(summary["ready"])
        self.assertEqual("CREATED", payload["lifecycle"])
        self.assertEqual("CLARIFY", payload["workflow_stage"])
        self.assertIn("navigation_map", payload)
        self.assertEqual("CREATED", payload["navigation_map"]["you_are_here"]["lifecycle"])
        self.assertIn("dispatch-beat", payload["navigation_map"]["next_single_action"]["command"])
        self.assertIn("next_action", payload)
        self.assertIn("T01b", payload["next_action"]["command"])
        self.assertEqual({}, payload["active_dispatches"])
        self.assertIn("execution_packet", payload)

    def test_map_cli_facade_returns_navigation_map_only(self) -> None:
        from e2e_harness.cli.commands import map as map_command  # noqa: PLC0415
        import argparse  # noqa: PLC0415
        import e2e_dev_harness  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _code, start_result = e2e_dev_harness.start(
                argparse.Namespace(
                    repo=repo,
                    feature="Quote",
                    request="Return a quote.",
                    design_doc=None,
                    agent_run_dir=None,
                    run_id="run",
                    run_date=None,
                    force=False,
                    status_file=None,
                )
            )
            status_file = repo / "map-status.json"

            code, result = map_command.run_from_args(
                argparse.Namespace(
                    repo=repo,
                    state=Path(start_result["run_state"]),
                    runtime="claude-code",
                    status_file=status_file,
                )
            )
            status_payload = json.loads(status_file.read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertEqual("e2e-dev-harness.navigation-map.v1", result["schema"])
        self.assertEqual("CREATED", result["you_are_here"]["lifecycle"])
        self.assertEqual("CLARIFY", result["you_are_here"]["workflow_stage"])
        self.assertEqual(result, status_payload)
        self.assertNotIn("workflow_plan", result)
        self.assertNotIn("todo_policy", result)

    def test_cli_command_modules_preserve_guard_pre_code_test_impact_and_ac_progress_contracts(self) -> None:
        import e2e_dev_harness  # noqa: PLC0415
        from e2e_harness.cli.commands import ac_progress as ac_progress_command  # noqa: PLC0415
        from e2e_harness.cli.commands import guard as guard_command  # noqa: PLC0415
        from e2e_harness.cli.commands import pre_code as pre_code_command  # noqa: PLC0415
        from e2e_harness.cli.commands import test_impact as test_impact_command  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            guard_status = repo / "guard-status.json"
            pre_code_status = repo / "pre-code-status.json"
            test_impact_status = repo / "test-impact-status.json"
            ac_progress_status = repo / "ac-progress-status.json"
            test_impact_output = Path("docs/agent-runs/run/evidence/test-impact-plan.json")
            guard_payload = {"ready": True, "blocked_reasons": [], "warnings": []}
            pre_code_payload = {"ready": True, "blocked_reasons": [], "warnings": []}
            test_impact_payload = {"schema": "e2e-dev-harness.test-impact-plan.v1", "ready": True, "commands": []}
            ac_progress_payload = {"ready": True, "blocked_reasons": [], "warnings": []}

            with patch.object(e2e_dev_harness.workflow_guard, "validate_status_file", return_value=guard_payload):
                guard_code, guard_result = guard_command.run(
                    repo,
                    verify_status=Path("verify-status.json"),
                    strict=True,
                    require_completion=True,
                    approval_file=Path("approval.md"),
                    status_file=guard_status,
                )
            with (
                patch.object(e2e_dev_harness.phase_guard, "validate_action", return_value=dict(pre_code_payload)),
                patch.object(e2e_dev_harness, "runtime_hook_status", return_value={"ready": True, "warnings": []}),
            ):
                pre_code_code, pre_code_result = pre_code_command.run(
                    repo,
                    tool="Edit",
                    paths=[Path("src/app.py")],
                    status_file=pre_code_status,
                )
            with (
                patch.object(e2e_dev_harness.test_impact_plan, "parse_changed_files", return_value=["src/app.py"]),
                patch.object(e2e_dev_harness.test_impact_plan, "build_plan", return_value=test_impact_payload),
            ):
                test_impact_code, test_impact_result = test_impact_command.run(
                    repo,
                    changed_files=Path("changed-files.txt"),
                    output=test_impact_output,
                    status_file=test_impact_status,
                )
            with patch.object(e2e_dev_harness.ac_progress_gate, "validate", return_value=ac_progress_payload):
                ac_progress_code, ac_progress_result = ac_progress_command.run(
                    repo,
                    coverage_matrix=Path("coverage.md"),
                    implementation_manifest=Path("manifest.md"),
                    unit_test_evidence=Path("unit-test.json"),
                    status_file=ac_progress_status,
                )

            self.assertEqual(0, guard_code, guard_result)
            self.assertEqual(guard_result, json.loads(guard_status.read_text(encoding="utf-8")))
            self.assertEqual(0, pre_code_code, pre_code_result)
            self.assertTrue(pre_code_result["pre_code"])
            self.assertEqual([str(Path("src/app.py"))], pre_code_result["paths_checked"])
            self.assertEqual(0, test_impact_code, test_impact_result)
            self.assertTrue((repo / test_impact_output).exists())
            self.assertEqual(test_impact_result, json.loads(test_impact_status.read_text(encoding="utf-8")))
            self.assertEqual(0, ac_progress_code, ac_progress_result)
            self.assertEqual(ac_progress_result, json.loads(ac_progress_status.read_text(encoding="utf-8")))

    def test_cli_command_modules_preserve_service_design_contracts(self) -> None:
        from e2e_harness.cli.commands import service_design as service_design_command  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design, state_path, service_design = write_service_design_fixture(repo)
            code, result = service_design_command.run(
                repo,
                global_design=design.relative_to(repo),
                service_designs=[service_design.relative_to(repo)],
                run_state=state_path.relative_to(repo),
            )
            projected = json.loads((state_path.parent / "snapshots" / "run-state.json").read_text(encoding="utf-8"))

            generated_dir = Path("docs/agent-runs/run/generated-service-designs")
            template_code, template_result = service_design_command.run(
                repo,
                global_design=design.relative_to(repo),
                service_design_dir=generated_dir,
                emit_templates=["services/payment-service"],
            )
            generated = repo / generated_dir / "payment-service.md"
            generated_text = generated.read_text(encoding="utf-8")

        self.assertEqual(0, code, result)
        self.assertEqual("PLANNED", projected["lifecycle"])
        self.assertTrue(result["run_state_transition"]["ready"], result["run_state_transition"]["blocked_reasons"])
        self.assertEqual(0, template_code, template_result)
        self.assertIn("docs/agent-runs/run/generated-service-designs/payment-service.md", template_result["templates_written"])
        self.assertIn("Primary development contract", generated_text)

    def test_cli_command_modules_preserve_clarify_and_gate_contracts(self) -> None:
        from e2e_harness.cli.commands import clarify as clarify_command  # noqa: PLC0415
        from e2e_harness.cli.commands import gate as gate_command  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design, state_path = write_clarify_fixture(repo)
            clarify_code, clarify_result = clarify_command.run(
                repo,
                design_doc=design.relative_to(repo),
                run_state=state_path.relative_to(repo),
                require_intent=True,
                require_user_confirmation=True,
            )

            gate_state_path = repo / "docs" / "agent-runs" / "gate-run" / "run-state.json"
            red = gate_state_path.parent / "evidence" / "red-test.txt"
            red.parent.mkdir(parents=True, exist_ok=True)
            red.write_text("expected failure\n", encoding="utf-8")
            state = run_state.build_state(
                "docs/agent-runs/gate-run",
                "single",
                [],
                "docs/agent-runs/gate-run/artifact-registry.json",
                "PLANNED",
            )
            run_state.write_state(repo, gate_state_path, state)
            gate_payload = {
                "phase": "implementation",
                "ready": True,
                "blocked_reasons": [],
                "warnings": [],
                "knowledge_graph_status_loaded": True,
                "tdd": {"ready": True, "red_evidence": red.relative_to(repo).as_posix()},
                "semantic_reviews": {"ready": True, "covered_phases": ["design", "test"]},
            }
            with patch.object(gate_command.implementation_gate, "validate_gate_request", return_value=gate_payload):
                gate_code, gate_result = gate_command.run(
                    repo,
                    phase="implementation",
                    run_state=gate_state_path.relative_to(repo),
                    red_test_evidence=red,
                )
            clarify_projected = json.loads(
                (state_path.parent / "snapshots" / "run-state.json").read_text(encoding="utf-8")
            )
            gate_projected = json.loads(
                (gate_state_path.parent / "snapshots" / "run-state.json").read_text(encoding="utf-8")
            )

        self.assertEqual(0, clarify_code, clarify_result)
        self.assertEqual("CLARIFIED", clarify_projected["lifecycle"])
        self.assertTrue(clarify_result["blocked_next_without_plan"])
        self.assertEqual(0, gate_code, gate_result)
        self.assertEqual("IMPLEMENTED", gate_projected["lifecycle"])
        self.assertTrue(gate_result["run_state_transition"]["ready"])

    def test_cli_command_modules_preserve_doctor_recover_and_runtime_capability_contracts(self) -> None:
        import argparse  # noqa: PLC0415
        from e2e_harness.cli.commands import doctor as doctor_command  # noqa: PLC0415
        from e2e_harness.cli.commands import recover as recover_command  # noqa: PLC0415
        from e2e_harness.cli.commands import runtime_capabilities  # noqa: PLC0415
        from e2e_harness.cli.commands import timeline as timeline_command  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            doctor_status = repo / "doctor-status.json"
            recover_status = repo / "recover-status.json"
            timeline_status = repo / "timeline-status.json"
            capabilities_status = repo / "runtime-capabilities-status.json"
            schedule, state_path = write_dispatch_fixture(repo)
            dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "code-agent.md"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text("worker evidence\n", encoding="utf-8")

            doctor_result = doctor_command.run(repo, strict=False, state=state_path)
            doctor_code, doctor_from_args = doctor_command.run_from_args(
                argparse.Namespace(repo=repo, strict=False, state=state_path, status_file=doctor_status)
            )
            recover_result = recover_command.run(
                repo,
                state=state_path,
                schedule=schedule,
                task_id="T10",
                agent="code-developer-order-service",
                evidence=[evidence.relative_to(repo).as_posix()],
            )
            recover_code, recover_from_args = recover_command.run_from_args(
                argparse.Namespace(
                    repo=repo,
                    state=state_path,
                    schedule=schedule,
                    task_id="T10",
                    agent="code-developer-order-service",
                    evidence=[evidence.relative_to(repo).as_posix()],
                    status_file=recover_status,
                )
            )
            timeline_code, timeline_from_args = timeline_command.run_from_args(
                argparse.Namespace(repo=repo, state=state_path, status_file=timeline_status)
            )
            capabilities = runtime_capabilities.run("codex")
            capabilities_code, capabilities_from_args = runtime_capabilities.run_from_args(
                argparse.Namespace(repo=repo, runtime="codex", status_file=capabilities_status)
            )
            doctor_status_payload = json.loads(doctor_status.read_text(encoding="utf-8"))
            recover_status_payload = json.loads(recover_status.read_text(encoding="utf-8"))
            timeline_status_payload = json.loads(timeline_status.read_text(encoding="utf-8"))
            capabilities_status_payload = json.loads(capabilities_status.read_text(encoding="utf-8"))

        self.assertEqual("e2e-dev-harness.doctor.v1", doctor_result["schema"])
        self.assertEqual(0 if doctor_from_args["ready"] else 2, doctor_code)
        self.assertEqual(doctor_from_args, doctor_status_payload)
        self.assertEqual("e2e-dev-harness.recovery-plan.v1", recover_result["schema"])
        self.assertEqual(2, recover_code)
        self.assertEqual(recover_from_args, recover_status_payload)
        self.assertEqual(0, timeline_code)
        self.assertEqual(timeline_from_args, timeline_status_payload)
        self.assertEqual("codex", capabilities["runtime"])
        self.assertTrue(capabilities["ready"])
        self.assertEqual(0, capabilities_code)
        self.assertEqual(capabilities_from_args, capabilities_status_payload)

    def test_dispatch_cli_command_facade_preserves_dispatch_contracts(self) -> None:
        from e2e_harness.cli.commands import dispatch as dispatch_command  # noqa: PLC0415
        import install_hooks  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            install_hooks.install(repo, "claude")
            next_code, next_result = dispatch_command.run_next(
                repo,
                schedule=schedule.relative_to(repo),
                state=state_path.relative_to(repo),
                runtime="codex",
            )
            status_result = dispatch_command.run_status(
                repo,
                schedule=schedule.relative_to(repo),
                state=state_path.relative_to(repo),
            )
            ack_result = dispatch_command.run_ack(
                repo,
                state=state_path.relative_to(repo),
                task_id="T10",
                agent="code-developer-order-service",
                worker_handle="worker-T10",
                worker_session="session-T10",
            )
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "code-agent.md"
            output = repo / "docs" / "agent-runs" / "run" / "evidence" / "code-agent-output.md"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("worker evidence\n", encoding="utf-8")
            output_ref = output.relative_to(repo).as_posix()
            output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
            input_ref = "docs/agent-runs/run/handoffs/01-requirements.md"
            input_hash = hashlib.sha256((repo / input_ref).read_bytes()).hexdigest()
            evidence.write_text(
                "\n".join(
                    [
                        "---",
                        "agent: code-developer-order-service",
                        "agent_id: worker-T10",
                        "status: ready",
                        "inputs:",
                        "  - docs/agent-runs/run/handoffs/01-requirements.md",
                        "outputs:",
                        f"  - {output_ref}",
                        "input_hashes:",
                        f"  - {input_ref} sha256:{input_hash}",
                        "output_hashes:",
                        f"  - {output_ref} sha256:{output_hash}",
                        "consumed_by:",
                        "  - coordinator",
                        "open_questions: None",
                        "---",
                        "",
                        "## Summary",
                        "Code-agent evidence is ready.",
                        "",
                        "## Facts Used",
                        "The scheduled context pack and input handoff were reviewed.",
                        "",
                        "## Decisions Made",
                        "The worker returned the scheduled output reference.",
                        "",
                        "## Open Questions",
                        "None",
                        "",
                        "## Downstream Assumptions",
                        "The coordinator will validate the returned handoff.",
                        "",
                        "## Verification Evidence",
                        f"Evidence file {output_ref} was written and hashed.",
                    ]
                ),
                encoding="utf-8",
            )
            evidence.with_suffix(".ready.json").write_text(
                json.dumps(
                    {
                        "path": evidence.name,
                        "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                        "producer_agent": "worker-T10",
                        "status": "ready",
                    }
                ),
                encoding="utf-8",
            )
            complete_result = dispatch_command.run_complete(
                repo,
                schedule=schedule.relative_to(repo),
                state=state_path.relative_to(repo),
                task_id="T10",
                agent="code-developer-order-service",
                evidence=[evidence.relative_to(repo).as_posix()],
            )
            beat_code, beat_result = dispatch_command.run_beat(
                repo,
                schedule=schedule.relative_to(repo),
                state=state_path.relative_to(repo),
                runtime="codex",
                max_workers=1,
            )

        self.assertIn(next_code, {0, 2})
        self.assertIn("dispatch", next_result)
        self.assertEqual("e2e-dev-harness.dispatch-status.v1", status_result["schema"])
        self.assertTrue(ack_result["ready"], ack_result)
        self.assertTrue(complete_result["ready"], complete_result)
        self.assertIn(beat_code, {0, 2})
        self.assertIn("ready", beat_result)

    def test_agent_task_cli_command_facade_preserves_claim_and_validate_contracts(self) -> None:
        from e2e_harness.cli.commands import agent_task as agent_task_command  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule, state_path = write_dispatch_fixture(repo)
            validate_before = agent_task_command.run_validate(
                repo,
                schedule=schedule.relative_to(repo),
                services=["services/order-service"],
            )
            claim_result = agent_task_command.run_claim(
                repo,
                schedule=schedule.relative_to(repo),
                task_id="T10",
                agent="code-developer-order-service",
                state=state_path.relative_to(repo),
            )
            renew_result = agent_task_command.run_renew(
                repo,
                schedule=schedule.relative_to(repo),
                task_id="T10",
                agent="code-developer-order-service",
                state=state_path.relative_to(repo),
            )
            validate_after = agent_task_command.run_validate(
                repo,
                schedule=schedule.relative_to(repo),
                services=["services/order-service"],
                require_claims=True,
            )

        self.assertTrue(validate_before["ready"], validate_before)
        self.assertTrue(claim_result["ready"], claim_result)
        self.assertEqual("claimed", claim_result["task"]["status"])
        self.assertTrue(renew_result["ready"], renew_result)
        self.assertTrue(validate_after["ready"], validate_after)
        self.assertEqual("e2e-dev-harness.agent-task.v1", claim_result["schema"])

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
