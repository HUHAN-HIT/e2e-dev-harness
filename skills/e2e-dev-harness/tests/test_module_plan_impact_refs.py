from e2e_harness.core import module_plan


def _plan(refs):
    return {"schema": "e2e-dev-harness.module-plan.v1",
            "modules": [{"id": "m1", "name": "M1", "depends_on": [], "acceptance_ids": ["AC-001"],
                         "impact_refs": refs}]}


def test_optional_impact_refs_absent_is_valid():
    ok, reason = module_plan.validate_module_plan(
        {"schema": "e2e-dev-harness.module-plan.v1",
         "modules": [{"id": "m1", "name": "M1", "depends_on": [], "acceptance_ids": ["AC-001"]}]})
    assert ok is True and reason is None   # back-compat preserved


def test_valid_impact_refs_accepted():
    ok, reason = module_plan.validate_module_plan(
        _plan([{"seed": "_phase_request", "affected_processes": ["run"], "test_focus": ["x"]}]))
    assert ok is True and reason is None


def test_impact_refs_must_be_list():
    ok, reason = module_plan.validate_module_plan(_plan("nope"))
    assert ok is False and reason.startswith("bad-impact-refs")


def test_impact_ref_requires_seed():
    ok, reason = module_plan.validate_module_plan(_plan([{"affected_processes": ["run"]}]))
    assert ok is False and reason.startswith("bad-impact-ref")


def test_impact_ref_fields_must_be_lists():
    ok, reason = module_plan.validate_module_plan(
        _plan([{"seed": "s", "affected_processes": "run"}]))
    assert ok is False and reason.startswith("bad-impact-ref-fields")
