"""VERIFIED-phase scope manifest: repo grounding + honest PARTIAL (link ②).

A delivered-scope claim is grounded against the repo (a declared delivered table
must actually have a CREATE TABLE), so a worker cannot claim COMPLETE while the
jeepay-style "no DDL, no service change" subset was shipped. A truthful PARTIAL
is allowed through and recorded; a COMPLETE that overclaims is rejected.
"""
import json

from e2e_harness.adapters.evidence import scope as scope_ev
from e2e_harness.core import scope as scope_core


def _manifest(expected, delivered, status):
    return {"schema": scope_core.SCHEMA, "status": status,
            "expected": expected, "delivered": delivered}


def _scope(services=(), tables=(), phases=()):
    return {"services": list(services), "tables": list(tables), "phases": list(phases)}


def test_complete_with_grounded_table_passes(tmp_path):
    (tmp_path / "schema.sql").write_text("CREATE TABLE t_risk (id INT);", encoding="utf-8")
    man = _manifest(_scope(services=["payment"], tables=["t_risk"]),
                    _scope(services=["payment"], tables=["t_risk"]), "COMPLETE")
    ok, reason = scope_ev.validate_scope_manifest(man, tmp_path)
    assert ok is True and reason is None


def test_complete_overclaim_when_table_has_no_ddl_is_rejected(tmp_path):
    # delivered claims t_risk but there is no CREATE TABLE anywhere -> ungrounded
    man = _manifest(_scope(tables=["t_risk"]), _scope(tables=["t_risk"]), "COMPLETE")
    ok, reason = scope_ev.validate_scope_manifest(man, tmp_path)
    assert ok is False and reason.startswith("overclaims-complete:")


def test_honest_partial_is_allowed(tmp_path):
    man = _manifest(_scope(services=["payment", "merchant"]),
                    _scope(services=["payment"]), "PARTIAL")
    ok, reason = scope_ev.validate_scope_manifest(man, tmp_path)
    assert ok is True and reason is None


def test_complete_claim_on_subset_is_rejected(tmp_path):
    man = _manifest(_scope(services=["payment", "merchant"]),
                    _scope(services=["payment"]), "COMPLETE")
    ok, reason = scope_ev.validate_scope_manifest(man, tmp_path)
    assert ok is False and reason.startswith("overclaims-complete:")


def test_structural_rejection(tmp_path):
    ok, reason = scope_ev.validate_scope_manifest({"schema": "wrong"}, tmp_path)
    assert ok is False and reason == "bad-schema"


def test_label_delivery_reads_verified_evidence(tmp_path):
    (tmp_path / "schema.sql").write_text("create table t_risk(id int);", encoding="utf-8")
    man = _manifest(_scope(services=["payment", "merchant"], tables=["t_risk"]),
                    _scope(services=["payment"], tables=["t_risk"]), "PARTIAL")
    p = tmp_path / "scope.json"
    p.write_text(json.dumps(man), encoding="utf-8")
    state = {"phases": {"VERIFIED": {"evidence": {"scope_manifest": {"path": "scope.json"}}}}}

    status, undelivered = scope_ev.label_delivery(state, tmp_path)

    assert status == "PARTIAL"
    assert undelivered["services"] == ["merchant"]
