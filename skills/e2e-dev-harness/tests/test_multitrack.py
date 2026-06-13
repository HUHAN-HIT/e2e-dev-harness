"""Multi-track spine expansion (取向②, fix B2).

When PLANNED emits a module plan with >=2 modules, the per-module dev band
(RED -> IMPLEMENTED -> REVIEWED) expands into one full lifecycle per module,
chained in dependency (topological) order, with VERIFIED integrating at the end.
A single-module plan is just the existing single track (no expansion), so simple
runs are unchanged.

expand() is pure: (base_spine, module_plan) -> expanded spine. No I/O.
"""
from e2e_harness import pipeline
from e2e_harness.core import multitrack, module_plan, gates


def _plan(*mods):
    return {"schema": module_plan.SCHEMA, "modules": list(mods)}


def _mod(mid, deps=()):
    return {"id": mid, "name": f"{mid} svc", "depends_on": list(deps), "acceptance_ids": ["AC-001"]}


def _names(spine):
    return [p.name for p in spine]


def test_single_module_leaves_spine_unchanged():
    base = pipeline.build_spine("standard")
    out = multitrack.expand(base, _plan(_mod("core")))
    assert _names(out) == _names(base)


def test_no_modules_scoped_band_returns_base():
    # minimal has no PLANNED/REVIEWED but does have RED/IMPLEMENTED; still, with a
    # single module it must be untouched.
    base = pipeline.build_spine("minimal")
    out = multitrack.expand(base, _plan(_mod("core")))
    assert _names(out) == _names(base)


def test_two_modules_expand_per_module_lifecycle():
    base = pipeline.build_spine("standard")
    out = multitrack.expand(base, _plan(_mod("auth"), _mod("billing", deps=["auth"])))
    assert _names(out) == [
        "CREATED", "CLARIFIED", "PLANNED",
        "RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth",
        "RED#billing", "IMPLEMENTED#billing", "REVIEWED#billing",
        "VERIFIED",
    ]


def test_expansion_follows_topological_order_not_declared():
    base = pipeline.build_spine("standard")
    # declared billing-first, but billing depends on auth -> auth block first
    out = multitrack.expand(base, _plan(_mod("billing", deps=["auth"]), _mod("auth")))
    assert _names(out)[3:9] == [
        "RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth",
        "RED#billing", "IMPLEMENTED#billing", "REVIEWED#billing",
    ]


def test_next_phase_chaining_is_linear_across_blocks():
    base = pipeline.build_spine("standard")
    out = multitrack.expand(base, _plan(_mod("auth"), _mod("billing", deps=["auth"])))
    nxt = {p.name: p.next_phase for p in out}
    assert nxt["PLANNED"] == "RED#auth"
    assert nxt["REVIEWED#auth"] == "RED#billing"
    assert nxt["REVIEWED#billing"] == "VERIFIED"
    assert nxt["VERIFIED"] is None


def test_evidence_keys_are_namespaced_per_module():
    base = pipeline.build_spine("standard")
    out = multitrack.expand(base, _plan(_mod("auth"), _mod("billing")))
    by_name = {p.name: p for p in out}
    assert by_name["IMPLEMENTED#auth"].produces == ("passing_tests#auth", "test_substance#auth")
    assert by_name["IMPLEMENTED#auth"].exit_gate == ("passing_tests#auth", "test_substance#auth")
    assert by_name["RED#billing"].produces == ("failing_tests#billing",)


def test_allows_code_write_is_preserved_per_module():
    base = pipeline.build_spine("standard")
    out = multitrack.expand(base, _plan(_mod("auth"), _mod("billing")))
    by_name = {p.name: p for p in out}
    assert by_name["IMPLEMENTED#auth"].allows_code_write is True
    assert by_name["RED#auth"].allows_code_write is False
    assert by_name["REVIEWED#billing"].allows_code_write is False


def test_worker_role_and_skill_preserved():
    base = pipeline.build_spine("standard")
    out = multitrack.expand(base, _plan(_mod("auth"), _mod("billing")))
    red_auth = next(p for p in out if p.name == "RED#auth")
    assert red_auth.worker_role == "tdd-red"
    assert red_auth.worker_skill == "e2e-harness-tdd-red"


def test_expanded_spine_is_gate_closed():
    base = pipeline.build_spine("standard")
    out = multitrack.expand(base, _plan(_mod("auth"), _mod("billing", deps=["auth"])))
    ok, unmet = gates.gate_closure_ok(out)
    assert ok is True, f"expanded spine not gate-closed: {unmet}"


def test_base_phase_and_module_of_helpers():
    assert multitrack.base_phase_name("IMPLEMENTED#auth") == "IMPLEMENTED"
    assert multitrack.base_phase_name("VERIFIED") == "VERIFIED"
    assert multitrack.module_of("IMPLEMENTED#auth") == "auth"
    assert multitrack.module_of("VERIFIED") is None
    assert multitrack.base_key("passing_tests#auth") == "passing_tests"
    assert multitrack.base_key("passing_tests") == "passing_tests"


# --- B2.2: evidence validation must normalize namespaced keys -------------------

import json

from e2e_harness.adapters.evidence import validate


def test_validate_evidence_normalizes_namespaced_structured_key(tmp_path):
    p = tmp_path / "acc.json"
    p.write_text(json.dumps({"schema": "e2e-dev-harness.acceptance-contract.v1", "items": []}),
                 encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "acceptance_contract#auth",
                                            str(p.relative_to(tmp_path)))
    assert ok is False and reason == "no-items"  # base structural validator ran


