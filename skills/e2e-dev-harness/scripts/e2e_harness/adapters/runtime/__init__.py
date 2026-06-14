"""Narrow runtime seam (design §5): one `spawn_worker(packet) -> descriptor`.

Pure — translates a worker packet into a runtime-specific launch *descriptor*;
it never spawns a process. The coordinator performs the real tool call, staying
a pure control plane. Scope: codex + claude-code + opencode + manual. No model is
pinned, so the worker inherits the coordinator's accessible default model.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

DESCRIPTOR_SCHEMA = "e2e-dev-harness.worker-descriptor.v1"
PORTABLE_SUBAGENT_TYPE = "general-purpose"
AVAILABLE_SUBAGENTS_ENV = "E2E_HARNESS_AVAILABLE_SUBAGENTS"


def _declared_subagent_type(packet: dict | None = None) -> str:
    if not packet:
        return ""
    return str(packet.get("runtime_subagent_type", "")).strip()


def _available_subagent_types() -> set[str]:
    raw = os.environ.get(AVAILABLE_SUBAGENTS_ENV, "")
    return {part.strip() for part in raw.replace(";", ",").split(",") if part.strip()}


def _subagent_selection(role: str, packet: dict | None = None) -> dict:
    declared = _declared_subagent_type(packet)
    key = "E2E_HARNESS_SUBAGENT_TYPE_" + str(role).strip().upper().replace("-", "_")
    override = os.environ.get(key, "").strip()
    if override:
        return {
            "subagent_type": override,
            "requested_subagent_type": declared or override,
            "subagent_type_source": "env",
        }
    if declared:
        available = _available_subagent_types()
        if declared in available or "*" in available:
            return {
                "subagent_type": declared,
                "requested_subagent_type": declared,
                "subagent_type_source": "packet",
            }
        return {
            "subagent_type": PORTABLE_SUBAGENT_TYPE,
            "requested_subagent_type": declared,
            "subagent_type_source": "portable-fallback",
            "subagent_fallback_reason": "runtime_subagent_not_confirmed",
        }
    return {
        "subagent_type": PORTABLE_SUBAGENT_TYPE,
        "requested_subagent_type": PORTABLE_SUBAGENT_TYPE,
        "subagent_type_source": "default",
    }


def _subagent_type(role: str, packet: dict | None = None) -> str:
    return _subagent_selection(role, packet)["subagent_type"]


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
    selection = _subagent_selection(role, packet)
    descriptor = {
        "schema": DESCRIPTOR_SCHEMA,
        "runtime": "claude-code",
        "tool": "Task",
        "arguments": {
            "description": f"{role}: {skill}",
            "prompt": _prompt(packet),
            "subagent_type": selection["subagent_type"],
        },
        "requested_subagent_type": selection["requested_subagent_type"],
        "subagent_type_source": selection["subagent_type_source"],
        "context_paths": list(packet.get("context_paths", []) or []),
        "expected_outputs": list(packet.get("expected_outputs", []) or []),
        "context_policy": "fresh Claude Code Task only; no inherited coordinator chat beyond these context_paths.",
    }
    if selection.get("subagent_fallback_reason"):
        descriptor["subagent_fallback_reason"] = selection["subagent_fallback_reason"]
    return descriptor


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
    selection = _subagent_selection(role, packet)
    descriptor = {
        "schema": DESCRIPTOR_SCHEMA,
        "runtime": "opencode",
        "tool": "task",
        "arguments": {
            "description": f"{role}: {skill}",
            "prompt": _prompt(packet),
            "subagent_type": selection["subagent_type"],
        },
        "requested_subagent_type": selection["requested_subagent_type"],
        "subagent_type_source": selection["subagent_type_source"],
        "context_paths": list(packet.get("context_paths", []) or []),
        "expected_outputs": list(packet.get("expected_outputs", []) or []),
        "context_policy": "fresh opencode task subagent only; no inherited coordinator chat beyond these context_paths.",
    }
    if selection.get("subagent_fallback_reason"):
        descriptor["subagent_fallback_reason"] = selection["subagent_fallback_reason"]
    return descriptor


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


@dataclass(frozen=True)
class RuntimeCapabilities:
    """Pure capability data for a runtime (design §4.1).

    Invariant (enforced by the contract test): ``can_auto_spawn`` is true iff a
    ``spawn_tool`` exists — i.e. iff the runtime can launch an isolated worker on
    its own. ``manual`` (and any unknown runtime) cannot, so dispatch must block
    rather than let the coordinator self-deal.
    """

    name: str
    can_auto_spawn: bool
    spawn_tool: str | None


class RuntimeAdapter(Protocol):
    """Uniform runtime seam (design §4.2). The dispatcher talks only to this."""

    name: str

    def capabilities(self) -> RuntimeCapabilities: ...

    def spawn(self, packet: dict) -> dict: ...


class _SpawnAdapter:
    """Auto-spawn runtime: wraps an existing packet→descriptor function."""

    def __init__(self, name: str, spawn_tool: str, spawn_fn) -> None:
        self.name = name
        self._caps = RuntimeCapabilities(name, True, spawn_tool)
        self._spawn_fn = spawn_fn

    def capabilities(self) -> RuntimeCapabilities:
        return self._caps

    def spawn(self, packet: dict) -> dict:
        return self._spawn_fn(packet)


class _ManualAdapter:
    """Manual / unknown runtime: cannot auto-spawn (carries an optional warning)."""

    name = "manual"

    def __init__(self, warning: str = "") -> None:
        self._warning = warning

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities("manual", False, None)

    def spawn(self, packet: dict) -> dict:
        return _manual(packet, warning=self._warning)


def get_adapter(runtime: str = "codex") -> RuntimeAdapter:
    """Resolve a runtime name to its adapter. Unknown → manual (with a warning)."""
    name = (runtime or "codex").strip().lower()
    if name in {"codex", "codex-app"}:
        return _SpawnAdapter("codex", "multi_agent_v1.spawn_agent", _codex)
    if name == "claude-code":
        return _SpawnAdapter("claude-code", "Task", _claude_code)
    if name == "opencode":
        return _SpawnAdapter("opencode", "task", _opencode)
    if name == "manual":
        return _ManualAdapter()
    return _ManualAdapter(warning=f"Unknown runtime {name!r}; falling back to manual dispatch.")


def spawn_worker(packet: dict, runtime: str = "codex") -> dict:
    """Backward-compat shim: translate a packet into a runtime launch descriptor.

    Delegates to the resolved adapter; output is unchanged from the original
    free-function seam. Unknown runtimes fall back to `manual` with a `warning`.
    """
    return get_adapter(runtime).spawn(packet)


__all__ = [
    "spawn_worker",
    "get_adapter",
    "RuntimeAdapter",
    "RuntimeCapabilities",
    "DESCRIPTOR_SCHEMA",
]
