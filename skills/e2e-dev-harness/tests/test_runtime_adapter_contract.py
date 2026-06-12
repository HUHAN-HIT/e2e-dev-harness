"""Gap 4 (b) — uniform RuntimeAdapter contract across all runtimes.

Every runtime adapter, fetched via get_adapter(), must satisfy the SAME
invariants so failure semantics stay consistent across claude-code / codex /
opencode / manual (design §4.5). This is the contract test the architecture's
Phase 3 calls for.
"""
import pytest

from e2e_harness.adapters import runtime


RUNTIMES = ["claude-code", "codex", "opencode", "manual"]


def _packet(role="clarifier", skill="e2e-harness-clarification"):
    return {
        "schema": "e2e-dev-harness.worker-packet.v1",
        "role": role,
        "skill": skill,
        "context_paths": ["docs/agent-runs/r1/run-state.json"],
        "expected_outputs": ["clarification"],
    }


def _has_model_key(obj) -> bool:
    if isinstance(obj, dict):
        if any(k == "model" for k in obj):
            return True
        return any(_has_model_key(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_model_key(x) for x in obj)
    return False


def _prompt_text(desc) -> str:
    args = desc.get("arguments", {})
    return args.get("prompt") or args.get("message") or ""


@pytest.mark.parametrize("name", RUNTIMES)
def test_get_adapter_exposes_capabilities_and_spawn(name):
    adapter = runtime.get_adapter(name)
    caps = adapter.capabilities()
    assert isinstance(caps, runtime.RuntimeCapabilities)
    assert caps.name == name
    desc = adapter.spawn(_packet())
    assert desc["schema"] == runtime.DESCRIPTOR_SCHEMA


@pytest.mark.parametrize("name", RUNTIMES)
def test_no_model_key_for_any_runtime(name):
    desc = runtime.get_adapter(name).spawn(_packet())
    assert not _has_model_key(desc)


@pytest.mark.parametrize("name", RUNTIMES)
def test_passthrough_context_and_outputs(name):
    pkt = _packet()
    desc = runtime.get_adapter(name).spawn(pkt)
    assert desc["context_paths"] == pkt["context_paths"]
    assert desc["expected_outputs"] == pkt["expected_outputs"]


@pytest.mark.parametrize("name", RUNTIMES)
def test_can_auto_spawn_iff_tool_present(name):
    adapter = runtime.get_adapter(name)
    caps = adapter.capabilities()
    desc = adapter.spawn(_packet())
    assert caps.can_auto_spawn == (desc.get("tool") is not None)


@pytest.mark.parametrize("name", ["claude-code", "codex", "opencode"])
def test_auto_spawn_runtimes_carry_fresh_context_and_skill(name):
    desc = runtime.get_adapter(name).spawn(_packet(skill="e2e-harness-clarification"))
    assert "fresh" in desc["context_policy"].lower()
    text = _prompt_text(desc)
    assert "e2e-harness-clarification" in text
    assert "clarification" in text


def test_manual_cannot_auto_spawn():
    caps = runtime.get_adapter("manual").capabilities()
    assert caps.can_auto_spawn is False
    assert caps.spawn_tool is None


def test_codex_app_alias_normalizes_to_codex():
    assert runtime.get_adapter("codex-app").capabilities().name == "codex"


def test_unknown_runtime_capability_is_manual_and_warns():
    adapter = runtime.get_adapter("made-up-runtime")
    assert adapter.capabilities().can_auto_spawn is False
    desc = adapter.spawn(_packet())
    assert desc["runtime"] == "manual"
    assert desc.get("warning")


def test_spawn_worker_shim_still_delegates():
    # Backward-compat: the free function stays byte-compatible (default codex).
    assert runtime.spawn_worker(_packet())["runtime"] == "codex"
    assert runtime.spawn_worker(_packet(), runtime="manual")["runtime"] == "manual"
