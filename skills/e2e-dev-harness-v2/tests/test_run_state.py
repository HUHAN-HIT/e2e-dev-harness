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


import json
import pytest
from pathlib import Path


def test_load_rejects_schema_mismatch(tmp_path):
    from harness_v2.core import run_state
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema": "wrong", "run_id": "x"}), encoding="utf-8")
    with pytest.raises(ValueError) as ei:
        run_state.load(p)
    assert "schema" in str(ei.value)


def test_save_is_atomic_no_partial_on_replace(tmp_path):
    from harness_v2.core import run_state
    st = run_state.new_run_state("r1", "feat", "req")
    p = tmp_path / "run-state.json"
    run_state.save(p, st)
    leftovers = [q.name for q in tmp_path.iterdir() if q.name != "run-state.json"]
    assert leftovers == []
    assert run_state.load(p)["run_id"] == "r1"


def test_domain_block_embedded_when_supplied():
    st = run_state.new_run_state("r", "f", "q",
        domain={"name": "frontend", "test_runner": "vitest", "review_profile": "frontend-default"})
    assert st["domain"]["name"] == "frontend"


def test_domain_absent_by_default_byte_identical():
    st = run_state.new_run_state("r", "f", "q")
    assert "domain" not in st   # parity: backend default adds no key


import threading


def test_mutate_atomic_under_concurrency(tmp_path):
    p = tmp_path / "run-state.json"
    st = run_state.new_run_state("r1", "feat", "req")
    st["phases"] = {"REVIEWED": {"evidence": {}}}
    run_state.save(p, st)

    def add_key(k):
        run_state.mutate(
            p, lambda s: s["phases"]["REVIEWED"]["evidence"].__setitem__(k, {"path": k})
        )

    keys = [f"r{i}_review" for i in range(20)]
    threads = [threading.Thread(target=add_key, args=(k,)) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ev = run_state.load(p)["phases"]["REVIEWED"]["evidence"]
    assert sorted(ev) == sorted(keys)  # zero lost updates


def test_mutate_releases_lock_and_persists(tmp_path):
    p = tmp_path / "run-state.json"
    run_state.save(p, run_state.new_run_state("r1", "feat", "req"))
    run_state.mutate(p, lambda s: s.__setitem__("feature", "feat2"))
    assert not (tmp_path / "run-state.json.lock").exists()
    assert run_state.load(p)["feature"] == "feat2"
