"""S1/S2 — per-key review failures must not be erased by another reviewer, and a
failed key must block the gate even when the phase dispatch later reads DONE.

REVIEWED (critical) fans out to r1/r2/r3_review sharing one phase record. The old
bug: r2 fails, then r3's `done` pops the blocker + flips dispatch to DONE, erasing
the failure and letting the gate pass. The fix records failures per key and makes
gate_passes consult them.
"""
from e2e_harness.core import engine, gates, run_state, dispatch
from e2e_harness import pipeline


def _reviewed_phase():
    # pipeline.build_spine expands the review fan-out so the gate requires all
    # three per-reviewer keys (see test_review_fanout); the raw active_phase_names
    # spine would leave a single pre-fanout `review` key.
    return next(p for p in pipeline.build_spine("critical") if p.name == "REVIEWED")


def _state():
    return run_state.new_run_state("r1", "f", "r", pipeline="critical")


def test_keyed_failure_survives_other_reviewers_done():
    st = _state()
    engine.submit_evidence(st, "REVIEWED", "r1_review", "r1.md")
    engine.submit_evidence(st, "REVIEWED", "r2_review", None,
                           status="failed", reason="r2 found a defect")
    engine.submit_evidence(st, "REVIEWED", "r3_review", "r3.md")

    rec = st["phases"]["REVIEWED"]
    # S1: r3's done must NOT erase r2's failure.
    assert rec.get("failures", {}).get("r2_review") == "r2 found a defect"
    # The phase dispatch reads DONE (last submission won) — the OLD signal is gone…
    assert rec["dispatch"] == dispatch.DispatchStatus.DONE.value
    # …but S2: the gate still refuses to pass because r2 failed.
    ok, missing = gates.gate_passes(_reviewed_phase(), rec)
    assert ok is False
    assert "failed:r2_review" in missing


def test_resubmitting_failed_key_clears_failure_and_gate_passes():
    st = _state()
    engine.submit_evidence(st, "REVIEWED", "r1_review", "r1.md")
    engine.submit_evidence(st, "REVIEWED", "r2_review", None,
                           status="failed", reason="boom")
    engine.submit_evidence(st, "REVIEWED", "r3_review", "r3.md")
    # genuine rework: r2 is re-reviewed and now passes
    engine.submit_evidence(st, "REVIEWED", "r2_review", "r2.md")

    rec = st["phases"]["REVIEWED"]
    assert "failures" not in rec or "r2_review" not in rec["failures"]
    ok, missing = gates.gate_passes(_reviewed_phase(), rec)
    assert ok is True
    assert missing == []


def test_phase_level_failure_cleared_by_keyed_done():
    """A whole-phase failure (key=None -> "_phase") is cleared when the phase is
    successfully re-driven via a keyed done, so a crash does not brick the gate."""
    st = _state()
    engine.submit_evidence(st, "REVIEWED", None, None,
                           status="failed", reason="reviewer process crashed")
    assert st["phases"]["REVIEWED"]["failures"]["_phase"] == "reviewer process crashed"
    for key in ("r1_review", "r2_review", "r3_review"):
        engine.submit_evidence(st, "REVIEWED", key, f"{key}.md")

    rec = st["phases"]["REVIEWED"]
    assert "failures" not in rec
    ok, missing = gates.gate_passes(_reviewed_phase(), rec)
    assert ok is True and missing == []
