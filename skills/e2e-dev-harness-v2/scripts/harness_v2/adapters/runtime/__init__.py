"""Narrow runtime seam (design §5): one `spawn_worker(packet) -> descriptor`.

Pure — translates a worker packet into a runtime-specific launch *descriptor*;
it never spawns a process. The coordinator performs the real tool call, staying
a pure control plane. Scope: codex + claude-code + opencode + manual. No model is
pinned, so the worker inherits the coordinator's accessible default model.
"""
from __future__ import annotations

import os

DESCRIPTOR_SCHEMA = "e2e-dev-harness-v2.worker-descriptor.v1"
PORTABLE_SUBAGENT_TYPE = "general-purpose"


def _subagent_type(role: str) -> str:
    key = "E2E_HARNESS_V2_SUBAGENT_TYPE_" + str(role).strip().upper().replace("-", "_")
    override = os.environ.get(key, "").strip()
    return override or PORTABLE_SUBAGENT_TYPE


def _prompt(packet: dict) -> str:
    role = packet.get("role", "")
    skill = packet.get("skill", "")
    context_paths = packet.get("context_paths", []) or []
    expected = packet.get("expected_outputs", []) or []
    lines = [
        f"You are the {role} worker. Run the `{skill}` skill in a fresh context.",
        "Read only these context paths (no inherited coordinator chat):",
        *[f"  - {p}" for p in context_paths],
        "Produce these expected outputs:",
        *[f"  - {o}" for o in expected],
    ]
    return "\n".join(lines)


def _claude_code(packet: dict) -> dict:
    role = packet.get("role", "")
    skill = packet.get("skill", "")
    return {
        "schema": DESCRIPTOR_SCHEMA,
        "runtime": "claude-code",
        "tool": "Task",
        "arguments": {
            "description": f"{role}: {skill}",
            "prompt": _prompt(packet),
            "subagent_type": _subagent_type(role),
        },
        "context_paths": list(packet.get("context_paths", []) or []),
        "expected_outputs": list(packet.get("expected_outputs", []) or []),
        "context_policy": "fresh Claude Code Task only; no inherited coordinator chat beyond these context_paths.",
    }


def _codex(packet: dict) -> dict:
    role = packet.get("role", "")
    skill = packet.get("skill", "")
    return {
        "schema": DESCRIPTOR_SCHEMA,
        "runtime": "codex",
        "tool": "multi_agent_v1.spawn_agent",
        "arguments": {
            "agent_type": "worker",
            "fork_context": False,
            "message": _prompt(packet),
        },
        "description": f"{role}: {skill}",
        "context_paths": list(packet.get("context_paths", []) or []),
        "expected_outputs": list(packet.get("expected_outputs", []) or []),
        "context_policy": "fresh Codex worker only; fork_context=false; use context paths instead of coordinator chat.",
    }


def _opencode(packet: dict) -> dict:
    role = packet.get("role", "")
    skill = packet.get("skill", "")
    return {
        "schema": DESCRIPTOR_SCHEMA,
        "runtime": "opencode",
        "tool": "task",
        "arguments": {
            "description": f"{role}: {skill}",
            "prompt": _prompt(packet),
            "subagent_type": _subagent_type(role),
        },
        "context_paths": list(packet.get("context_paths", []) or []),
        "expected_outputs": list(packet.get("expected_outputs", []) or []),
        "context_policy": "fresh opencode task subagent only; no inherited coordinator chat beyond these context_paths.",
    }


def _manual(packet: dict, warning: str = "") -> dict:
    skill = packet.get("skill", "")
    descriptor = {
        "schema": DESCRIPTOR_SCHEMA,
        "runtime": "manual",
        "tool": None,
        "instruction": (
            f"Run the `{skill}` worker yourself using the listed context_paths; "
            "produce the expected_outputs."
        ),
        "context_paths": list(packet.get("context_paths", []) or []),
        "expected_outputs": list(packet.get("expected_outputs", []) or []),
    }
    if warning:
        descriptor["warning"] = warning
    return descriptor


def spawn_worker(packet: dict, runtime: str = "codex") -> dict:
    """Translate a worker packet into a runtime launch descriptor (no process spawned).

    Unknown runtimes fall back to `manual` with a `warning` rather than raising.
    """
    name = (runtime or "codex").strip().lower()
    if name in {"codex", "codex-app"}:
        return _codex(packet)
    if name == "claude-code":
        return _claude_code(packet)
    if name == "opencode":
        return _opencode(packet)
    if name == "manual":
        return _manual(packet)
    return _manual(packet, warning=f"Unknown runtime {name!r}; falling back to manual dispatch.")


__all__ = ["spawn_worker", "DESCRIPTOR_SCHEMA"]
