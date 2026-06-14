import json

from e2e_harness.core import impact_bridge, engine, lifecycle


class _FakeProvider:
    name = "gitnexus"

    def __init__(self, result):
        self._result = result

    def assess(self, repo, request):
        return self._result


def _contract(tmp_path, seeds=("_phase_request",)):
    c = tmp_path / "acceptance-contract.json"
    c.write_text(json.dumps({
        "schema": "e2e-dev-harness.acceptance-contract.v1",
        "items": [{"id": "AC-001", "criterion": "c", "observable_behavior": "o"}],
        "impact_seed_candidates": list(seeds),
    }), encoding="utf-8")
    return c


def _state(tmp_path, mode, contract, tier="standard", request="change the planner module"):
    run_state_path = tmp_path / "run-state.json"
    return {
        "run_id": "r1", "request": request, "tier": tier,
        "impact": {"mode": mode},
        "_run_state_path": str(run_state_path),
        "phases": {"CLARIFIED": {"evidence": {"acceptance_contract": {"path": str(contract)}}}},
    }


def _verified_artifact():
    return {
        "schema": "e2e-dev-harness.impact-assessment.v1", "status": "verified", "tool": "gitnexus",
        "seeds": [{"kind": "symbol", "name": "_phase_request", "file_path": "x.py", "reason": "r"}],
        "impact": [{"seed": "_phase_request", "direction": "upstream", "risk": "LOW",
                    "summary": {}, "affected_processes": [{"name": "run"}], "affected_modules": []}],
        "open_questions": [], "degradation": None, "approval": None,
    }


def test_mode_off_is_noop(tmp_path):
    st = _state(tmp_path, "off", _contract(tmp_path))
    assert impact_bridge.ensure_assessment_for_planning(st, str(tmp_path)) is None
    assert "impact_assessment" not in st


def test_not_required_writes_not_applicable(tmp_path):
    # doc-only request, minimal tier, no seed candidates -> not required
    st = _state(tmp_path, "auto", _contract(tmp_path, seeds=[]),
                tier="minimal", request="update the documentation")
    decision = impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=_FakeProvider(None))
    assert decision is None
    assert st["impact_assessment"]["status"] == "not_applicable"
    assert st["impact_assessment"]["required"] is False
    assert (tmp_path / "impact-assessment.json").exists()


def test_verified_writes_binding_with_seeds(tmp_path):
    st = _state(tmp_path, "auto", _contract(tmp_path))
    decision = impact_bridge.ensure_assessment_for_planning(
        st, str(tmp_path), provider=_FakeProvider(_verified_artifact()))
    assert decision is None
    b = st["impact_assessment"]
    assert b["status"] == "verified" and b["required"] is True
    assert b["seeds"] == ["_phase_request"]
    assert b["risk"] == "LOW"
    assert b["contract_sha256"]


def test_blocked_returns_block_and_persists(tmp_path):
    blocked = {"schema": "e2e-dev-harness.impact-assessment.v1", "status": "blocked",
               "seeds": [], "impact": [],
               "open_questions": [{"id": "IQ-001", "question": "Which handler?", "status": "open"}]}
    st = _state(tmp_path, "strict", _contract(tmp_path))
    decision = impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=_FakeProvider(blocked))
    assert decision is not None and decision["status"] == "blocked"
    assert st["impact_assessment"]["status"] == "blocked"


def test_idempotent_on_contract_hash(tmp_path):
    st = _state(tmp_path, "auto", _contract(tmp_path))

    class _CountingProvider(_FakeProvider):
        calls = 0

        def assess(self, repo, request):
            _CountingProvider.calls += 1
            return _verified_artifact()

    prov = _CountingProvider(None)
    impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=prov)
    impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=prov)
    assert _CountingProvider.calls == 1   # second call served from binding cache


def test_amended_contract_invalidates_binding(tmp_path):
    contract = _contract(tmp_path)
    st = _state(tmp_path, "auto", contract)

    class _CountingProvider(_FakeProvider):
        calls = 0

        def assess(self, repo, request):
            _CountingProvider.calls += 1
            return _verified_artifact()

    prov = _CountingProvider(None)
    impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=prov)
    # amend the acceptance contract -> hash changes -> assessment must re-run
    contract.write_text(json.dumps({
        "schema": "e2e-dev-harness.acceptance-contract.v1",
        "items": [{"id": "AC-001", "criterion": "changed", "observable_behavior": "o"}],
        "impact_seed_candidates": ["_phase_request"],
    }), encoding="utf-8")
    impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=prov)
    assert _CountingProvider.calls == 2


# --- Degradation override: a recorded approval turns blocked -> degraded ---

