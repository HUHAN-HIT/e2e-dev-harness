"""U2 — spawn_worker runtime seam.

Pure descriptor: spawn_worker(packet, runtime) translates a worker packet into a
runtime launch descriptor (no process spawned). Scope: claude-code + manual.
Portable subagent_type, per-role env override, and NO model pin (regression
guard for the glm-4.7 broken-dispatch).
"""
from harness_v2.adapters import runtime


def _packet(role="clarifier", skill="e2e-harness-clarification"):
    return {
        "schema": "e2e-dev-harness-v2.worker-packet.v1",
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


def test_claude_code_descriptor_shape():
    d = runtime.spawn_worker(_packet())
    assert d["schema"] == "e2e-dev-harness-v2.worker-descriptor.v1"
    assert d["runtime"] == "claude-code"
    assert d["tool"] == "Task"
    assert "prompt" in d["arguments"]
    assert "description" in d["arguments"]


def test_default_runtime_is_claude_code():
    assert runtime.spawn_worker(_packet())["runtime"] == "claude-code"


def test_subagent_type_defaults_to_general_purpose():
    d = runtime.spawn_worker(_packet())
    assert d["arguments"]["subagent_type"] == "general-purpose"


def test_env_override_sets_subagent_type(monkeypatch):
    monkeypatch.setenv("E2E_HARNESS_V2_SUBAGENT_TYPE_CLARIFIER", "my-clarifier-agent")
    d = runtime.spawn_worker(_packet(role="clarifier"))
    assert d["arguments"]["subagent_type"] == "my-clarifier-agent"


def test_no_model_key_anywhere_in_descriptor():
    # Regression guard: the seam must never pin a model (glm-4.7 breakage).
    d = runtime.spawn_worker(_packet())
    assert not _has_model_key(d)


def test_expected_outputs_and_context_paths_pass_through():
    pkt = _packet()
    d = runtime.spawn_worker(pkt)
    assert d["expected_outputs"] == pkt["expected_outputs"]
    assert d["context_paths"] == pkt["context_paths"]


def test_prompt_mentions_skill_and_expected_outputs():
    d = runtime.spawn_worker(_packet(skill="e2e-harness-clarification"))
    prompt = d["arguments"]["prompt"]
    assert "e2e-harness-clarification" in prompt
    assert "clarification" in prompt


def test_manual_descriptor():
    d = runtime.spawn_worker(_packet(), runtime="manual")
    assert d["runtime"] == "manual"
    assert d["tool"] is None
    assert "instruction" in d and d["instruction"]
    assert d["expected_outputs"] == ["clarification"]


def test_unknown_runtime_falls_back_to_manual_with_warning():
    d = runtime.spawn_worker(_packet(), runtime="codex")
    assert d["runtime"] == "manual"
    assert d.get("warning")
    assert "codex" in d["warning"]
