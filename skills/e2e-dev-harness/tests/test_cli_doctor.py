import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from e2e_harness.cli.commands import doctor


ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness.py"


def test_doctor_command_accepts_project_and_json_flag(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(ENTRY), "doctor", str(tmp_path), "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema"] == "e2e-dev-harness.doctor.v1"
    assert payload["project_root"] == str(tmp_path.resolve())
    assert payload["ready"] is True


def _doctor(tmp_path, *extra):
    proc = subprocess.run(
        [sys.executable, str(ENTRY), "doctor", str(tmp_path), "--json", *extra],
        cwd=tmp_path, capture_output=True, text=True,
    )
    return proc.returncode, json.loads(proc.stdout or "{}")


def test_doctor_default_ready_without_settings(tmp_path):
    """F6 back-compat: default doctor blocks only on a missing project_root, so the
    installer's doctor-only action (run before settings exist) still reports ready."""
    code, payload = _doctor(tmp_path)
    assert code == 0
    assert payload["ready"] is True
    assert payload["checks"]["claude_settings"]["available"] is False


def test_doctor_strict_blocks_when_settings_absent(tmp_path):
    code, payload = _doctor(tmp_path, "--strict")
    assert code == 2
    assert payload["ready"] is False
    assert any("settings.json" in r for r in payload["blocked_reasons"])


def test_doctor_strict_ready_when_settings_present_and_parseable(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    code, payload = _doctor(tmp_path, "--strict")
    assert code == 0
    assert payload["ready"] is True
    assert payload["checks"]["claude_settings"]["parseable"] is True


def test_doctor_strict_blocks_on_unparseable_settings(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{not valid json", encoding="utf-8")
    code, payload = _doctor(tmp_path, "--strict")
    assert code == 2
    assert payload["ready"] is False
    assert payload["checks"]["claude_settings"]["parseable"] is False


def test_doctor_strict_opencode_checks_plugin_not_claude_settings(tmp_path):
    (tmp_path / ".opencode" / "plugins").mkdir(parents=True)
    (tmp_path / ".opencode" / "plugins" / "e2e-dev-harness.js").write_text(
        "phase_guard.py\nstop_guard.py\n",
        encoding="utf-8",
    )

    code, payload = _doctor(tmp_path, "--strict", "--runtime", "opencode")

    assert code == 0
    assert payload["ready"] is True
    assert payload["runtime"] == "opencode"
    assert payload["checks"]["claude_settings"]["available"] is False
    assert payload["checks"]["opencode_plugin"]["available"] is True


def test_doctor_strict_opencode_blocks_when_plugin_missing(tmp_path):
    code, payload = _doctor(tmp_path, "--strict", "--runtime", "opencode")

    assert code == 2
    assert payload["ready"] is False
    assert payload["runtime"] == "opencode"
    assert any("e2e-dev-harness.js" in r for r in payload["blocked_reasons"])


# --- Task 4: read-only `doctor --state` run diagnosis ------------------------
# `--state` carries the run-state path (cli/main.py:75); None => installer
# readiness (byte-compatible), a path => run diagnosis returning doctor-state.v1.


def test_doctor_default_schema_remains_installer_readiness(tmp_path):
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False, state=None)
    code, payload = doctor.run(args)
    assert code == 0
    assert payload["schema"] == "e2e-dev-harness.doctor.v1"
    assert "checks" in payload


def test_doctor_state_reports_first_missing_evidence(tmp_path):
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED",
        "phases": {"IMPLEMENTED": {"evidence": {}}},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False,
                           state=str(run_state), repo=".")
    code, payload = doctor.run(args)
    assert code == 2
    assert payload["schema"] == "e2e-dev-harness.doctor-state.v1"
    assert payload["diagnosis_ready"] is True
    assert payload["run_blocked"] is True
    assert payload["first_fault"]["kind"] == "missing_evidence"
    assert payload["missing_evidence"] == ["passing_tests", "test_substance"]
    # Pin the full command (real CLI verb + both flags), not just the prefix,
    # so a wrong --repo or state path is caught.
    assert payload["next_legal_command"] == (
        f"e2e-dev-harness dispatch --state {run_state} --repo ."
    )


def test_doctor_state_handles_namespaced_module_phase(tmp_path):
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED#auth",
        "phases": {"IMPLEMENTED#auth": {"evidence": {}}},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False,
                           state=str(run_state), repo=".")
    code, payload = doctor.run(args)
    assert code == 2
    assert payload["blocked_phase"] == "IMPLEMENTED#auth"
    assert payload["missing_evidence"] == ["passing_tests#auth", "test_substance#auth"]


