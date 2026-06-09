import json
from pathlib import Path

from e2e_harness.adapters.hooks import stop_guard as sg
from e2e_harness.core import run_state


def _write_state(tmp_path, current_phase):
    state = run_state.new_run_state("r1", "demo", "do x")
    state["current_phase"] = current_phase
    sp = tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json"
    run_state.save(sp, state)
    return sp


def test_unverified_active_run_blocks(tmp_path):
    sp = _write_state(tmp_path, "RED")
    d = sg.decide(sp)
    assert d["decision"] == "block"
    assert "RED" in d["reason"]


def test_verified_allows_stop(tmp_path):
    sp = _write_state(tmp_path, "VERIFIED")
    assert sg.decide(sp)["decision"] == "allow"


def test_no_run_state_allows_stop(tmp_path):
    assert sg.decide(None)["decision"] == "allow"
    assert sg.decide(tmp_path / "missing.json")["decision"] == "allow"


def test_unreadable_run_state_allows_stop(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert sg.decide(bad)["decision"] == "allow"


def test_emit_block_protocol(capsys):
    sg._emit({"decision": "block", "reason": "go on"})
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "block" and out["reason"] == "go on"


def test_emit_allow_is_empty(capsys):
    sg._emit({"decision": "allow", "reason": ""})
    assert json.loads(capsys.readouterr().out) == {}
