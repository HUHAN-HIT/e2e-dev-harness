#!/usr/bin/env python3
"""Runtime adapter contracts for e2e-dev-harness dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from common import posix


CLAUDE_CAPABILITIES = {
    "runtime": "claude-code",
    "supports_subagent": True,
    "supports_task_hook": True,
    "supports_isolated_review": True,
    "supports_blocking_stop": True,
    "dispatch_mode": "native-subagent",
    "spawn_tool": "Task",
    "spawn_requires_tool_call": True,
    "spawn_acknowledgement": "phase_guard_task_hook_or_dispatch_ack",
}

CODEX_CAPABILITIES = {
    "runtime": "codex",
    "supports_subagent": True,
    "supports_task_hook": False,
    "supports_isolated_review": True,
    "supports_blocking_stop": False,
    "dispatch_mode": "codex-multi-agent-v1",
    "spawn_tool": "multi_agent_v1.spawn_agent",
    "spawn_requires_tool_call": True,
}

MANUAL_CAPABILITIES = {
    "runtime": "manual",
    "supports_subagent": False,
    "supports_task_hook": False,
    "supports_isolated_review": False,
    "supports_blocking_stop": False,
    "dispatch_mode": "manual-dispatch",
}


def normalize_runtime(runtime: str | None) -> str:
    text = (runtime or "claude-code").strip().lower().replace("_", "-")
    aliases = {
        "claude": "claude-code",
        "claude-code": "claude-code",
        "manual": "manual",
        "codex": "codex",
        "codex-app": "codex",
        "gemini": "gemini",
        "opencode": "opencode",
    }
    return aliases.get(text, text)


def _resolve(repo: Path, path: Path | str | None) -> Path | None:
    if not path:
        return None
    value = path if isinstance(path, Path) else Path(str(path))
    return value if value.is_absolute() else repo / value


def _rel(repo: Path, path: Path) -> str:
    try:
        return posix(path.resolve().relative_to(repo.resolve()))
    except (OSError, ValueError):
        return posix(str(path))


def _completion_commands(task: dict, schedule_path: Path, state_path: Path | None, repo: Path) -> tuple[str, str]:
    task_id = str(task.get("id", ""))
    agent = str(task.get("agent", "")) or "agent"
    evidence_args = " ".join(f"--evidence {item}" for item in task.get("outputs", []) or ["<evidence-path>"])
    state_arg = f" --state {_rel(repo, _resolve(repo, state_path) or state_path)}" if state_path else ""
    completion_command = (
        "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-complete . "
        f"--schedule {_rel(repo, _resolve(repo, schedule_path) or schedule_path)}"
        f"{state_arg} --task-id {task_id} --agent {agent} {evidence_args}"
    )
    ack_command = (
        "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py dispatch-ack ."
        f"{state_arg} --task-id {task_id} --agent {agent}"
        " --worker-handle <runtime-worker-id> --worker-session <runtime-worker-session>"
    )
    return ack_command, completion_command


@dataclass(frozen=True)
class RuntimeAdapter:
    name: str
    _capabilities: dict

    def capabilities(self) -> dict:
        return dict(self._capabilities)

    def spawn(
        self,
        task: dict,
        prompt: str,
        schedule_path: Path,
        state_path: Path | None,
        repo: Path,
    ) -> dict | None:
        capabilities = self.capabilities()
        task_id = str(task.get("id", ""))
        agent = str(task.get("agent", "")) or "agent"
        ack_command, completion_command = _completion_commands(task, schedule_path, state_path, repo)
        subagent_type = str(task.get("runtime_subagent_type") or "").strip() or "general-purpose"
        if capabilities.get("spawn_tool") == "Task":
            return {
                "schema": "e2e-dev-harness.runtime-spawn-request.v1",
                "runtime": capabilities.get("runtime", ""),
                "tool": "Task",
                "arguments": {
                    "description": f"{task_id} {agent}",
                    "prompt": prompt,
                    "subagent_type": subagent_type,
                },
                "task_id": task_id,
                "agent": agent,
                "ack_command": ack_command,
                "completion_command": completion_command,
                "context_policy": "fresh Claude Code Task only; no inherited coordinator chat beyond this prompt and context pack.",
            }
        if capabilities.get("spawn_tool") == "multi_agent_v1.spawn_agent":
            return {
                "schema": "e2e-dev-harness.runtime-spawn-request.v1",
                "runtime": capabilities.get("runtime", ""),
                "tool": "multi_agent_v1.spawn_agent",
                "arguments": {
                    "agent_type": "worker",
                    "fork_context": False,
                    "message": prompt,
                },
                "task_id": task_id,
                "agent": agent,
                "ack_command": ack_command,
                "completion_command": completion_command,
                "context_policy": "fresh worker only; fork_context=false; use context pack instead of coordinator chat.",
            }
        return None

    def ack(self, task: dict, worker_handle: str, worker_session: str = "") -> dict:
        return {
            "task_id": str(task.get("id", "")),
            "worker_handle": worker_handle.strip(),
            "worker_session": worker_session.strip() or worker_handle.strip(),
        }

    def complete(self, task: dict, evidence: list[str] | None = None) -> dict:
        return {"task_id": str(task.get("id", "")), "evidence": evidence or []}

    def recover(self, task: dict, reason: str) -> dict:
        return {"task_id": str(task.get("id", "")), "reason": reason}


def adapter_for(runtime: str | None = "claude-code") -> RuntimeAdapter:
    normalized = normalize_runtime(runtime)
    if normalized == "claude-code":
        return RuntimeAdapter("claude-code", CLAUDE_CAPABILITIES)
    if normalized == "codex":
        return RuntimeAdapter("codex", CODEX_CAPABILITIES)
    if normalized == "manual":
        return RuntimeAdapter("manual", MANUAL_CAPABILITIES)
    data = dict(MANUAL_CAPABILITIES)
    data["runtime"] = normalized
    return RuntimeAdapter(normalized, data)
