"""Manual runtime adapter."""

from __future__ import annotations

from runtime_adapters import SpawnResult, adapter_for, normalize_runtime


class ManualAdapter:
    def __init__(self, runtime: str = "manual") -> None:
        self.name = normalize_runtime(runtime)
        self._legacy = adapter_for(self.name)

    def capabilities(self):
        return self._legacy.capability_contract()

    def spawn(self, task: dict, context_pack: dict, prompt: str) -> SpawnResult:
        return SpawnResult(self.name, str(task.get("id", "")), str(task.get("agent", "")) or "agent", "planned", None)

    def ack(self, task: dict, worker_handle: str, worker_session: str = "") -> dict:
        return self._legacy.ack(task, worker_handle, worker_session)

    def complete(self, task: dict, evidence: list[str] | None = None) -> dict:
        return self._legacy.complete(task, evidence)

    def recover(self, task: dict, reason: str) -> dict:
        return self._legacy.recover(task, reason)


def adapter(runtime: str = "manual") -> ManualAdapter:
    return ManualAdapter(runtime)
