"""module_plan.v1 — machine-readable functional-module slicing (fix B1).

PLANNED must emit a structured module plan, not only prose, so the engine can
fan the RED->IMPLEMENTED->REVIEWED work out per module and drive them in
dependency order (progressive parallel development). validate_module_plan is
pure: structure in, (ok, reason) out — including dependency closure and
acyclicity, since a plan whose modules reference a missing/cyclic dependency
cannot be scheduled.
"""
from e2e_harness.core import module_plan


def _mod(mid="auth", **over):
    base = {"id": mid, "name": f"{mid} service", "depends_on": [], "acceptance_ids": ["AC-001"]}
    base.update(over)
    return base


def _plan(*mods):
    return {"schema": module_plan.SCHEMA, "modules": list(mods) or [_mod()]}


def test_wellformed_plan_passes():
    ok, reason = module_plan.validate_module_plan(
        _plan(_mod("auth"), _mod("billing", depends_on=["auth"])))
    assert ok is True and reason is None


def test_non_object_is_rejected():
    ok, reason = module_plan.validate_module_plan(["x"])
    assert ok is False and reason == "not-object"


def test_wrong_schema_is_rejected():
    p = _plan()
    p["schema"] = "nope"
    ok, reason = module_plan.validate_module_plan(p)
    assert ok is False and reason == "bad-schema"


def test_empty_modules_is_rejected():
    ok, reason = module_plan.validate_module_plan({"schema": module_plan.SCHEMA, "modules": []})
    assert ok is False and reason == "no-modules"


def test_modules_must_be_a_list():
    ok, reason = module_plan.validate_module_plan({"schema": module_plan.SCHEMA, "modules": {}})
    assert ok is False and reason == "no-modules"


def test_bad_module_id_is_rejected():
    ok, reason = module_plan.validate_module_plan(_plan(_mod("bad id!")))
    assert ok is False and reason == "bad-module-id:'bad id!'"


def test_duplicate_module_id_is_rejected():
    ok, reason = module_plan.validate_module_plan(_plan(_mod("auth"), _mod("auth")))
    assert ok is False and reason == "duplicate-module-id:auth"


def test_empty_name_is_rejected():
    ok, reason = module_plan.validate_module_plan(_plan(_mod("auth", name="  ")))
    assert ok is False and reason == "empty-name:auth"


def test_depends_on_must_be_a_list():
    ok, reason = module_plan.validate_module_plan(_plan(_mod("auth", depends_on="billing")))
    assert ok is False and reason == "bad-depends-on:auth"


def test_unknown_dependency_is_rejected():
    ok, reason = module_plan.validate_module_plan(_plan(_mod("billing", depends_on=["ghost"])))
    assert ok is False and reason == "unknown-dep:billing->ghost"


def test_self_dependency_is_rejected():
    ok, reason = module_plan.validate_module_plan(_plan(_mod("auth", depends_on=["auth"])))
    assert ok is False and reason == "self-dep:auth"


def test_cycle_is_rejected():
    ok, reason = module_plan.validate_module_plan(
        _plan(_mod("a", depends_on=["b"]), _mod("b", depends_on=["a"])))
    assert ok is False and reason.startswith("cycle:")


def test_bad_acceptance_id_is_rejected():
    ok, reason = module_plan.validate_module_plan(_plan(_mod("auth", acceptance_ids=["X1"])))
    assert ok is False and reason == "bad-acceptance-id:auth:'X1'"


def test_acceptance_ids_optional():
    m = _mod("auth")
    del m["acceptance_ids"]
    ok, reason = module_plan.validate_module_plan(_plan(m))
    assert ok is True and reason is None


def test_module_ids_in_declared_order():
    p = _plan(_mod("billing", depends_on=["auth"]), _mod("auth"))
    assert module_plan.module_ids(p) == ["billing", "auth"]


def test_topological_order_respects_depends_on():
    # declared billing-before-auth, but billing depends on auth -> auth first
    p = _plan(_mod("billing", depends_on=["auth"]), _mod("auth"))
    assert module_plan.topological_order(p) == ["auth", "billing"]


def test_topological_order_independent_modules_keep_declared_order():
    p = _plan(_mod("auth"), _mod("billing"), _mod("search"))
    assert module_plan.topological_order(p) == ["auth", "billing", "search"]


# --- B4: derive VERIFIED expected scope from the module plan ---------------------


def test_expected_scope_aggregates_services_and_tables():
    p = _plan(
        _mod("auth", **{}) | {"scope": {"services": ["auth"], "tables": ["users"]}},
        _mod("billing") | {"scope": {"services": ["billing"], "tables": ["invoices", "users"]}},
    )
    scope = module_plan.expected_scope(p)
    assert scope["services"] == ["auth", "billing"]
    assert scope["tables"] == ["invoices", "users"]  # deduped + sorted


def test_expected_scope_phases_are_module_ids():
    p = _plan(_mod("auth"), _mod("billing", deps=["auth"]))
    assert module_plan.expected_scope(p)["phases"] == ["auth", "billing"]


def test_expected_scope_tolerates_modules_without_scope():
    p = _plan(_mod("auth"))  # no scope block
    scope = module_plan.expected_scope(p)
    assert scope["services"] == [] and scope["tables"] == []
    assert scope["phases"] == ["auth"]
