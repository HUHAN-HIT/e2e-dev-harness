def test_package_imports():
    import harness_v2
    import harness_v2.core
    assert harness_v2 is not None


from harness_v2.core import run_state


def test_new_run_state_shape():
    st = run_state.new_run_state("r1", "feat", "req")
    assert st["schema"] == "e2e-dev-harness-v2.run-state.v1"
    assert st["current_phase"] == "CREATED"
    assert st["tier"] == "minimal"
    assert st["pipeline"] == "minimal"
    assert st["phases"] == {}


def test_save_then_load_roundtrip(tmp_path):
    st = run_state.new_run_state("r1", "feat", "req")
    p = tmp_path / "run-state.json"
    run_state.save(p, st)
    loaded = run_state.load(p)
    assert loaded["run_id"] == "r1"
    assert loaded["current_phase"] == "CREATED"


def test_save_refreshes_updated_at(tmp_path):
    st = run_state.new_run_state("r1", "feat", "req", now="20260607T000000Z")
    p = tmp_path / "run-state.json"
    run_state.save(p, st, now="20260607T010101Z")
    assert run_state.load(p)["updated_at"] == "20260607T010101Z"
