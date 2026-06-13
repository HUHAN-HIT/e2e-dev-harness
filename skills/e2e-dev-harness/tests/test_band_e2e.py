"""Design walkthrough: 3 modules (auth, reports independent; billing depends on
auth) advance concurrently through the public verbs. Proves: a beat returns
multiple descriptors, independent tracks sit in the frontier at the same time, a
failing track does not block its sibling, and billing only enters the frontier
after auth completes — then the run joins at VERIFIED."""
import json
import sys

from e2e_harness import pipeline
from e2e_harness.core import run_state, engine, module_plan, acceptance, multitrack
from e2e_harness.adapters.evidence import command_evidence


def _mods():
    return [
        {"id": "auth", "name": "Auth", "depends_on": [], "acceptance_ids": ["AC-001"]},
        {"id": "reports", "name": "Reports", "depends_on": [], "acceptance_ids": ["AC-001"]},
        {"id": "billing", "name": "Billing", "depends_on": ["auth"], "acceptance_ids": ["AC-001"]},
    ]


def _artifact(repo, art, phase, key):
    bkey = multitrack.base_key(key)
    stem = f"{phase.replace('#', '_')}-{key.replace('#', '_')}"
    if bkey == "acceptance_contract":
        p = art / f"{stem}.json"
        p.write_text(json.dumps({"schema": acceptance.SCHEMA, "items": [
            {"id": "AC-001", "criterion": "c", "observable_behavior": "o"}]}), encoding="utf-8")
    elif bkey == "plan":
        p = art / f"{stem}.md"
        p.write_text("# plan\nreal", encoding="utf-8")
    elif bkey == "module_plan":
        p = art / f"{stem}.json"
        p.write_text(json.dumps({"schema": module_plan.SCHEMA, "modules": _mods()}), encoding="utf-8")
    elif bkey == "test_substance":
        tf = art / f"{stem}_test.py"
        tf.write_text("def test_x():\n    assert 1 + 1 == 2\n", encoding="utf-8")
        p = art / f"{stem}.json"
        p.write_text(json.dumps({"schema": "e2e-dev-harness.test-substance.v1",
                                 "acceptance_contract_path": str(art / "CLARIFIED-acceptance_contract.json"),
                                 "language": "python", "test_files": [str(tf)],
                                 "red_tests": ["t::test_x"], "green_tests": ["t::test_x"],
                                 "ac_coverage": {"AC-001": ["t::test_x"]}}), encoding="utf-8")
    elif bkey in ("failing_tests", "passing_tests"):
        code = 1 if bkey == "failing_tests" else 0
        ev = command_evidence.record_command(art, f'"{sys.executable}" -c "import sys; sys.exit({code})"')
        p = art / f"{stem}.json"
        p.write_text(json.dumps(ev), encoding="utf-8")
    elif bkey == "scope_manifest":
        p = art / f"{stem}.json"
        p.write_text(json.dumps({"schema": "e2e-dev-harness.scope-manifest.v1", "status": "COMPLETE",
                                 "expected": {"services": [], "tables": [], "phases": []},
                                 "delivered": {"services": [], "tables": [], "phases": []}}), encoding="utf-8")
    elif bkey == "verification":
        tf = art / f"{stem}-replay_test.py"
        tf.write_text("def test_real():\n    assert 1 + 1 == 2\n", encoding="utf-8")
        ev = command_evidence.record_command(art, f'"{sys.executable}" -m pytest "{tf}" -q')
        p = art / f"{stem}.json"
        p.write_text(json.dumps(ev), encoding="utf-8")
    else:
        p = art / f"{stem}.md"
        p.write_text("real", encoding="utf-8")
    return str(p.relative_to(repo))


def _submit_phase(st, repo, art, spine, ph):
    phase = next(p for p in spine if p.name == ph)
    for key in phase.produces:
        engine.submit_evidence(st, ph, key, _artifact(repo, art, ph, key), repo_root=repo)


