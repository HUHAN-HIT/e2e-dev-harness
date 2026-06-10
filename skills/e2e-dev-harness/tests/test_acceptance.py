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
