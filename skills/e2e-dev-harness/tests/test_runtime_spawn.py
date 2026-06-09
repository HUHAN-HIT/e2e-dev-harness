"""U2 — spawn_worker runtime seam.

Pure descriptor: spawn_worker(packet, runtime) translates a worker packet into a
runtime launch descriptor (no process spawned). Scope: claude-code + manual.
Portable subagent_type, per-role env override, and NO model pin (regression
guard for the glm-4.7 broken-dispatch).
"""
from e2e_harness.adapters import runtime


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


def test_claude_code_descriptor_shape():
    d = runtime.spawn_worker(_packet(), runtime="claude-code")
    assert d["schema"] == "e2e-dev-harness.worker-descriptor.v1"
    assert d["runtime"] == "claude-code"
    assert d["tool"] == "Task"
    assert "prompt" in d["arguments"]
    assert "description" in d["arguments"]


def test_default_runtime_is_codex_spawn_agent_without_model_pin():
    d = runtime.spawn_worker(_packet())
    assert d["runtime"] == "codex"
    assert d["tool"] == "multi_agent_v1.spawn_agent"
    assert d["arguments"]["agent_type"] == "worker"
    assert d["arguments"]["fork_context"] is False
    assert "message" in d["arguments"]
    assert not _has_model_key(d)


def test_subagent_type_defaults_to_general_purpose():
    d = runtime.spawn_worker(_packet(), runtime="claude-code")
    assert d["arguments"]["subagent_type"] == "general-purpose"


def test_env_override_sets_subagent_type(monkeypatch):
    monkeypatch.setenv("E2E_HARNESS_SUBAGENT_TYPE_CLARIFIER", "my-clarifier-agent")
    d = runtime.spawn_worker(_packet(role="clarifier"), runtime="claude-code")
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
    prompt = d["arguments"]["message"]
    assert "e2e-harness-clarification" in prompt
    assert "clarification" in prompt


def test_opencode_descriptor_shape():
    d = runtime.spawn_worker(_packet(), runtime="opencode")
    assert d["schema"] == "e2e-dev-harness.worker-descriptor.v1"
    assert d["runtime"] == "opencode"
    assert d["tool"] == "task"
    assert d["arguments"]["subagent_type"] == "general-purpose"
    assert "description" in d["arguments"]
    assert "prompt" in d["arguments"]
    assert d["arguments"]["prompt"] == d["arguments"].get("prompt")
    assert d["context_paths"] == _packet()["context_paths"]
    assert d["expected_outputs"] == _packet()["expected_outputs"]


def test_opencode_prompt_mentions_skill_and_expected_outputs():
    d = runtime.spawn_worker(_packet(skill="e2e-harness-clarification"), runtime="opencode")
    prompt = d["arguments"]["prompt"]
    assert "e2e-harness-clarification" in prompt
    assert "clarification" in prompt


def test_opencode_env_override_sets_subagent_type(monkeypatch):
    monkeypatch.setenv("E2E_HARNESS_SUBAGENT_TYPE_CLARIFIER", "oc-clarifier")
    d = runtime.spawn_worker(_packet(role="clarifier"), runtime="opencode")
    assert d["arguments"]["subagent_type"] == "oc-clarifier"


def test_opencode_no_model_pin():
    # Regression guard: opencode seam must never pin a model (glm-4.7 breakage).
    d = runtime.spawn_worker(_packet(), runtime="opencode")
    assert not _has_model_key(d)


def test_manual_descriptor():
    d = runtime.spawn_worker(_packet(), runtime="manual")
    assert d["runtime"] == "manual"
    assert d["tool"] is None
    assert "instruction" in d and d["instruction"]
    assert d["expected_outputs"] == ["clarification"]


def test_unknown_runtime_falls_back_to_manual_with_warning():
    d = runtime.spawn_worker(_packet(), runtime="made-up-runtime")
    assert d["runtime"] == "manual"
    assert d.get("warning")
    assert "made-up-runtime" in d["warning"]
