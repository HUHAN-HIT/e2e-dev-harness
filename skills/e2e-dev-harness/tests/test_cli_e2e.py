import json
import os
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness.py"


def _run(*args, cwd, env=None):
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True, env=proc_env)
    return proc.returncode, json.loads(proc.stdout or "{}")


def _make_artifact(repo: Path, phase: str, key: str) -> str:
    """Produce a REAL artifact for `key`; return its repo-relative path."""
    from e2e_harness.adapters.evidence import command_evidence as ce, validate
    base = repo / "docs" / "agent-runs" / "art"
    base.mkdir(parents=True, exist_ok=True)
    # Any COMMAND_KEYS key (failing_tests/passing_tests/verification) needs genuine
    # command-evidence with the right exit code; everything else is a plain artifact.
    if key == "scope_manifest":
        import json as _json
        f = base / f"{phase}-{key}.json"
        f.write_text(_json.dumps({"schema": "e2e-dev-harness.scope-manifest.v1", "status": "COMPLETE", "expected": {"services": [], "tables": [], "phases": []}, "delivered": {"services": [], "tables": [], "phases": []}}), encoding="utf-8")
        return str(f.relative_to(repo))
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
        return str(f.relative_to(repo))
    if key == "acceptance_contract":
        import json as _json
        from e2e_harness.core import acceptance as _acc
        f = base / f"{phase}-{key}.json"
        f.write_text(_json.dumps({"schema": _acc.SCHEMA, "items": [
            {"id": "AC-001", "criterion": "demo criterion",
             "observable_behavior": "demo observable behaviour"}]}), encoding="utf-8")
        return str(f.relative_to(repo))
    if key == "module_plan":
        import json as _json
        from e2e_harness.core import module_plan as _mp
        f = base / f"{phase}-{key}.json"
        f.write_text(_json.dumps({"schema": _mp.SCHEMA, "modules": [
            {"id": "core", "name": "Core", "depends_on": [], "acceptance_ids": ["AC-001"]}]}), encoding="utf-8")
        return str(f.relative_to(repo))
    if key == "agent_team_dispatch":
        # F4: the audited VERIFIED gate requires a real dispatch-invocation whose
        # referenced team plan resolves to a non-empty worker set. Write both the
        # team plan and the invocation that points at it.
        import json as _json
        from e2e_harness.adapters.evidence import dispatch_invocation as _di
        plan = base / f"{phase}-team-plan.json"
        plan.write_text(_json.dumps({
            "schema": "e2e-dev-harness.agent-team-plan.v1",
            "workers": [{"id": f"{phase}#core", "expected_outputs": []}]}), encoding="utf-8")
        f = base / f"{phase}-{key}.json"
        f.write_text(_json.dumps({
            "schema": _di.DISPATCH_INVOCATION_SCHEMA,
            "phase": phase,
            "team_plan_path": str(plan.relative_to(repo)),
            "descriptors": [{"id": f"{phase}#core", "runtime": "codex"}]}), encoding="utf-8")
        return str(f.relative_to(repo))
    if key == "audit_replay":
        # F5: the audited VERIFIED gate requires an audit-replay manifest whose every
        # claim is backed by genuine command-evidence (anti-forgery, not replayed).
        import json as _json
        from e2e_harness.adapters.evidence import audit_replay as _ar
        ev = ce.record_command(repo, f'"{sys.executable}" -c "import sys; sys.exit(0)"')
        claim_rec = base / f"{phase}-{key}-claim.json"
        claim_rec.write_text(json.dumps(ev), encoding="utf-8")
        f = base / f"{phase}-{key}.json"
        f.write_text(_json.dumps({
            "schema": _ar.AUDIT_REPLAY_SCHEMA,
            "claims": [{"name": "audited suite",
                        "evidence": str(claim_rec.relative_to(repo)),
                        "expect_exit": 0}]}), encoding="utf-8")
        return str(f.relative_to(repo))
    want = validate.COMMAND_KEYS.get(key)
    if want is not None:
        code = 0 if want == "zero" else 1
        command = f'"{sys.executable}" -c "import sys; sys.exit({code})"'
        if key == "verification":
            tf = base / f"{phase}-{key}-replay_test.py"
            tf.write_text("def test_real():\n    assert 1 + 1 == 2\n", encoding="utf-8")
            command = f'"{sys.executable}" -m pytest "{tf}" -q'
        ev = ce.record_command(repo, command)
        f = base / f"{phase}-{key}.json"
        f.write_text(json.dumps(ev), encoding="utf-8")
    else:
        f = base / f"{phase}-{key}.md"
        f.write_text(f"# {phase} {key}\nreal evidence content\n", encoding="utf-8")
    return str(f.relative_to(repo))