def test_validate_evidence_normalizes_namespaced_command_key(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("real", encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "passing_tests#auth",
                                            str(p.relative_to(tmp_path)))
    assert ok is False and reason == "not-json"  # base command-key path engaged


# --- B2.3: spine_for_state expansion + can_write_code namespace awareness --------

from e2e_harness.core import run_state


def _state_with_plan(repo, *mods):
    plan = {"schema": module_plan.SCHEMA, "modules": list(mods)}
    (repo / "mp.json").write_text(json.dumps(plan), encoding="utf-8")
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    st["phases"] = {"PLANNED": {"evidence": {"module_plan": {"path": "mp.json"}}}}
    return st


def test_spine_for_state_expands_with_two_modules(tmp_path):
    st = _state_with_plan(tmp_path, _mod("auth"), _mod("billing", deps=["auth"]))
    spine = pipeline.spine_for_state(st, tmp_path)
    names = _names(spine)
    assert "RED#auth" in names and "REVIEWED#billing" in names


def test_spine_for_state_single_module_not_expanded(tmp_path):
    st = _state_with_plan(tmp_path, _mod("core"))
    spine = pipeline.spine_for_state(st, tmp_path)
    assert _names(spine) == _names(pipeline.build_spine("standard"))


def test_spine_for_state_without_repo_is_base(tmp_path):
    st = _state_with_plan(tmp_path, _mod("auth"), _mod("billing"))
    assert _names(pipeline.spine_for_state(st)) == _names(pipeline.build_spine("standard"))


def test_can_write_code_true_for_module_implemented():
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    st["current_phase"] = "IMPLEMENTED#auth"
    assert pipeline.can_write_code(st) is True


def test_can_write_code_false_for_module_red():
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    st["current_phase"] = "RED#auth"
    assert pipeline.can_write_code(st) is False


# --- B3: ready module frontier (the parallelism mechanism) ----------------------


def _expanded(*mods):
    base = pipeline.build_spine("standard")
    mplan = _plan(*mods)
    return multitrack.expand(base, mplan), mplan


def _mark(st, spine, *phase_names):
    by = {p.name: p for p in spine}
    for name in phase_names:
        st.setdefault("phases", {})[name] = {"evidence": {k: {"path": "x"} for k in by[name].exit_gate}}
    return st


def _front_names(spine, st, mplan):
    return [p.name for p in multitrack.ready_frontier(spine, st, mplan)]


def test_frontier_independent_modules_start_in_parallel():
    spine, mplan = _expanded(_mod("auth"), _mod("billing"))
    st = {"phases": {}}
    assert sorted(_front_names(spine, st, mplan)) == ["RED#auth", "RED#billing"]


def test_frontier_dependent_module_waits_for_its_dependency():
    spine, mplan = _expanded(_mod("auth"), _mod("billing", deps=["auth"]))
    st = {"phases": {}}
    assert _front_names(spine, st, mplan) == ["RED#auth"]


def test_frontier_unblocks_dependent_after_dependency_complete():
    spine, mplan = _expanded(_mod("auth"), _mod("billing", deps=["auth"]))
    st = {"phases": {}}
    _mark(st, spine, "RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth")
    assert _front_names(spine, st, mplan) == ["RED#billing"]


def test_frontier_advances_within_a_module_chain():
    spine, mplan = _expanded(_mod("auth"), _mod("billing"))
    st = {"phases": {}}
    _mark(st, spine, "RED#auth")  # auth's RED done, billing untouched
    assert sorted(_front_names(spine, st, mplan)) == ["IMPLEMENTED#auth", "RED#billing"]


def test_frontier_empty_when_all_modules_complete():
    spine, mplan = _expanded(_mod("auth"), _mod("billing", deps=["auth"]))
    st = {"phases": {}}
    _mark(st, spine, "RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth",
          "RED#billing", "IMPLEMENTED#billing", "REVIEWED#billing")
    assert _front_names(spine, st, mplan) == []


# --- FAN1: conflict-group fan-out safety floor ----------------------------------


def _mod_cg(mid, groups, deps=()):
    return {"id": mid, "name": f"{mid} svc", "depends_on": list(deps),
            "acceptance_ids": ["AC-001"], "conflict_groups": list(groups)}


def test_frontier_withholds_module_sharing_conflict_group():
    # auth and billing are dependency-independent but both touch db:migrations ->
    # only the first (declared order) may run; billing is serialized behind it.
    mplan = _plan(_mod_cg("auth", ["db:migrations"]), _mod_cg("billing", ["db:migrations"]))
    spine = multitrack.expand(pipeline.build_spine("standard"), mplan)
    st = {"phases": {}}
    assert _front_names(spine, st, mplan) == ["RED#auth"]


def test_frontier_parallel_when_conflict_groups_disjoint():
    mplan = _plan(_mod_cg("auth", ["db:migrations"]), _mod_cg("billing", ["npm:lockfile"]))
    spine = multitrack.expand(pipeline.build_spine("standard"), mplan)
    st = {"phases": {}}
    assert sorted(_front_names(spine, st, mplan)) == ["RED#auth", "RED#billing"]


def test_frontier_parallel_when_no_conflict_groups_declared():
    # regression: modules with no conflict_groups still fan out (existing behavior).
    spine, mplan = _expanded(_mod("auth"), _mod("billing"))
    st = {"phases": {}}
    assert sorted(_front_names(spine, st, mplan)) == ["RED#auth", "RED#billing"]


def test_frontier_releases_conflict_peer_after_first_completes():
    # once auth's chain is done, billing (same group) is no longer withheld.
    mplan = _plan(_mod_cg("auth", ["db:migrations"]), _mod_cg("billing", ["db:migrations"]))
    spine = multitrack.expand(pipeline.build_spine("standard"), mplan)
    st = {"phases": {}}
    _mark(st, spine, "RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth")
    assert _front_names(spine, st, mplan) == ["RED#billing"]