def _blocked_artifact():
    return {"schema": "e2e-dev-harness.impact-assessment.v1", "status": "blocked",
            "seeds": [], "impact": [],
            "open_questions": [{"id": "IQ-001", "question": "GitNexus unavailable; approve "
                               "degradation or install it.", "status": "open"}]}


def test_blocked_with_approval_becomes_degraded(tmp_path):
    st = _state(tmp_path, "auto", _contract(tmp_path))
    st["approvals"] = {"impact_degradation": {"sha256": "deadbeef",
                                              "source": "user-approved", "reason": "no gitnexus"}}
    decision = impact_bridge.ensure_assessment_for_planning(
        st, str(tmp_path), provider=_FakeProvider(_blocked_artifact()))
    assert decision is None   # degraded -> proceed
    assert st["impact_assessment"]["status"] == "degraded"
    art = json.loads((tmp_path / "impact-assessment.json").read_text(encoding="utf-8"))
    assert art["status"] == "degraded"
    assert art["approval"]["sha256"] == "deadbeef"


def test_blocked_then_approval_reruns_to_degraded(tmp_path):
    st = _state(tmp_path, "auto", _contract(tmp_path))
    prov = _FakeProvider(_blocked_artifact())
    d1 = impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=prov)
    assert d1["status"] == "blocked"
    assert st["impact_assessment"]["status"] == "blocked"
    # coordinator records the approval; same contract, but now degradable
    st.setdefault("approvals", {})["impact_degradation"] = {
        "sha256": "abc", "source": "user-approved", "reason": "no gitnexus"}
    d2 = impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=prov)
    assert d2 is None
    assert st["impact_assessment"]["status"] == "degraded"


def test_strict_mode_blocks_instead_of_degrading(tmp_path):
    st = _state(tmp_path, "strict", _contract(tmp_path))
    st["approvals"] = {"impact_degradation": {"sha256": "abc",
                                              "source": "user-approved", "reason": "no gitnexus"}}
    decision = impact_bridge.ensure_assessment_for_planning(
        st, str(tmp_path), provider=_FakeProvider(_blocked_artifact()))
    assert decision == {"status": "blocked", "strict_mode_no_degrade": True}
    assert st["impact_assessment"]["status"] == "blocked"
    art = json.loads((tmp_path / "impact-assessment.json").read_text(encoding="utf-8"))
    assert art["status"] == "blocked"
    assert art.get("approval") is None


def test_revoked_degradation_approval_reruns_and_reblocks(tmp_path):
    st = _state(tmp_path, "auto", _contract(tmp_path))

    class _CountingBlockedProvider(_FakeProvider):
        calls = 0

        def assess(self, repo, request):
            _CountingBlockedProvider.calls += 1
            return _blocked_artifact()

    prov = _CountingBlockedProvider(None)
    st["approvals"] = {"impact_degradation": {"sha256": "abc",
                                              "source": "user-approved", "reason": "no gitnexus"}}
    assert impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=prov) is None
    assert st["impact_assessment"]["status"] == "degraded"

    del st["approvals"]["impact_degradation"]
    decision = impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=prov)
    assert decision == {"status": "blocked"}
    assert st["impact_assessment"]["status"] == "blocked"
    assert _CountingBlockedProvider.calls == 2


def test_impact_artifact_write_leaves_no_partial_tmp(tmp_path):
    st = _state(tmp_path, "auto", _contract(tmp_path))
    impact_bridge.ensure_assessment_for_planning(
        st, str(tmp_path), provider=_FakeProvider(_verified_artifact()))
    assert (tmp_path / "impact-assessment.json").exists()
    assert [p.name for p in tmp_path.glob("impact-assessment.json.*.tmp")] == []


# --- Task 3a.2: engine seam ---

def _spine():
    return lifecycle.build_spine(
        ["CLARIFIED", "PLANNED", "RED", "IMPLEMENTED", "REVIEWED", "VERIFIED"])


def _passing_clarified(tmp_path, contract):
    # CLARIFIED gate passes: clarification (non-empty) + a valid acceptance_contract.
    clar = tmp_path / "clarification.md"
    clar.write_text("done", encoding="utf-8")
    return {"evidence": {"clarification": {"path": str(clar)},
                         "acceptance_contract": {"path": str(contract)}}}


def _valid_contract(tmp_path):
    c = tmp_path / "acceptance-contract.json"
    c.write_text(json.dumps({
        "schema": "e2e-dev-harness.acceptance-contract.v1",
        "items": [{"id": "AC-001", "criterion": "c", "observable_behavior": "o"}],
        "impact_seed_candidates": ["_phase_request"],
    }), encoding="utf-8")
    return c


