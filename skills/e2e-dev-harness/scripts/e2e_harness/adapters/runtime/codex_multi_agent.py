"""Codex multi-agent runtime adapter."""

from __future__ import annotations

from pathlib import Path

from runtime_adapters import SpawnResult, adapter_for


class CodexMultiAgentAdapter:
    name = "codex"

    def __init__(self) -> None:
        self._legacy = adapter_for("codex")

    def capabilities(self):
        return self._legacy.capability_contract()

    def spawn(self, task: dict, context_pack: dict, prompt: str) -> SpawnResult:
        repo = Path(str(context_pack.get("repo") or "."))
        schedule = Path(str(context_pack.get("schedule_path") or "agent-schedule.json"))
        state = Path(str(context_pack.get("state_path"))) if context_pack.get("state_path") else None
        request = self._legacy.spawn(task, prompt, schedule, state, repo)
        return SpawnResult("codex", str(task.get("id", "")), str(task.get("agent", "")) or "agent", "dispatch_requested", request)

    def ack(self, task: dict, worker_handle: str, worker_session: str = "") -> dict:
        return self._legacy.ack(task, worker_handle, worker_session)

    def complete(self, task: dict, evidence: list[str] | None = None) -> dict:
        return self._legacy.complete(task, evidence)

    def recover(self, task: dict, reason: str) -> dict:
        return self._legacy.recover(task, reason)


def adapter() -> CodexMultiAgentAdapter:
    return CodexMultiAgentAdapter()