# --- review remediation: diagnose_run must not trust the SHAPE of the state ---


def test_doctor_state_corrupt_evidence_list_is_not_false_clean(tmp_path):
    """A corrupt `evidence` that is a JSON list (not a dict) must NOT yield a
    false all-clear: `key not in [..]` would otherwise do list membership and
    report run_blocked=False for a structurally broken state."""
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED",
        # adversarial: the list even contains the key names, the worst case for `in`.
        "phases": {"IMPLEMENTED": {"evidence": ["passing_tests", "test_substance"]}},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False,
                           state=str(run_state), repo=".")
    code, payload = doctor.run(args)
    assert code == 2
    assert payload["run_blocked"] is True
    assert payload["missing_evidence"] == ["passing_tests", "test_substance"]


def test_doctor_state_non_dict_phase_record_does_not_crash(tmp_path):
    """A non-dict phase record must degrade to a diagnosis payload, not raise a
    bare AttributeError out of the read-only diagnosis surface."""
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED",
        "phases": {"IMPLEMENTED": "oops-not-a-dict"},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False,
                           state=str(run_state), repo=".")
    code, payload = doctor.run(args)
    assert payload["schema"] == "e2e-dev-harness.doctor-state.v1"
    assert code == 2
    assert payload["missing_evidence"] == ["passing_tests", "test_substance"]


def test_doctor_state_unblocked_when_evidence_present(tmp_path):
    """Happy path: a phase with all exit_gate evidence present is not blocked —
    exit 0, run_blocked False, no first_fault, no next_legal_command."""
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED",
        "phases": {"IMPLEMENTED": {"evidence": {
            "passing_tests": {"path": "x"}, "test_substance": {"path": "y"}}}},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False,
                           state=str(run_state), repo=".")
    code, payload = doctor.run(args)
    assert code == 0
    assert payload["run_blocked"] is False
    assert payload["first_fault"] is None
    assert payload["blocked_phase"] is None
    assert payload["next_legal_command"] is None
    assert payload["missing_evidence"] == []


def test_doctor_state_reports_unresolved_failure_as_blocked(tmp_path):
    """#12: a phase with ALL exit_gate evidence present but an unresolved failure
    ledger entry (a reviewer's recorded `failed:<key>`) is gate-blocked, not
    healthy. doctor --state must surface it without replaying anything."""
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED",
        "phases": {"IMPLEMENTED": {
            "evidence": {"passing_tests": {"path": "x"}, "test_substance": {"path": "y"}},
            "failures": {"passing_tests": "tests are weak"},
            "dispatch": "failed",
            "blocker": "tests are weak",
        }},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False,
                           state=str(run_state), repo=".")
    code, payload = doctor.run(args)
    assert code == 2
    assert payload["run_blocked"] is True
    assert payload["first_fault"]["kind"] == "failed_gate"
    assert payload["blocked_phase"] == "IMPLEMENTED"
    assert payload["missing_evidence"] == []   # evidence present; the block is a recorded failure
    assert "weak" in payload["first_fault"]["message"]
    assert payload["next_legal_command"].startswith("e2e-dev-harness dispatch --state")


def test_doctor_state_reports_rework_required(tmp_path):
    """A verification rollback clears the target's evidence and stamps
    rework_required; doctor --state must report kind='rework_required', not a
    generic missing_evidence that hides the rework provenance."""
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED",
        "phases": {"IMPLEMENTED": {
            "evidence": {},
            "dispatch": "failed",
            "blocker": "verification gate failed: verification",
            "rework_required": {
                "from_phase": "VERIFIED",
                "missing_evidence": ["verification"],
                "reason": "verification gate failed: verification",
            },
        }},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False,
                           state=str(run_state), repo=".")
    code, payload = doctor.run(args)
    assert code == 2
    assert payload["run_blocked"] is True
    assert payload["first_fault"]["kind"] == "rework_required"
    assert payload["blocked_phase"] == "IMPLEMENTED"
    assert "verification" in payload["first_fault"]["message"]


# --- F-6: resolve the real blocked task id from dispatch/team-plan artifacts ---
# diagnose_run returned task_id/blocked_task=null. The honest current-checkout
# "task id" is the worker dispatched for the blocked phase, recorded in
# `agent-team-plan.json` (workers[].id / producer_ids). No artifact => stays null.