def test_start_auto_returns_tier_recommendation(tmp_path):
    code, res = _run(
        "start",
        "--repo",
        str(tmp_path),
        "--feature",
        "tier-options",
        "--request",
        "rename a helper function",
        cwd=tmp_path,
    )

    assert code == 0
    assert res["tier"] == "standard"
    assert res["tier_recommendation"]["recommended_tier"] == "standard"
    assert res["tier_recommendation"]["selected_tier"] == "standard"
    assert res["tier_recommendation"]["selection_source"] == "auto"
    assert len(res["tier_recommendation"]["options"]) == 4
    assert res["tier_reasons"] == res["tier_recommendation"]["reasons"]


def test_start_preview_tier_returns_options_without_creating_run_state(tmp_path):
    code, res = _run(
        "start",
        "--preview-tier",
        "--repo",
        str(tmp_path),
        "--feature",
        "tier-preview",
        "--request",
        "rename a helper function",
        cwd=tmp_path,
    )

    assert code == 0
    assert res["schema"] == "e2e-dev-harness.tier-preview.v1"
    assert res["feature"] == "tier-preview"
    assert res["run_will_be_created"] is False
    assert "run_state" not in res
    assert "run_id" not in res
    assert "current_phase" not in res
    assert res["recommended_tier"] == "standard"
    assert res["selected_tier"] == "standard"
    assert [option["tier"] for option in res["tier_recommendation"]["options"]] == [
        "minimal",
        "standard",
        "critical",
        "audited",
    ]
    assert not (tmp_path / "docs" / "agent-runs").exists()


def test_start_preview_explicit_lower_tier_reports_downgrade(tmp_path):
    # Preview is a read-only dry run: it never creates a run and never exits 2.
    # Its job is to hand the coordinator MACHINE signals (not prose) so a hard
    # coordinator rule can stop and ask the user before a real downgrade start.
    code, res = _run(
        "start",
        "--preview-tier",
        "--repo",
        str(tmp_path),
        "--feature",
        "tier-preview-downgrade",
        "--request",
        "add refund settlement to the ledger",
        "--tier",
        "standard",
        cwd=tmp_path,
    )

    assert code == 0
    assert res["recommended_tier"] == "critical"
    assert res["selected_tier"] == "standard"
    assert res["tier_recommendation"]["selection_source"] == "explicit"
    assert res["tier_recommendation"]["downgrade"]["requested_below_recommended"] is True
    assert res["tier_recommendation"]["downgrade"]["requires_provenance"] is True
    assert res["tier_recommendation"]["downgrade"]["confirmed"] is False
    assert res["tier_recommendation"]["downgrade"]["blocked"] is True
    assert res["confirmation"]["confirmation_required"] is True
    assert res["confirmation"]["must_ask_user"] is True
    assert res["confirmation"]["allowed_without_user_choice"] is False
    assert not (tmp_path / "docs" / "agent-runs").exists()