def test_engine_blocks_at_clarified_on_blocked_impact(tmp_path, monkeypatch):
    def _fake(state, repo_root, **kw):
        state["impact_assessment"] = {"schema": "e2e-dev-harness.impact-binding.v1",
                                      "status": "blocked", "required": True,
                                      "path": "impact-assessment.json"}
        return {"status": "blocked"}

    monkeypatch.setattr(
        "e2e_harness.core.impact_bridge.ensure_assessment_for_planning", _fake)

    contract = _valid_contract(tmp_path)
    rsp = tmp_path / "run-state.json"
    state = {"run_id": "r1", "request": "change planner", "tier": "standard",
             "impact": {"mode": "strict"}, "current_phase": "PLANNED",
             "_run_state_path": str(rsp),
             "phases": {"CLARIFIED": _passing_clarified(tmp_path, contract)}}
    res = engine.evaluate(_spine(), state, str(tmp_path))
    assert res["blocked_phase"] == "CLARIFIED"
    assert state["current_phase"] == "CLARIFIED"


def test_engine_proceeds_to_planned_when_impact_ok(tmp_path, monkeypatch):
    # bridge returns None (proceed) -> normal PLANNED block for missing plan/module_plan.
    monkeypatch.setattr(
        "e2e_harness.core.impact_bridge.ensure_assessment_for_planning",
        lambda state, repo_root, **kw: None)

    contract = _valid_contract(tmp_path)
    rsp = tmp_path / "run-state.json"
    state = {"run_id": "r1", "request": "change planner", "tier": "standard",
             "impact": {"mode": "strict"}, "current_phase": "CLARIFIED",
             "_run_state_path": str(rsp),
             "phases": {"CLARIFIED": _passing_clarified(tmp_path, contract)}}
    res = engine.evaluate(_spine(), state, str(tmp_path))
    assert res["blocked_phase"] == "PLANNED"


# --- Slice 3b: re-clarify merge ---

def test_pending_merges_impact_iq_questions(tmp_path):
    from e2e_harness.adapters.evidence import clarification
    contract = tmp_path / "acceptance-contract.json"
    contract.write_text(json.dumps({
        "schema": "e2e-dev-harness.acceptance-contract.v1",
        "items": [{"id": "AC-001", "criterion": "c", "observable_behavior": "o"}],
        "open_questions": [{"id": "OQ-001", "question": "Scope?", "status": "open"}],
    }), encoding="utf-8")
    art = tmp_path / "impact-assessment.json"
    art.write_text(json.dumps({
        "schema": "e2e-dev-harness.impact-assessment.v1", "status": "blocked",
        "seeds": [], "impact": [],
        "open_questions": [{"id": "IQ-001", "question": "Which handler?", "status": "open"}],
    }), encoding="utf-8")
    state = {"_run_state_path": str(tmp_path / "run-state.json"),
             "impact_assessment": {"status": "blocked", "path": "impact-assessment.json"},
             "phases": {"CLARIFIED": {"evidence": {"acceptance_contract": {"path": str(contract)}}}}}
    pending = clarification.pending_from_state(state, str(tmp_path))
    ids = {q["id"] for q in pending}
    assert {"OQ-001", "IQ-001"} <= ids


def test_pending_no_impact_binding_unchanged(tmp_path):
    from e2e_harness.adapters.evidence import clarification
    contract = tmp_path / "acceptance-contract.json"
    contract.write_text(json.dumps({
        "schema": "e2e-dev-harness.acceptance-contract.v1",
        "items": [{"id": "AC-001", "criterion": "c", "observable_behavior": "o"}],
        "open_questions": [{"id": "OQ-001", "question": "Scope?", "status": "open"}],
    }), encoding="utf-8")
    state = {"phases": {"CLARIFIED": {"evidence": {"acceptance_contract": {"path": str(contract)}}}}}
    pending = clarification.pending_from_state(state, str(tmp_path))
    assert [q["id"] for q in pending] == ["OQ-001"]


def test_blocked_binding_marks_degradation_available_in_auto(tmp_path):
    st = _state(tmp_path, "auto", _contract(tmp_path))
    impact_bridge.ensure_assessment_for_planning(
        st, str(tmp_path), provider=_FakeProvider(_blocked_artifact()))
    assert st["impact_assessment"]["status"] == "blocked"
    assert st["impact_assessment"]["degradation_available"] is True


def test_blocked_binding_marks_no_degradation_in_strict(tmp_path):
    st = _state(tmp_path, "strict", _contract(tmp_path))
    impact_bridge.ensure_assessment_for_planning(
        st, str(tmp_path), provider=_FakeProvider(_blocked_artifact()))
    assert st["impact_assessment"]["status"] == "blocked"
    assert st["impact_assessment"]["degradation_available"] is False
