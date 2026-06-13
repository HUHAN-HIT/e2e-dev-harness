import json
import subprocess
import sys
from pathlib import Path

from e2e_harness.core import run_state, engine, dispatch
from e2e_harness import pipeline

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness.py"


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args], cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def test_submit_failed_marks_dispatch_failed_with_blocker():
    spine = pipeline.build_spine("minimal")
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(spine, st)  # at CLARIFIED
    engine.submit_evidence(st, "CLARIFIED", None, None, status="failed", reason="clarifier crashed")
    assert st["phases"]["CLARIFIED"]["dispatch"] == dispatch.DispatchStatus.FAILED.value
    assert st["phases"]["CLARIFIED"]["blocker"] == "clarifier crashed"


def test_evaluate_reports_failed_phase():
    spine = pipeline.build_spine("minimal")
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(spine, st)
    engine.submit_evidence(st, "CLARIFIED", None, None, status="failed", reason="boom")
    res = engine.evaluate(spine, st)
    assert res["blocked_phase"] == "CLARIFIED"
    assert res.get("failed") is True
    assert res.get("blocker") == "boom"


def test_successful_resubmit_clears_blocker_and_advances(tmp_path):
    spine = pipeline.build_spine("minimal")
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(spine, st)
    engine.submit_evidence(st, "CLARIFIED", None, None, status="failed", reason="boom")
    f = tmp_path / "c.md"; f.write_text("real", encoding="utf-8")
    engine.submit_evidence(st, "CLARIFIED", "clarification", str(f), repo_root=tmp_path)
    from e2e_harness.core import acceptance as _acc
    ac = tmp_path / "ac.json"
    ac.write_text(json.dumps({"schema": _acc.SCHEMA, "items": [
        {"id": "AC-001", "criterion": "c", "observable_behavior": "o"}]}), encoding="utf-8")
    engine.submit_evidence(st, "CLARIFIED", "acceptance_contract", str(ac), repo_root=tmp_path)
    engine.evaluate(spine, st, tmp_path)
    assert "blocker" not in st["phases"]["CLARIFIED"]
    assert st["current_phase"] == "RED"


def test_cli_submit_failed_then_status_shows_blocked(tmp_path):
    _, res = _run("start", "--repo", str(tmp_path), "--feature", "demo", "--request", "x", cwd=tmp_path)
    sp = res["run_state"]
    _run("next", "--state", sp, "--repo", str(tmp_path), cwd=tmp_path)
    _run("submit", "--state", sp, "--phase", "CLARIFIED", "--status", "failed",
         "--reason", "crashed", "--repo", str(tmp_path), cwd=tmp_path)
    _, sres = _run("status", "--state", sp, "--repo", str(tmp_path), cwd=tmp_path)
    phases = {p["name"]: p["status"] for p in sres["navigation_map"]["phases"]}
    assert phases["CLARIFIED"] == "blocked"


def test_failed_verification_routes_back_to_implementation_rework(tmp_path):
    from e2e_harness.adapters.evidence import command_evidence as ce

    spine = pipeline.build_spine("minimal")
    st = run_state.new_run_state("r1", "f", "r")
    st["current_phase"] = "VERIFIED"
    st["phases"]["IMPLEMENTED"] = {
        "dispatch": dispatch.DispatchStatus.DONE.value,
        "evidence": {
            "passing_tests": {"path": "old-passing.json"},
            "test_substance": {"path": "old-substance.json"},
        },
    }

    ev = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(1)"')
    verification = tmp_path / "verification.json"
    verification.write_text(json.dumps(ev), encoding="utf-8")
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({
        "schema": "e2e-dev-harness.scope-manifest.v1",
        "status": "COMPLETE",
        "expected": {"services": [], "tables": [], "phases": []},
        "delivered": {"services": [], "tables": [], "phases": []},
    }), encoding="utf-8")
    engine.submit_evidence(st, "VERIFIED", "verification", str(verification), repo_root=tmp_path)
    engine.submit_evidence(st, "VERIFIED", "scope_manifest", str(scope), repo_root=tmp_path)

    res = engine.evaluate(spine, st, tmp_path)

    assert res["rework_required"] is True
    assert res["blocked_phase"] == "IMPLEMENTED"
    assert res["next_action"]["skill"] == "e2e-harness-implementation"
    assert st["current_phase"] == "IMPLEMENTED"
    impl = st["phases"]["IMPLEMENTED"]
    assert impl["dispatch"] == dispatch.DispatchStatus.FAILED.value
    assert impl["evidence"] == {}
    assert set(impl["superseded_evidence"]) == {"passing_tests", "test_substance"}


def test_successful_redrive_clears_rework_residue(tmp_path):
    """F3: after a VERIFIED->IMPLEMENTED rollback writes rework residue, a successful
    re-drive of IMPLEMENTED must CLEAR superseded_evidence + rework_required so a
    later reader cannot mistake a converged 'done' phase for one still needing rework,
    and a subsequent evaluate must not re-route back into rework."""
    from e2e_harness.adapters.evidence import command_evidence as ce
    spine = pipeline.build_spine("minimal")
    st = run_state.new_run_state("r1", "f", "r")
    # Predecessors present (key-presence) so F1's all-gates check converges later.
    st["phases"]["CLARIFIED"] = {"evidence": {
        "clarification": {"path": "c"}, "acceptance_contract": {"path": "a"}}}
    st["phases"]["RED"] = {"evidence": {"failing_tests": {"path": "r"}}}
    st["current_phase"] = "VERIFIED"
    st["phases"]["IMPLEMENTED"] = {
        "dispatch": dispatch.DispatchStatus.DONE.value,
        "evidence": {"passing_tests": {"path": "old-p.json"},
                     "test_substance": {"path": "old-s.json"}},
    }
    ev = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(1)"')
    verification = tmp_path / "verification.json"
    verification.write_text(json.dumps(ev), encoding="utf-8")
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({
        "schema": "e2e-dev-harness.scope-manifest.v1", "status": "COMPLETE",
        "expected": {"services": [], "tables": [], "phases": []},
        "delivered": {"services": [], "tables": [], "phases": []},
    }), encoding="utf-8")
    engine.submit_evidence(st, "VERIFIED", "verification", str(verification), repo_root=tmp_path)
    engine.submit_evidence(st, "VERIFIED", "scope_manifest", str(scope), repo_root=tmp_path)
    res = engine.evaluate(spine, st, tmp_path)
    assert res["rework_required"] is True  # baseline: rolled back, residue written
    assert "superseded_evidence" in st["phases"]["IMPLEMENTED"]
    assert "rework_required" in st["phases"]["IMPLEMENTED"]

    # Re-drive: the FIRST successful keyed done already clears the residue.
    engine.submit_evidence(st, "IMPLEMENTED", "passing_tests", "new-p.json")
    assert "superseded_evidence" not in st["phases"]["IMPLEMENTED"]
    assert "rework_required" not in st["phases"]["IMPLEMENTED"]
    engine.submit_evidence(st, "IMPLEMENTED", "test_substance", "new-s.json")
    assert set(st["phases"]["IMPLEMENTED"]["evidence"]) == {"passing_tests", "test_substance"}

    # A subsequent evaluate converges instead of re-routing to rework.
    res2 = engine.evaluate(spine, st)
    assert res2.get("rework_required") is not True
    assert res2["complete"] is True
