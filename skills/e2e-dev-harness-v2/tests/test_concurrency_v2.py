"""Concurrency safety + lifecycle-lag semantics for the single-file SSOT.

Two pinned contracts:
1. Every mutating verb goes through run_state.mutate() (locked), so parallel
   workers (e.g. r1/r2/r3 reviewers each calling `submit`) cannot clobber each
   other's evidence via last-os.replace-wins.
2. current_phase advances ONLY on `next` (lazy); `submit` records evidence but
   does NOT advance the phase. This is intentional and fail-safe — the phase
   guard stays restrictive until `next` runs.
"""
import threading
import types
from pathlib import Path  # noqa: F401 (kept for parity with command modules)

from harness_v2.core import run_state
from harness_v2.cli.commands import submit as submit_cmd
from harness_v2.cli.commands import next as next_cmd


def _args(state, repo, phase, key, evidence):
    return types.SimpleNamespace(
        state=str(state), repo=str(repo), phase=phase,
        key=key, path=str(evidence), status="done", reason=None,
    )


def test_parallel_reviewer_submits_all_survive(tmp_path):
    p = tmp_path / "run-state.json"
    st = run_state.new_run_state("r1", "feat", "req",
                                 tier="critical", pipeline="critical")
    st["current_phase"] = "REVIEWED"
    run_state.save(p, st)
    evidence = tmp_path / "review.txt"
    evidence.write_text("ok", encoding="utf-8")

    def do(key):
        submit_cmd.run(_args(p, tmp_path, "REVIEWED", key, evidence))

    threads = [threading.Thread(target=do, args=(k,))
               for k in ("r1_review", "r2_review", "r3_review")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ev = run_state.load(p)["phases"]["REVIEWED"]["evidence"]
    assert set(ev) == {"r1_review", "r2_review", "r3_review"}


def test_submit_does_not_advance_current_phase(tmp_path):
    p = tmp_path / "run-state.json"
    st = run_state.new_run_state("r1", "feat", "req")
    st["current_phase"] = "CLARIFIED"
    run_state.save(p, st)
    evidence = tmp_path / "clar.md"
    evidence.write_text("ok", encoding="utf-8")
    submit_cmd.run(_args(p, tmp_path, "CLARIFIED", "clarification", evidence))
    assert run_state.load(p)["current_phase"] == "CLARIFIED"


def test_next_does_not_persist_transient_path_and_leaves_no_lock(tmp_path):
    p = tmp_path / "run-state.json"
    run_state.save(p, run_state.new_run_state("r1", "feat", "req"))
    args = types.SimpleNamespace(state=str(p), repo=str(tmp_path))
    code, res = next_cmd.run(args)
    assert code == 0 and "navigation_map" in res
    assert "_run_state_path" not in run_state.load(p)
    assert not (tmp_path / "run-state.json.lock").exists()