def _drive_prologue(st, repo, art):
    """Walk CREATED..PLANNED submitting evidence until the band forks."""
    for _ in range(8):
        spine = pipeline.spine_for_state(st, repo)
        st["_run_state_path"] = "rs.json"
        res = engine.evaluate(spine, st, repo)
        if st.get("region") == "module_band":
            return res
        _submit_phase(st, repo, art, spine, res["blocked_phase"])
    raise AssertionError("never forked into band")


def test_three_module_beats_reach_verified(tmp_path):
    repo = tmp_path
    art = repo / "art"; art.mkdir()
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    res = _drive_prologue(st, repo, art)

    # Beat 1: auth + reports both in frontier; billing absent (depends on auth)
    blocked = sorted(e["blocked_phase"] for e in res["tracks_frontier"])
    assert blocked == ["RED#auth", "RED#reports"]

    saw_billing_before_auth_done = False
    for _ in range(40):
        spine = pipeline.spine_for_state(st, repo)
        st["_run_state_path"] = "rs.json"
        res = engine.evaluate(spine, st, repo)
        if res.get("complete") or res.get("blocked_phase") == "VERIFIED":
            break
        frontier = res.get("tracks_frontier")
        if frontier is None:    # prologue/epilogue singleton step
            _submit_phase(st, repo, art, spine, res["blocked_phase"])
            continue
        # billing must never appear while auth is incomplete
        if any(e["track"] == "billing" for e in frontier) and not st["tracks"]["auth"]["complete"]:
            saw_billing_before_auth_done = True
        # submit the whole frontier this beat (the real concurrent path)
        for entry in frontier:
            _submit_phase(st, repo, art, spine, entry["blocked_phase"])

    # drive the VERIFIED epilogue to completion
    for _ in range(4):
        spine = pipeline.spine_for_state(st, repo)
        st["_run_state_path"] = "rs.json"
        res = engine.evaluate(spine, st, repo)
        if res.get("complete"):
            break
        _submit_phase(st, repo, art, spine, res["blocked_phase"])

    assert st["current_phase"] == "VERIFIED"
    assert res.get("complete") is True
    assert saw_billing_before_auth_done is False  # billing gated until auth complete


def test_failing_track_does_not_block_sibling(tmp_path):
    repo = tmp_path
    art = repo / "art"; art.mkdir()
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    _drive_prologue(st, repo, art)

    # Beat 1: both RED -> submit failing_tests for both, advancing to IMPLEMENTED
    for mid in ("auth", "reports"):
        engine.submit_evidence(st, f"RED#{mid}", f"failing_tests#{mid}",
                               _artifact(repo, art, f"RED#{mid}", f"failing_tests#{mid}"), repo_root=repo)
    spine = pipeline.spine_for_state(st, repo)
    res = engine.evaluate(spine, st, repo)
    frontier = {e["track"]: e["blocked_phase"] for e in res["tracks_frontier"]}
    assert frontier["auth"] == "IMPLEMENTED#auth"
    assert frontier["reports"] == "IMPLEMENTED#reports"

    # reports IMPLEMENTED fails; auth IMPLEMENTED succeeds
    engine.submit_evidence(st, "IMPLEMENTED#reports", None, None, status="failed", reason="impl bug")
    for key in ("passing_tests#auth", "test_substance#auth"):
        engine.submit_evidence(st, "IMPLEMENTED#auth", key,
                               _artifact(repo, art, "IMPLEMENTED#auth", key), repo_root=repo)
    res = engine.evaluate(spine, st, repo)
    frontier = {e["track"]: e for e in res["tracks_frontier"]}
    assert frontier["auth"]["blocked_phase"] == "REVIEWED#auth"      # auth advanced
    assert frontier["reports"]["blocked_phase"] == "IMPLEMENTED#reports"
    assert frontier["reports"].get("failed") is True                  # reports still in rework
