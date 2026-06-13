"""Acceptance-contract well-formedness (Phase 0 link ①, requirements fidelity).

The contract turns prose acceptance criteria into machine-checkable items so a
later phase's tests and gates can reference each one by id. validate_contract is
pure: structure in, (ok, reason) out — no I/O.
"""
from e2e_harness.core import acceptance


def _item(i=1, **over):
    base = {"id": f"AC-{i:03d}", "criterion": f"criterion {i}",
            "observable_behavior": f"observable {i}"}
    base.update(over)
    return base


def _contract(*items):
    return {"schema": acceptance.SCHEMA, "items": list(items) or [_item()]}


def test_wellformed_contract_passes():
    ok, reason = acceptance.validate_contract(_contract(_item(1), _item(2)))
    assert ok is True
    assert reason is None


def test_non_object_is_rejected():
    ok, reason = acceptance.validate_contract(["not", "a", "dict"])
    assert ok is False
    assert reason == "not-object"


def test_wrong_schema_is_rejected():
    bad = _contract()
    bad["schema"] = "something-else"
    ok, reason = acceptance.validate_contract(bad)
    assert ok is False
    assert reason == "bad-schema"


def test_empty_items_is_rejected():
    ok, reason = acceptance.validate_contract({"schema": acceptance.SCHEMA, "items": []})
    assert ok is False
    assert reason == "no-items"


def test_items_must_be_a_list():
    ok, reason = acceptance.validate_contract({"schema": acceptance.SCHEMA, "items": {}})
    assert ok is False
    assert reason == "no-items"


def test_bad_id_format_is_rejected():
    ok, reason = acceptance.validate_contract(_contract(_item(1, id="X1")))
    assert ok is False
    assert reason.startswith("bad-id")


def test_duplicate_ids_are_rejected():
    ok, reason = acceptance.validate_contract(_contract(_item(1), _item(1)))
    assert ok is False
    assert reason == "duplicate-id:AC-001"


def test_empty_criterion_is_rejected():
    ok, reason = acceptance.validate_contract(_contract(_item(1, criterion="  ")))
    assert ok is False
    assert reason == "empty-criterion:AC-001"


def test_missing_observable_behavior_is_rejected():
    item = _item(1)
    del item["observable_behavior"]
    ok, reason = acceptance.validate_contract(_contract(item))
    assert ok is False
    assert reason == "empty-observable:AC-001"


def test_ids_returns_ordered_unique_ids():
    contract = _contract(_item(2), _item(1))
    assert acceptance.ids(contract) == ["AC-002", "AC-001"]


# --- gate wiring: validate_evidence must structurally check the contract key ---
import json

from e2e_harness.adapters.evidence import validate


def _write(repo, name, obj):
    p = repo / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p.relative_to(repo))


def test_validate_evidence_accepts_wellformed_contract(tmp_path):
    rel = _write(tmp_path, "acceptance.json", _contract(_item(1)))
    ok, reason = validate.validate_evidence(tmp_path, "acceptance_contract", rel)
    assert ok is True
    assert reason is None


def test_validate_evidence_rejects_malformed_contract(tmp_path):
    rel = _write(tmp_path, "acceptance.json", {"schema": acceptance.SCHEMA, "items": []})
    ok, reason = validate.validate_evidence(tmp_path, "acceptance_contract", rel)
    assert ok is False
    assert reason == "no-items"


def test_validate_evidence_rejects_non_json_contract(tmp_path):
    p = tmp_path / "acceptance.md"
    p.write_text("# not json\n", encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "acceptance_contract", str(p.relative_to(tmp_path)))
    assert ok is False
    assert reason == "not-json"


# --- v2 open_questions: clarification-to-resolution (link ①, fix A1) ------------
# A contract may now carry an `open_questions[]` ledger. validate_contract checks
# its structure when present (back-compat: absent == no open questions).
# `unresolved_questions` is the pure gate signal: ids still in status "open".


def _oq(i=1, **over):
    base = {"id": f"OQ-{i:03d}", "question": f"question {i}", "status": "resolved",
            "resolution": f"resolution {i}"}
    base.update(over)
    return base


def test_open_questions_absent_is_valid():
    ok, reason = acceptance.validate_contract(_contract(_item(1)))
    assert ok is True and reason is None


def test_open_questions_wellformed_passes():
    c = _contract(_item(1))
    c["open_questions"] = [_oq(1), _oq(2, status="deferred", resolution="user deferred to v2")]
    ok, reason = acceptance.validate_contract(c)
    assert ok is True and reason is None


def test_open_questions_must_be_a_list():
    c = _contract(_item(1))
    c["open_questions"] = {"OQ-001": "?"}
    ok, reason = acceptance.validate_contract(c)
    assert ok is False and reason == "bad-open-questions"


def test_open_question_bad_id_rejected():
    c = _contract(_item(1))
    c["open_questions"] = [_oq(1, id="Q1")]
    ok, reason = acceptance.validate_contract(c)
    assert ok is False and reason == "bad-oq-id:'Q1'"


def test_open_question_duplicate_id_rejected():
    c = _contract(_item(1))
    c["open_questions"] = [_oq(1), _oq(1)]
    ok, reason = acceptance.validate_contract(c)
    assert ok is False and reason == "duplicate-oq-id:OQ-001"


def test_open_question_empty_question_rejected():
    c = _contract(_item(1))
    c["open_questions"] = [_oq(1, question="  ")]
    ok, reason = acceptance.validate_contract(c)
    assert ok is False and reason == "empty-oq-question:OQ-001"