def test_start_preview_with_pipeline_marks_pipeline_override(tmp_path):
    custom = tmp_path / "custom-pipeline.yaml"
    custom.write_text(
        "name: custom\n"
        "phases:\n"
        "  - CREATED\n"
        "  - CLARIFIED\n"
        "  - RED\n"
        "  - phase: IMPLEMENTED\n"
        "    allows_code_write: true\n"
        "  - VERIFIED\n",
        encoding="utf-8",
    )

    code, res = _run(
        "start",
        "--preview-tier",
        "--repo",
        str(tmp_path),
        "--feature",
        "tier-preview-pipeline",
        "--request",
        "rename a helper function",
        "--pipeline",
        str(custom),
        cwd=tmp_path,
    )

    assert code == 0
    assert res["schema"] == "e2e-dev-harness.tier-preview.v1"
    assert res["pipeline"] == str(custom)
    assert res["pipeline_override"] is True
    assert res["tier_controls_pipeline"] is False
    assert res["recommended_tier"] == "standard"
    assert not (tmp_path / "docs" / "agent-runs").exists()


def test_start_persists_tier_recommendation(tmp_path):
    code, res = _run(
        "start",
        "--repo",
        str(tmp_path),
        "--feature",
        "persist-tier-options",
        "--request",
        "add refund settlement to the ledger",
        cwd=tmp_path,
    )

    assert code == 0
    state = json.loads(Path(res["run_state"]).read_text(encoding="utf-8"))
    assert state["tier"] == "critical"
    assert state["tier_recommendation"]["recommended_tier"] == "critical"
    assert state["tier_recommendation"]["selected_tier"] == "critical"


def test_start_explicit_tier_below_recommended_blocks_without_confirmation(tmp_path):
    # A1: the authoritative backstop. A below-recommended tier with no confirmation
    # token does NOT create a run — the downgrade fact was never settled by a human,
    # so the coordinator cannot turn a historical preference into a current choice.
    code, res = _run(
        "start",
        "--repo",
        str(tmp_path),
        "--feature",
        "explicit-downgrade",
        "--request",
        "add refund settlement to the ledger",
        "--tier",
        "standard",
        cwd=tmp_path,
    )

    assert code == 2
    assert res["schema"] == "e2e-dev-harness.tier-downgrade-blocked.v1"
    assert res["recommended_tier"] == "critical"
    assert res["selected_tier"] == "standard"
    assert "--confirm-downgrade" in res["remediation"]
    assert res["tier_recommendation"]["downgrade"]["blocked"] is True
    assert not (tmp_path / "docs" / "agent-runs").exists()


def test_start_explicit_tier_downgrade_confirmed_creates_run_and_anchors_provenance(tmp_path):
    # The confirmation is settled ONCE in run-state (mirror of approvals.impact_degradation):
    # auditable, with an explicit reason — not re-derivable from the conversation.
    code, res = _run(
        "start",
        "--repo",
        str(tmp_path),
        "--feature",
        "explicit-downgrade-confirmed",
        "--request",
        "add refund settlement to the ledger",
        "--tier",
        "standard",
        "--confirm-downgrade",
        "--downgrade-reason",
        "user explicitly chose standard for this slice",
        cwd=tmp_path,
    )

    assert code == 0
    assert res["tier"] == "standard"
    state = json.loads(Path(res["run_state"]).read_text(encoding="utf-8"))
    anchor = state["approvals"]["tier_downgrade"]
    assert anchor["confirmed_tier"] == "standard"
    assert anchor["recommended_tier"] == "critical"
    assert anchor["reason"] == "user explicitly chose standard for this slice"
    assert anchor["source"] == "user"
    assert state["tier_recommendation"]["downgrade"]["confirmed"] is True
    assert state["tier_recommendation"]["downgrade"]["blocked"] is False


def test_start_confirm_downgrade_without_reason_still_blocks(tmp_path):
    # The reason IS the audit anchor: an empty/missing reason is not a valid
    # confirmation, so the run is still blocked (no rubber-stamp downgrade).
    code, res = _run(
        "start",
        "--repo",
        str(tmp_path),
        "--feature",
        "empty-reason-downgrade",
        "--request",
        "add refund settlement to the ledger",
        "--tier",
        "standard",
        "--confirm-downgrade",
        cwd=tmp_path,
    )

    assert code == 2
    assert res["schema"] == "e2e-dev-harness.tier-downgrade-blocked.v1"
    assert not (tmp_path / "docs" / "agent-runs").exists()


