"""Schema-versioned domain contracts for the enterprise harness core."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


RUN_STATE_SCHEMA = "e2e-dev-harness.run-state.v1"
LIFECYCLE_TRANSITION_SCHEMA = "e2e-dev-harness.lifecycle-transition.v1"
TASK_SCHEDULE_SCHEMA = "e2e-dev-harness.agent-schedule.v1"
DISPATCH_RECORD_SCHEMA = "e2e-dev-harness.dispatch-record.v1"
EVIDENCE_REF_SCHEMA = "e2e-dev-harness.evidence-ref.v1"
GATE_RESULT_SCHEMA = "e2e-dev-harness.gate-result.v1"
EXECUTION_PACKET_SCHEMA = "e2e-dev-harness.execution-packet.v1"


def _strings(values: list[Any] | None) -> list[str]:
    return [str(item) for item in values or []]


@dataclass(frozen=True)
class RunState:
    run_id: str
    lifecycle: str
    selected_mode: str
    services: list[str] = field(default_factory=list)
    gates: dict[str, str] = field(default_factory=dict)
    owners: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    schema: str = RUN_STATE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "lifecycle": self.lifecycle,
            "selected_mode": self.selected_mode,
            "services": list(self.services),
            "gates": dict(self.gates),
            "owners": dict(self.owners),
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunState":
        return cls(
            run_id=str(data.get("run_id", "")),
            lifecycle=str(data.get("lifecycle", "")),
            selected_mode=str(data.get("selected_mode", "")),
            services=_strings(data.get("services", [])),
            gates=dict(data.get("gates", {}) if isinstance(data.get("gates"), dict) else {}),
            owners=dict(data.get("owners", {}) if isinstance(data.get("owners"), dict) else {}),
            history=list(data.get("history", []) if isinstance(data.get("history"), list) else []),
            schema=str(data.get("schema", RUN_STATE_SCHEMA)),
        )


@dataclass(frozen=True)
class LifecycleTransition:
    from_lifecycle: str
    to_lifecycle: str
    gate: str = ""
    evidence: str = ""
    status: str = ""
    schema: str = LIFECYCLE_TRANSITION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "from": self.from_lifecycle,
            "to": self.to_lifecycle,
            "gate": self.gate,
            "evidence": self.evidence,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LifecycleTransition":
        return cls(
            from_lifecycle=str(data.get("from", data.get("from_lifecycle", ""))),
            to_lifecycle=str(data.get("to", data.get("to_lifecycle", ""))),
            gate=str(data.get("gate", "")),
            evidence=str(data.get("evidence", "")),
            status=str(data.get("status", data.get("gate_status", ""))),
            schema=str(data.get("schema", LIFECYCLE_TRANSITION_SCHEMA)),
        )


@dataclass(frozen=True)
class TaskSchedule:
    tasks: list[dict[str, Any]] = field(default_factory=list)
    completion_mode: str = ""
    schema: str = TASK_SCHEDULE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        data = {"schema": self.schema, "tasks": list(self.tasks)}
        if self.completion_mode:
            data["completion_mode"] = self.completion_mode
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskSchedule":
        return cls(
            tasks=list(data.get("tasks", []) if isinstance(data.get("tasks"), list) else []),
            completion_mode=str(data.get("completion_mode", "")),
            schema=str(data.get("schema", TASK_SCHEDULE_SCHEMA)),
        )


@dataclass(frozen=True)
class DispatchRecord:
    task_id: str
    agent: str
    runtime: str
    status: str
    worker_handle: str = ""
    worker_session: str = ""
    schema: str = DISPATCH_RECORD_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "agent": self.agent,
            "runtime": self.runtime,
            "status": self.status,
            "worker_handle": self.worker_handle,
            "worker_session": self.worker_session,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchRecord":
        return cls(
            task_id=str(data.get("task_id", data.get("current_task_id", ""))),
            agent=str(data.get("agent", data.get("current_agent", ""))),
            runtime=str(data.get("runtime", "")),
            status=str(data.get("status", "")),
            worker_handle=str(data.get("worker_handle", "")),
            worker_session=str(data.get("worker_session", "")),
            schema=str(data.get("schema", DISPATCH_RECORD_SCHEMA)),
        )


@dataclass(frozen=True)
class EvidenceRef:
    path: str
    sha256: str
    type: str
    producer: str
    validation_status: str
    schema: str = EVIDENCE_REF_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "path": self.path,
            "sha256": self.sha256,
            "type": self.type,
            "producer": self.producer,
            "validation_status": self.validation_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceRef":
        return cls(
            path=str(data.get("path", "")),
            sha256=str(data.get("sha256", "")),
            type=str(data.get("type", "")),
            producer=str(data.get("producer", data.get("producer_agent", ""))),
            validation_status=str(data.get("validation_status", data.get("status", ""))),
            schema=str(data.get("schema", EVIDENCE_REF_SCHEMA)),
        )


@dataclass(frozen=True)
class GateResult:
    ready: bool
    blocked_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    required_fixes: list[str] = field(default_factory=list)
    schema: str = GATE_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ready": self.ready,
            "blocked_reasons": list(self.blocked_reasons),
            "warnings": list(self.warnings),
            "required_fixes": list(self.required_fixes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GateResult":
        return cls(
            ready=bool(data.get("ready", False)),
            blocked_reasons=_strings(data.get("blocked_reasons", [])),
            warnings=_strings(data.get("warnings", [])),
            required_fixes=_strings(data.get("required_fixes", [])),
            schema=str(data.get("schema", GATE_RESULT_SCHEMA)),
        )


@dataclass(frozen=True)
class ExecutionPacket:
    lifecycle: str
    objective: str
    primary_command: str
    allowed_writes: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    completion_checks: list[str] = field(default_factory=list)
    next_gate: str = ""
    schema: str = EXECUTION_PACKET_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "lifecycle": self.lifecycle,
            "objective": self.objective,
            "primary_command": self.primary_command,
            "allowed_writes": list(self.allowed_writes),
            "forbidden_actions": list(self.forbidden_actions),
            "required_evidence": list(self.required_evidence),
            "completion_checks": list(self.completion_checks),
            "next_gate": self.next_gate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionPacket":
        return cls(
            lifecycle=str(data.get("lifecycle", "")),
            objective=str(data.get("objective", "")),
            primary_command=str(data.get("primary_command", "")),
            allowed_writes=_strings(data.get("allowed_writes", [])),
            forbidden_actions=_strings(data.get("forbidden_actions", [])),
            required_evidence=_strings(data.get("required_evidence", [])),
            completion_checks=_strings(data.get("completion_checks", [])),
            next_gate=str(data.get("next_gate", "")),
            schema=str(data.get("schema", EXECUTION_PACKET_SCHEMA)),
        )
