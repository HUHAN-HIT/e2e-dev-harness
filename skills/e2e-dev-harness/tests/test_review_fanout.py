import json
import sys
from pathlib import Path

from e2e_harness import pipeline
from e2e_harness.core import run_state, engine, dispatch, gates
from e2e_harness.adapters.evidence import command_evidence, validate


def _artifact(base, phase, key):
    """Write a real artifact valid for `key`: command-evidence JSON for the
    test-running phases (failing_tests=nonzero, passing_tests=zero), plain
    file otherwise."""
    if key == "test_substance":
        import json as _json
        tf = base / f"{phase}-real_test.py"
        tf.write_text("def test_real():" + chr(10) + "    assert 1 + 1 == 2" + chr(10), encoding="utf-8")
        man = {"schema": "e2e-dev-harness.test-substance.v1",
               "acceptance_contract_path": str(base / "CLARIFIED-acceptance_contract.json"),
               "language": "python", "test_files": [str(tf)],
               "red_tests": ["t::test_real"], "green_tests": ["t::test_real"],
               "ac_coverage": {"AC-001": ["t::test_real"]}}
        f = base / f"{phase}-{key}.json"
        f.write_text(_json.dumps(man), encoding="utf-8")
        return f
    if key == "acceptance_contract":
        from e2e_harness.core import acceptance as _acc
        f = base / f"{phase}-{key}.json"
        f.write_text(json.dumps({"schema": _acc.SCHEMA, "items": [
            {"id": "AC-001", "criterion": "c", "observable_behavior": "o"}]}), encoding="utf-8")
        return f
    want = validate.COMMAND_KEYS.get(key)
    if want is None:
        f = base / f"{phase}-{key}.md"
        f.write_text("real", encoding="utf-8")
        return f
    f = base / f"{phase}-{key}.json"
    code = 0 if want == "zero" else 1
    ev = command_evidence.record_command(
        base, f'"{sys.executable}" -c "import sys; sys.exit({code})"')
    f.write_text(json.dumps(ev), encoding="utf-8")
    return f


def _drive_to(state, repo, target, spine):
    """Advance, fabricating real artifacts, until current_phase == target."""
    base = Path(repo) / "art"
    base.mkdir(parents=True, exist_ok=True)
    res = {"complete": False}
    for _ in range(20):
        res = engine.evaluate(spine, state, repo)
        if state["current_phase"] == target or res["complete"]:
            return res
        phase = res["blocked_phase"]
        ph = next(p for p in spine if p.name == phase)
        for key in ph.produces:
            f = _artifact(base, phase, key)
            engine.submit_evidence(state, phase, key, str(f), repo_root=repo)
    return res


def test_critical_reviewed_dispatch_packet_lists_three_reviews():
    spine = pipeline.build_spine("critical")
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    packet = dispatch.worker_packet(reviewed, "docs/agent-runs/r1/run-state.json")
    assert packet["expected_outputs"] == ["r1_review", "r2_review", "r3_review"]


def test_critical_reviewed_blocks_until_three_real_reviews(tmp_path):
    spine = pipeline.build_spine("critical")
    st = run_state.new_run_state("r1", "f", "r", tier="critical", pipeline="critical")
    _drive_to(st, tmp_path, "REVIEWED", spine)
    assert st["current_phase"] == "REVIEWED"
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    # submit only two real reviews -> still blocked
    for key in ("r1_review", "r2_review"):
        f = tmp_path / f"{key}.md"; f.write_text("ok", encoding="utf-8")
        engine.submit_evidence(st, "REVIEWED", key, str(f), repo_root=tmp_path)
    ok, missing = gates.gate_passes(reviewed, st["phases"]["REVIEWED"], tmp_path)
    assert ok is False and "r3_review" in missing
    # third review -> gate passes
    f = tmp_path / "r3_review.md"; f.write_text("ok", encoding="utf-8")
    engine.submit_evidence(st, "REVIEWED", "r3_review", str(f), repo_root=tmp_path)
    ok, missing = gates.gate_passes(reviewed, st["phases"]["REVIEWED"], tmp_path)
    assert ok is True and missing == []