def test_start_confirm_downgrade_whitespace_reason_still_blocks(tmp_path):
    # A whitespace-only reason strips to empty: not a valid anchor, still blocked.
    code, res = _run(
        "start",
        "--repo",
        str(tmp_path),
        "--feature",
        "whitespace-reason-downgrade",
        "--request",
        "add refund settlement to the ledger",
        "--tier",
        "standard",
        "--confirm-downgrade",
        "--downgrade-reason",
        "   ",
        cwd=tmp_path,
    )

    assert code == 2
    assert res["schema"] == "e2e-dev-harness.tier-downgrade-blocked.v1"
    assert not (tmp_path / "docs" / "agent-runs").exists()


def test_start_explicit_tier_above_recommended_is_not_blocked(tmp_path):
    # Selecting a HIGHER tier than recommended is not a downgrade — never blocked,
    # no confirmation needed.
    code, res = _run(
        "start",
        "--repo",
        str(tmp_path),
        "--feature",
        "above-recommended",
        "--request",
        "rename a helper function",
        "--tier",
        "critical",
        cwd=tmp_path,
    )

    assert code == 0
    assert res["tier"] == "critical"
    assert res["tier_recommendation"]["downgrade"]["requested_below_recommended"] is False
    assert res["tier_recommendation"]["downgrade"]["blocked"] is False


def test_start_preview_with_confirmation_signals_no_ask(tmp_path):
    # F1: once the downgrade is confirmed, preview must NOT still say "must ask user".
    # The hard signals track `blocked` (is a choice still needed?), not merely
    # "is this a downgrade?" — otherwise a coordinator rule re-asks after confirming.
    code, res = _run(
        "start",
        "--preview-tier",
        "--repo",
        str(tmp_path),
        "--feature",
        "preview-confirmed",
        "--request",
        "add refund settlement to the ledger",
        "--tier",
        "standard",
        "--confirm-downgrade",
        "--downgrade-reason",
        "user chose standard for this slice",
        cwd=tmp_path,
    )

    assert code == 0
    assert res["tier_recommendation"]["downgrade"]["confirmed"] is True
    assert res["tier_recommendation"]["downgrade"]["blocked"] is False
    assert res["confirmation"]["must_ask_user"] is False
    assert res["confirmation"]["allowed_without_user_choice"] is True
    assert res["confirmation"]["confirmation_required"] is False
    assert not (tmp_path / "docs" / "agent-runs").exists()


def test_start_explicit_tier_below_audited_blocks_without_confirmation(tmp_path):
    # critical < audited is also a downgrade: same backstop, no special-casing.
    code, res = _run(
        "start",
        "--repo",
        str(tmp_path),
        "--feature",
        "explicit-audited-downgrade",
        "--request",
        "compliance audit of the incident response",
        "--tier",
        "critical",
        cwd=tmp_path,
    )

    assert code == 2
    assert res["schema"] == "e2e-dev-harness.tier-downgrade-blocked.v1"
    assert res["recommended_tier"] == "audited"
    assert res["selected_tier"] == "critical"
    assert res["tier_recommendation"]["downgrade"]["blocked"] is True
    assert not (tmp_path / "docs" / "agent-runs").exists()


def test_start_audited_forces_event_log_when_disable_env_set(tmp_path):
    code, res = _run(
        "start",
        "--repo",
        str(tmp_path),
        "--feature",
        "audited-events",
        "--request",
        "compliance audit of the incident response",
        "--tier",
        "audited",
        cwd=tmp_path,
        env={"E2E_HARNESS_DISABLE_EVENTS": "1"},
    )

    assert code == 0
    state_path = Path(res["run_state"])
    assert (state_path.parent / "events.jsonl").exists()


