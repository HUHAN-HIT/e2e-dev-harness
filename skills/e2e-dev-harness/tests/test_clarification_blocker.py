"""A3: the re-clarify loop surfaces *which* questions block CLARIFIED.

A2 makes the gate block while any open question remains; A3 makes `next` tell
the user exactly which questions are pending so the loop is actionable rather
than an opaque "acceptance_contract missing". No engine-core change: the blocker
is derived from the contract evidence at the CLI seam.
"""
import json
import types

from e2e_harness.core import acceptance, run_state
from e2e_harness.adapters.evidence import clarification
from e2e_harness.cli.commands import next as next_cmd


def _clarified_state(repo, *open_qs):
    c = {"schema": acceptance.SCHEMA,
         "items": [{"id": "AC-001", "criterion": "c", "observable_behavior": "o"}],
         "open_questions": list(open_qs)}
    docs = repo / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "acc.json").write_text(json.dumps(c), encoding="utf-8")
    (docs / "clar.md").write_text("# handoff\n", encoding="utf-8")
    state = run_state.new_run_state("r1", "f", "r")
    state["current_phase"] = "CLARIFIED"
    state["phases"] = {"CLARIFIED": {"evidence": {
        "clarification": {"path": "docs/clar.md"},
        "acceptance_contract": {"path": "docs/acc.json"}}}}
    return state


def test_pending_from_state_lists_open_questions(tmp_path):
    state = _clarified_state(tmp_path, {"id": "OQ-001", "question": "which db?", "status": "open"})
    assert clarification.pending_from_state(state, tmp_path) == [{"id": "OQ-001", "question": "which db?"}]


def test_pending_from_state_empty_when_all_resolved(tmp_path):
    state = _clarified_state(tmp_path, {"id": "OQ-001", "question": "q", "status": "resolved",
                                        "resolution": "postgres"})
    assert clarification.pending_from_state(state, tmp_path) == []


def test_pending_from_state_empty_when_no_contract(tmp_path):
    state = run_state.new_run_state("r1", "f", "r")
    assert clarification.pending_from_state(state, tmp_path) == []


def test_next_surfaces_open_questions_blocker(tmp_path):
    state = _clarified_state(tmp_path, {"id": "OQ-001", "question": "which db?", "status": "open"})
    statefile = tmp_path / "run.json"
    run_state.save(statefile, state)
    args = types.SimpleNamespace(repo=str(tmp_path), state=str(statefile))
    code, res = next_cmd.run(args)
    assert code == 0
    assert res["blocked_phase"] == "CLARIFIED"
    assert res["open_questions"] == [{"id": "OQ-001", "question": "which db?"}]
    assert "OQ-001" in res["blocker"]


def test_next_no_open_questions_blocker_when_resolved(tmp_path):
    state = _clarified_state(tmp_path, {"id": "OQ-001", "question": "q", "status": "resolved",
                                        "resolution": "postgres"})
    statefile = tmp_path / "run.json"
    run_state.save(statefile, state)
    args = types.SimpleNamespace(repo=str(tmp_path), state=str(statefile))
    code, res = next_cmd.run(args)
    # contract resolved -> CLARIFIED passes -> advances past it, no open_questions key
    assert "open_questions" not in res
