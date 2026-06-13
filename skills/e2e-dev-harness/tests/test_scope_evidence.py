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


def _module_state(tmp_path, expected_phases, delivered_phases):
    """Build a `complete` 2-module (auth, billing) run-state + scope manifest on
    disk. Uses the `standard` pipeline (has RED/IMPLEMENTED/REVIEWED) for BOTH the
    fixture spine and label_delivery's internal spine_for_state, so the test truly
    exercises REVIEWED#<id> chain-completion grounding (the default `minimal`
    pipeline has no REVIEWED and would not)."""
    from e2e_harness import pipeline
    from e2e_harness.core import multitrack, module_plan

    mplan = {"schema": module_plan.SCHEMA, "modules": [
        {"id": "auth", "name": "auth", "depends_on": [], "acceptance_ids": ["AC-001"]},
        {"id": "billing", "name": "billing", "depends_on": [], "acceptance_ids": ["AC-002"]},
    ]}
    (tmp_path / "module-plan.json").write_text(json.dumps(mplan), encoding="utf-8")

    state = {"pipeline": "standard",
             "phases": {"PLANNED": {"evidence": {"module_plan": {"path": "module-plan.json"}}}}}
    spine = multitrack.expand(pipeline.build_spine("standard"), mplan)
    by = {p.name: p for p in spine}

    def _complete(*names):
        for n in names:
            state["phases"][n] = {"evidence": {k: {"path": "x"} for k in by[n].exit_gate}}

    # Both modules finished — the only state in which a run is `complete`.
    _complete("RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth",
              "RED#billing", "IMPLEMENTED#billing", "REVIEWED#billing")

    man = {"schema": scope_core.SCHEMA, "status": "PARTIAL",
           "expected":  {"services": [], "tables": [], "phases": list(expected_phases)},
           "delivered": {"services": [], "tables": [], "phases": list(delivered_phases)}}
    (tmp_path / "scope.json").write_text(json.dumps(man), encoding="utf-8")
    state["phases"]["VERIFIED"] = {"evidence": {"scope_manifest": {"path": "scope.json"}}}
    return state


def test_label_delivery_grounds_phases_against_completed_modules(tmp_path):
    # Manifest overclaims a third phase `reporting` that was never a module.
    state = _module_state(tmp_path,
                          expected_phases=["auth", "billing", "reporting"],
                          delivered_phases=["auth", "billing", "reporting"])
    status, undelivered = scope_ev.label_delivery(state, tmp_path)
    assert status == "PARTIAL"
    assert undelivered["phases"] == ["reporting"]   # ungrounded: never a completed module


def test_label_delivery_keeps_genuinely_completed_modules(tmp_path):
    # Both delivered phases ARE completed modules -> grounding must not strip them.
    state = _module_state(tmp_path,
                          expected_phases=["auth", "billing"],
                          delivered_phases=["auth", "billing"])
    status, undelivered = scope_ev.label_delivery(state, tmp_path)
    assert status == "COMPLETE"
    assert undelivered["phases"] == []