def test_open_question_bad_status_rejected():
    c = _contract(_item(1))
    c["open_questions"] = [_oq(1, status="maybe")]
    ok, reason = acceptance.validate_contract(c)
    assert ok is False and reason == "bad-oq-status:OQ-001"


def test_open_question_open_status_needs_no_resolution():
    c = _contract(_item(1))
    c["open_questions"] = [{"id": "OQ-001", "question": "still open?", "status": "open"}]
    ok, reason = acceptance.validate_contract(c)
    assert ok is True and reason is None


def test_resolved_status_requires_resolution():
    c = _contract(_item(1))
    c["open_questions"] = [{"id": "OQ-001", "question": "q", "status": "resolved"}]
    ok, reason = acceptance.validate_contract(c)
    assert ok is False and reason == "missing-oq-resolution:OQ-001"


def test_deferred_status_requires_resolution():
    c = _contract(_item(1))
    c["open_questions"] = [{"id": "OQ-001", "question": "q", "status": "deferred", "resolution": "  "}]
    ok, reason = acceptance.validate_contract(c)
    assert ok is False and reason == "missing-oq-resolution:OQ-001"


def test_unresolved_questions_lists_open_ids_in_order():
    c = _contract(_item(1))
    c["open_questions"] = [
        _oq(1),  # resolved
        {"id": "OQ-002", "question": "a", "status": "open"},
        {"id": "OQ-003", "question": "b", "status": "open"},
        _oq(4, status="deferred", resolution="later"),
    ]
    assert acceptance.unresolved_questions(c) == ["OQ-002", "OQ-003"]


def test_unresolved_questions_empty_when_all_resolved():
    c = _contract(_item(1))
    c["open_questions"] = [_oq(1), _oq(2, status="deferred", resolution="x")]
    assert acceptance.unresolved_questions(c) == []


def test_unresolved_questions_empty_when_field_absent():
    assert acceptance.unresolved_questions(_contract(_item(1))) == []


# --- A2: CLARIFIED gate blocks until every open question is resolved -------------

from e2e_harness.core import gates, lifecycle


def test_validate_evidence_rejects_contract_with_open_question(tmp_path):
    c = _contract(_item(1))
    c["open_questions"] = [{"id": "OQ-001", "question": "which db?", "status": "open"}]
    rel = _write(tmp_path, "acceptance.json", c)
    ok, reason = validate.validate_evidence(tmp_path, "acceptance_contract", rel)
    assert ok is False
    assert reason == "open-questions:OQ-001"


def test_validate_evidence_lists_all_open_question_ids(tmp_path):
    c = _contract(_item(1))
    c["open_questions"] = [
        {"id": "OQ-001", "question": "a", "status": "open"},
        _oq(2),  # resolved
        {"id": "OQ-003", "question": "b", "status": "open"},
    ]
    rel = _write(tmp_path, "acceptance.json", c)
    ok, reason = validate.validate_evidence(tmp_path, "acceptance_contract", rel)
    assert ok is False
    assert reason == "open-questions:OQ-001,OQ-003"


def test_validate_evidence_accepts_contract_with_all_questions_resolved(tmp_path):
    c = _contract(_item(1))
    c["open_questions"] = [_oq(1), _oq(2, status="deferred", resolution="later")]
    rel = _write(tmp_path, "acceptance.json", c)
    ok, reason = validate.validate_evidence(tmp_path, "acceptance_contract", rel)
    assert ok is True and reason is None


def test_clarified_gate_blocks_on_open_question(tmp_path):
    c = _contract(_item(1))
    c["open_questions"] = [{"id": "OQ-001", "question": "?", "status": "open"}]
    acc = _write(tmp_path, "acceptance.json", c)
    clar = _write(tmp_path, "clar.md", {"summary": "x"})
    phase = lifecycle.catalog()["CLARIFIED"]
    rec = {"evidence": {"clarification": {"path": clar},
                        "acceptance_contract": {"path": acc}}}
    ok, missing = gates.gate_passes(phase, rec, tmp_path)
    assert ok is False
    assert "acceptance_contract" in missing


def test_clarified_gate_passes_when_questions_resolved(tmp_path):
    c = _contract(_item(1))
    c["open_questions"] = [_oq(1)]
    acc = _write(tmp_path, "acceptance.json", c)
    clar = _write(tmp_path, "clar.md", {"summary": "x"})
    phase = lifecycle.catalog()["CLARIFIED"]
    rec = {"evidence": {"clarification": {"path": clar},
                        "acceptance_contract": {"path": acc}}}
    ok, missing = gates.gate_passes(phase, rec, tmp_path)
    assert ok is True and missing == []


# --- A3: human-facing pending questions for the re-clarify loop ------------------


def test_pending_questions_returns_id_and_text_for_open():
    c = _contract(_item(1))
    c["open_questions"] = [
        {"id": "OQ-001", "question": "which db?", "status": "open"},
        _oq(2),
        {"id": "OQ-003", "question": "auth model?", "status": "open"},
    ]
    assert acceptance.pending_questions(c) == [
        {"id": "OQ-001", "question": "which db?"},
        {"id": "OQ-003", "question": "auth model?"},
    ]


def test_pending_questions_empty_when_none_open():
    c = _contract(_item(1))
    c["open_questions"] = [_oq(1)]
    assert acceptance.pending_questions(c) == []