def test_start_defaults_impact_mode_auto(tmp_path):
    """GitNexus impact is ON by default: a run started without --impact-mode records
    impact.mode == auto. (A non-code request like 'do x' is not_applicable, so the
    run is functionally unaffected — proven by the drive test below.)"""
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    assert code == 0
    state = json.loads(Path(res["run_state"]).read_text(encoding="utf-8"))
    assert state["impact"]["mode"] == "auto"


def test_start_impact_mode_off_opts_out(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", "--impact-mode", "off", cwd=tmp_path)
    assert code == 0
    state = json.loads(Path(res["run_state"]).read_text(encoding="utf-8"))
    assert state["impact"]["mode"] == "off"


def test_start_then_drive_to_verified_with_real_artifacts_terminates(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    assert code == 0
    state_path = res["run_state"]
    steps = 0
    nres = {"complete": False}
    while steps < 50:
        steps += 1
        code, nres = _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
        if nres["complete"]:
            break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            rel = _make_artifact(tmp_path, phase, key)
            _run("submit", "--state", state_path, "--phase", phase,
                 "--key", key, "--path", rel, "--repo", str(tmp_path), cwd=tmp_path)
    assert nres["complete"] is True
    assert nres["navigation_map"]["you_are_here"] == "VERIFIED"
    assert nres.get("delivery") == "COMPLETE"  # link ②: full-scope delivery labelled
    # No --tier => auto, which floors to `standard` (G4): the drive walks the
    # standard spine (adds PLANNED + REVIEWED) and terminates in 7 steps. The
    # bound stays tight to guard against a runaway loop / pipeline regression.
    assert steps <= 8


def test_start_audited_then_drive_to_verified_terminates(tmp_path):
    """End-to-end proof that the *audited* tier's evidence chain
    (command-backed audit_replay verification + agent_team_dispatch
    provenance) drives a run all the way to VERIFIED via the CLI.

    The standard drive (above) never exercises the audited spine, so a
    regression in the audited gates or the dispatch-provenance evidence
    would otherwise pass undetected.
    """
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    # --impact-mode off: this test exercises the audited VERIFIED gate chain
    # (audit_replay + agent_team_dispatch), which is orthogonal to the GitNexus impact
    # gate. Impact is on by default, but an audited run in an unindexed temp repo would
    # block on impact; the impact on-path is covered by test_impact_e2e.py.
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "audited-demo",
                     "--request", "compliance audit of the incident response",
                     "--tier", "audited", "--impact-mode", "off", cwd=tmp_path)
    assert code == 0
    assert res["tier"] == "audited"
    state_path = res["run_state"]
    steps = 0
    nres = {"complete": False}
    while steps < 50:
        steps += 1
        code, nres = _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
        if nres["complete"]:
            break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            rel = _make_artifact(tmp_path, phase, key)
            _run("submit", "--state", state_path, "--phase", phase,
                 "--key", key, "--path", rel, "--repo", str(tmp_path), cwd=tmp_path)
    assert nres["complete"] is True
    assert nres["navigation_map"]["you_are_here"] == "VERIFIED"
    # Prove the audited VERIFIED gate validated the full audited chain — not just
    # `verification`. Its three required keys (verification + audit_replay +
    # agent_team_dispatch) all passed; a regression dropping the dispatch-provenance
    # or audit-replay evidence would shrink `required` or leave `missing` non-empty.
    verified = next(n for n in nres["navigation_map"]["full_catalog"] if n["name"] == "VERIFIED")
    assert verified["status"] == "done"
    # Re-check the VERIFIED gate directly: the audited spine requires three keys
    # (verification + audit_replay + agent_team_dispatch), and all pass against the
    # canonically-produced evidence. This guards the audit-replay and dispatch-
    # provenance validators — a regression rejecting valid evidence fails here.
    code, gres = _run("gate", "--state", state_path, "--phase", "VERIFIED",
                      "--repo", str(tmp_path), cwd=tmp_path)
    assert code == 0
    assert gres["passed"] is True
    assert gres["missing_evidence"] == []


def test_fake_path_evidence_never_reaches_verified(tmp_path):
    """R1: a present-but-nonexistent evidence path must NOT drive the run to VERIFIED."""
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    steps = 0
    nres = {"complete": False}
    while steps < 8:
        steps += 1
        code, nres = _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
        if nres["complete"]:
            break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            _run("submit", "--state", state_path, "--phase", phase,
                 "--key", key, "--path", f"{phase}-{key}.md",  # FAKE: never created
                 "--repo", str(tmp_path), cwd=tmp_path)
    assert nres["complete"] is False
    assert nres["navigation_map"]["you_are_here"] != "VERIFIED"


def test_dispatch_returns_pointer_packet(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    code, dres = _run("dispatch", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    assert dres["skill"] == "e2e-harness-clarification"
    assert dres["expected_outputs"] == ["clarification", "acceptance_contract"]


def test_dispatch_emits_worker_descriptor(tmp_path):
    """Dispatch emits a launchable worker request that inherits the runtime default model."""
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    code, dres = _run("dispatch", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    desc = dres["worker_descriptor"]
    assert desc["schema"] == "e2e-dev-harness.worker-descriptor.v1"
    assert desc["runtime"] == "codex"
    assert desc["tool"] == "multi_agent_v1.spawn_agent"
    assert desc["arguments"]["agent_type"] == "worker"
    assert desc["arguments"]["fork_context"] is False
    assert "model" not in desc["arguments"]
    assert "message" in desc["arguments"]
    assert desc["expected_outputs"] == dres["expected_outputs"]


def test_dispatch_runtime_manual_yields_manual_descriptor(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    code, dres = _run("dispatch", "--state", state_path, "--repo", str(tmp_path),
                      "--runtime", "manual", cwd=tmp_path)
    desc = dres["worker_descriptor"]
    assert desc["runtime"] == "manual"
    assert desc["tool"] is None


def test_dispatch_runtime_opencode_yields_task_descriptor(tmp_path):
    """`--runtime opencode` emits an opencode task descriptor (no model pin)."""
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    code, dres = _run("dispatch", "--state", state_path, "--repo", str(tmp_path),
                      "--runtime", "opencode", cwd=tmp_path)
    desc = dres["worker_descriptor"]
    assert desc["runtime"] == "opencode"
    assert desc["tool"] == "task"
    assert desc["arguments"]["subagent_type"] == "general-purpose"
    assert "model" not in desc["arguments"]
    assert "prompt" in desc["arguments"]
    assert desc["expected_outputs"] == dres["expected_outputs"]


def test_gate_verb_rejects_fake_artifact_accepts_real(tmp_path):
    """R1 at the `gate` verb directly: a fake artifact fails the gate (exit 1),
    a real one passes (exit 0)."""
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)  # -> CLARIFIED

    # fake evidence path that is never created
    _run("submit", "--state", state_path, "--phase", "CLARIFIED",
         "--key", "clarification", "--path", "CLARIFIED-clarification.md",
         "--repo", str(tmp_path), cwd=tmp_path)
    code, gres = _run("gate", "--state", state_path, "--phase", "CLARIFIED",
                      "--repo", str(tmp_path), cwd=tmp_path)
    assert code == 1
    assert gres["passed"] is False
    assert "clarification" in gres["missing_evidence"]

    # real artifacts for BOTH required keys at the same phase -> gate passes
    for k in ("clarification", "acceptance_contract"):
        rel = _make_artifact(tmp_path, "CLARIFIED", k)
        _run("submit", "--state", state_path, "--phase", "CLARIFIED",
             "--key", k, "--path", rel, "--repo", str(tmp_path), cwd=tmp_path)
    code, gres = _run("gate", "--state", state_path, "--phase", "CLARIFIED",
                      "--repo", str(tmp_path), cwd=tmp_path)
    assert code == 0
    assert gres["passed"] is True
    assert gres["missing_evidence"] == []