def test_doctor_state_resolves_blocked_task_from_team_plan(tmp_path):
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED",
        "phases": {"IMPLEMENTED": {"evidence": {}}},
    }), encoding="utf-8")
    # The dispatch artifact the harness wrote for this phase (cli/commands/dispatch.py).
    (tmp_path / "agent-team-plan.json").write_text(json.dumps({
        "schema": "e2e-dev-harness.agent-team-plan.v1",
        "phase": "IMPLEMENTED",
        "workers": [{"id": "IMPLEMENTED-default", "expected_outputs": ["passing_tests"]}],
        "evidence_contract": {"producer_ids": ["IMPLEMENTED-default"]},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False,
                           state=str(run_state), repo=".")
    code, payload = doctor.run(args)
    assert code == 2
    assert payload["blocked_task"] == "IMPLEMENTED-default"
    assert payload["first_fault"]["task_id"] == "IMPLEMENTED-default"


def test_doctor_state_resolves_module_blocked_task(tmp_path):
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED#auth",
        "phases": {"IMPLEMENTED#auth": {"evidence": {}}},
    }), encoding="utf-8")
    # module fan-out: worker id IS the namespaced phase; only the blocked module's
    # worker must be selected, not a sibling module's.
    (tmp_path / "agent-team-plan.json").write_text(json.dumps({
        "schema": "e2e-dev-harness.agent-team-plan.v1",
        "phase": "IMPLEMENTED",
        "workers": [{"id": "IMPLEMENTED#auth"}, {"id": "IMPLEMENTED#billing"}],
        "evidence_contract": {"producer_ids": ["IMPLEMENTED#auth", "IMPLEMENTED#billing"]},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False,
                           state=str(run_state), repo=".")
    code, payload = doctor.run(args)
    assert code == 2
    assert payload["blocked_task"] == "IMPLEMENTED#auth"
    assert payload["first_fault"]["task_id"] == "IMPLEMENTED#auth"


def test_doctor_state_blocked_task_stays_null_without_artifacts(tmp_path):
    """Honest null: a blocked run with no dispatch artifact on disk yields no task
    id (no fabricated T0x)."""
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED",
        "phases": {"IMPLEMENTED": {"evidence": {}}},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False,
                           state=str(run_state), repo=".")
    code, payload = doctor.run(args)
    assert code == 2
    assert payload["blocked_task"] is None
    assert payload["first_fault"]["task_id"] is None


# --- Slice 3: doctor --state cross-checks the event witness ------------------
# diagnose_run gains a control-plane integrity check at the FRONT of the fault
# ladder: a tampered / drifted / known-write-failed control plane invalidates
# every downstream diagnosis, so it outranks missing-evidence / failed-gate. The
# two dead functions (verify_chain, detect_drift) become live here. Absent log =>
# the check self-skips (covered by every test above, which carries no events.jsonl).

from e2e_harness.core import event_log as _event_log  # noqa: E402
from e2e_harness.core import run_state as _run_state   # noqa: E402


def _healthy_state(tmp_path):
    """A domain-UNBLOCKED run (evidence present, dispatch done) so the ONLY fault a
    test can surface is a control-plane one."""
    sp = tmp_path / "run-state.json"
    sp.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "run_id": "r1",
        "current_phase": "IMPLEMENTED",
        "phases": {"IMPLEMENTED": {
            "evidence": {"passing_tests": {"path": "x"}, "test_substance": {"path": "y"}},
            "dispatch": "done"}},
    }), encoding="utf-8")
    return sp


def _clean_chain(sp):
    ep = _run_state.events_path_for(sp)
    _event_log.append_event(ep, {"type": "run.started", "run_id": "r1"})
    _event_log.append_event(ep, {"type": "phase.submitted", "run_id": "r1", "phase": "IMPLEMENTED"})
    _event_log.append_event(ep, {"type": "gate.passed", "run_id": "r1", "phase": "IMPLEMENTED"})
    # A real chain emits evidence.keys alongside gate.passed for an evidence-bearing
    # done phase (derive_events: a submit -> [gate.passed, evidence.keys]); without it
    # the projection is silent on evidence _healthy_state records, which the evidence
    # under-claim check now (correctly) flags as drift. Keys match _healthy_state.
    _event_log.append_event(ep, {"type": "evidence.keys", "run_id": "r1", "phase": "IMPLEMENTED",
                                 "keys": ["passing_tests", "test_substance"]})
    return ep


def _doctor_state(sp, tmp_path):
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False,
                           state=str(sp), repo=".")
    return doctor.run(args)


