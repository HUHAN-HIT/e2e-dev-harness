"""Scope manifest model (Phase 0 link ②, scope fidelity).

Design scope (services/tables/phases) must equal delivered scope, or the run is
PARTIAL — never silently VERIFIED on a subset (the jeepay failure: an 80-file
design delivered as a Phase-1 skeleton yet marked VERIFIED). Pure model here;
repo grounding + run-state labelling live in adapters/evidence/scope.py.
"""
from e2e_harness.core import scope


def _m(expected, delivered, status="COMPLETE"):
    return {"schema": scope.SCHEMA, "status": status,
            "expected": expected, "delivered": delivered}


FULL = {"services": ["payment", "merchant"], "tables": ["t_risk"], "phases": ["P1"]}


def test_wellformed_manifest_passes():
    ok, reason = scope.validate_manifest(_m(FULL, FULL))
    assert ok is True and reason is None


def test_non_object_rejected():
    ok, reason = scope.validate_manifest([])
    assert ok is False and reason == "not-object"


def test_bad_schema_rejected():
    m = _m(FULL, FULL); m["schema"] = "x"
    ok, reason = scope.validate_manifest(m)
    assert ok is False and reason == "bad-schema"


def test_missing_category_rejected():
    bad = {"services": ["a"], "tables": ["t"]}  # no phases
    ok, reason = scope.validate_manifest(_m(bad, bad))
    assert ok is False and reason.startswith("bad-expected") or reason.startswith("bad-scope")


def test_assess_complete_when_delivered_covers_expected():
    status, undelivered = scope.assess(FULL, FULL)
    assert status == "COMPLETE"
    assert undelivered == {"services": [], "tables": [], "phases": []}


def test_assess_partial_lists_undelivered_per_category():
    delivered = {"services": ["payment"], "tables": [], "phases": ["P1"]}
    status, undelivered = scope.assess(FULL, delivered)
    assert status == "PARTIAL"
    assert undelivered["services"] == ["merchant"]
    assert undelivered["tables"] == ["t_risk"]
    assert undelivered["phases"] == []
