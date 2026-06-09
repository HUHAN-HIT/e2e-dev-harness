from e2e_harness.core import pipeline_validate as pv


def test_builtin_specs_are_valid():
    from e2e_harness import pipeline
    for name in ("minimal", "standard", "critical", "audited"):
        ok, errors = pv.validate_spec(pipeline.load_spec(name))
        assert ok is True, f"{name}: {errors}"


def test_valid_custom_spec_passes():
    spec = {"name": "c", "phases": ["CREATED", "CLARIFIED", "VERIFIED"]}
    ok, errors = pv.validate_spec(spec)
    assert ok is True and errors == []


def test_i2_unsatisfiable_evidence_rejected():
    spec = {"name": "c", "phases": [
        "CREATED",
        {"phase": "CLARIFIED", "exit_gate": ["clarification", "ghost"]},
        "VERIFIED",
    ]}
    ok, errors = pv.validate_spec(spec)
    assert ok is False
    assert any("ghost" in e and "I2" in e for e in errors)


def test_i1_duplicate_phase_name_rejected():
    spec = {"name": "c", "phases": ["CREATED", "CLARIFIED", "CLARIFIED", "VERIFIED"]}
    ok, errors = pv.validate_spec(spec)
    assert ok is False
    assert any("duplicate" in e.lower() for e in errors)


def test_empty_phases_rejected():
    ok, errors = pv.validate_spec({"name": "c", "phases": []})
    assert ok is False
    assert any("phases" in e for e in errors)


def test_missing_name_rejected():
    ok, errors = pv.validate_spec({"phases": ["CREATED", "VERIFIED"]})
    assert ok is False
    assert any("name" in e for e in errors)


def test_noncatalog_phase_missing_fields_rejected():
    spec = {"name": "c", "phases": [
        "CREATED",
        {"phase": "AUDIT"},  # not in catalog, missing required fields
        "VERIFIED",
    ]}
    ok, errors = pv.validate_spec(spec)
    assert ok is False
    assert any("AUDIT" in e and "missing" in e for e in errors)


def test_noncatalog_phase_fully_specified_passes():
    spec = {"name": "c", "phases": [
        "CREATED",
        {"phase": "AUDIT", "worker_role": "auditor", "worker_skill": "e2e-harness-completion",
         "produces": ["audit"], "exit_gate": ["audit"]},
        {"phase": "VERIFIED", "produces": ["verification", "audit"], "exit_gate": ["verification", "audit"]},
    ]}
    ok, errors = pv.validate_spec(spec)
    assert ok is True, errors


def test_invalid_entry_type_rejected():
    ok, errors = pv.validate_spec({"name": "c", "phases": [123, "VERIFIED"]})
    assert ok is False


def test_allows_code_write_bool_accepted():
    spec = {"name": "c", "phases": [
        "CREATED",
        {"phase": "IMPLEMENTED", "allows_code_write": True},
        "VERIFIED",
    ]}
    ok, errors = pv.validate_spec(spec)
    assert ok is True, errors


def test_allows_code_write_nonbool_rejected():
    spec = {"name": "c", "phases": [
        "CREATED",
        {"phase": "IMPLEMENTED", "allows_code_write": "yes"},
        "VERIFIED",
    ]}
    ok, errors = pv.validate_spec(spec)
    assert ok is False
    assert any("allows_code_write" in e for e in errors)