def test_doctor_state_clean_chain_adds_no_control_plane_fault(tmp_path):
    """A healthy run with a matching chain is not blocked — the live verify_chain +
    detect_drift agree with the projection, so no false control_plane fault."""
    sp = _healthy_state(tmp_path)
    _clean_chain(sp)
    code, payload = _doctor_state(sp, tmp_path)
    assert code == 0
    assert payload["run_blocked"] is False
    assert payload["first_fault"] is None


def test_doctor_state_reports_tampered_event_as_control_plane_drift(tmp_path):
    """2a: editing a non-tail event breaks the forward chain -> verify_chain reports
    event-hash-mismatch -> doctor surfaces control_plane_drift, run blocked."""
    sp = _healthy_state(tmp_path)
    ep = _clean_chain(sp)
    lines = ep.read_text(encoding="utf-8").splitlines()
    ep.write_text(lines[0] + "\n"
                  + lines[1].replace("phase.submitted", "gate.failed") + "\n"
                  + lines[2] + "\n", encoding="utf-8")
    code, payload = _doctor_state(sp, tmp_path)
    assert code == 2
    assert payload["run_blocked"] is True
    assert payload["first_fault"]["kind"] == "control_plane_drift"
    assert "event-hash-mismatch" in payload["first_fault"]["message"]
    assert payload["first_fault"]["task_id"] is None
    # operator-gated recovery: the next step is read-only, never an auto-mutating verb.
    assert "dispatch" not in (payload["next_legal_command"] or "")


def test_doctor_state_reports_drift_after_truncate_and_reanchor(tmp_path):
    """2b: drop the trailing gate.passed and rewrite the .head anchor so verify_chain
    PASSES — the only remaining witness is projection drift against run-state."""
    sp = _healthy_state(tmp_path)
    ep = _clean_chain(sp)
    lines = ep.read_text(encoding="utf-8").splitlines()
    ep.write_text(lines[0] + "\n" + lines[1] + "\n", encoding="utf-8")
    kept = _event_log.read_events(ep)
    _event_log._write_anchor(ep, len(kept), kept[-1]["event_hash"])
    ok, _ = _event_log.verify_chain(ep)
    assert ok   # sanity: the re-anchored truncation is self-consistent
    code, payload = _doctor_state(sp, tmp_path)
    assert code == 2
    assert payload["first_fault"]["kind"] == "control_plane_drift"
    assert payload["first_fault"]["message"].startswith("drift:")


def test_doctor_state_write_failed_sentinel_outranks_drift(tmp_path):
    """2c: a recorded write-failure (sentinel) is a PRECISE cause and must outrank
    ambiguous drift — even when the chain would also drift."""
    sp = _healthy_state(tmp_path)
    ep = _clean_chain(sp)
    lines = ep.read_text(encoding="utf-8").splitlines()      # make it ALSO drift
    ep.write_text(lines[0] + "\n" + lines[1] + "\n", encoding="utf-8")
    kept = _event_log.read_events(ep)
    _event_log._write_anchor(ep, len(kept), kept[-1]["event_hash"])
    _run_state.write_failed_path_for(ep).write_text(json.dumps({
        "schema": "e2e-dev-harness.event-write-failure.v1", "run_id": "r1",
        "expected_sequence": 3, "type": "gate.passed", "reason": "OSError: disk full"}),
        encoding="utf-8")
    code, payload = _doctor_state(sp, tmp_path)
    assert code == 2
    assert payload["first_fault"]["kind"] == "event_log_write_failed"
    assert "dispatch" not in (payload["next_legal_command"] or "")


def test_doctor_state_control_plane_drift_outranks_missing_evidence(tmp_path):
    """Precedence over domain faults: a run that is ALSO missing evidence still
    reports control_plane_drift first — a tampered plane invalidates the rest."""
    sp = tmp_path / "run-state.json"
    sp.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1", "run_id": "r1",
        "current_phase": "IMPLEMENTED",
        "phases": {"IMPLEMENTED": {"evidence": {}}},   # domain fault: missing_evidence
    }), encoding="utf-8")
    ep = _run_state.events_path_for(sp)
    _event_log.append_event(ep, {"type": "run.started", "run_id": "r1"})
    _event_log.append_event(ep, {"type": "phase.submitted", "run_id": "r1", "phase": "IMPLEMENTED"})
    lines = ep.read_text(encoding="utf-8").splitlines()
    ep.write_text(lines[0] + "\n" + lines[1].replace("IMPLEMENTED", "HIJACKED") + "\n",
                  encoding="utf-8")
    code, payload = _doctor_state(sp, tmp_path)
    assert code == 2
    assert payload["first_fault"]["kind"] == "control_plane_drift"
    assert "event-hash-mismatch" in payload["first_fault"]["message"]
