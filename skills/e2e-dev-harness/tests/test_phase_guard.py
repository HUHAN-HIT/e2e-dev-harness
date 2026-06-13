import json
from pathlib import Path

from e2e_harness.adapters.hooks import phase_guard as pg
from e2e_harness.core import run_state


def _write_state(tmp_path, current_phase, pipeline="minimal"):
    state = run_state.new_run_state("r1", "demo", "do x", pipeline=pipeline)
    state["current_phase"] = current_phase
    sp = tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json"
    run_state.save(sp, state)
    return sp


def _hook(tool, **tin):
    return json.dumps({"tool_name": tool, "tool_input": tin})


def test_parse_hook_input_extracts_path_and_command():
    tool, paths, command = pg.parse_hook_input(_hook("Write", file_path="src/a.py", content="x"))
    assert tool == "Write" and paths == ["src/a.py"] and command == ""
    tool, paths, command = pg.parse_hook_input(_hook("Bash", command="echo hi > src/a.py"))
    assert tool == "Bash" and paths == ["src/a.py"] and command == "echo hi > src/a.py"


def test_parse_empty_is_safe():
    assert pg.parse_hook_input("") == ("", [], "")
    assert pg.parse_hook_input("not json") == ("", [], "")


def test_code_write_denied_in_non_impl_phase(tmp_path):
    sp = _write_state(tmp_path, "RED")
    d = pg.decide(_hook("Write", file_path=str(tmp_path / "src" / "a.py"), content="x"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "RED" in d["reason"] and "next" in d["reason"]
    # actionable: must say WHY it is blocked and HOW to recover
    assert "WHY:" in d["reason"] and "RECOVER:" in d["reason"]
    assert "status" in d["reason"] and "submit" in d["reason"]
    assert "a.py" in d["reason"]


def test_code_write_allowed_in_impl_phase(tmp_path):
    sp = _write_state(tmp_path, "IMPLEMENTED")
    d = pg.decide(_hook("Write", file_path=str(tmp_path / "src" / "a.py"), content="x"), tmp_path, sp)
    assert d["decision"] == "allow"


def test_non_code_path_allowed(tmp_path):
    sp = _write_state(tmp_path, "RED")
    d = pg.decide(_hook("Write", file_path=str(tmp_path / "docs" / "design" / "x.md"), content="x"), tmp_path, sp)
    assert d["decision"] == "allow"


def test_read_like_tool_no_paths_allowed(tmp_path):
    sp = _write_state(tmp_path, "RED")
    d = pg.decide(_hook("Bash", command="ls -la"), tmp_path, sp)
    assert d["decision"] == "allow"


def test_shell_redirect_into_code_denied_in_non_impl_phase(tmp_path):
    sp = _write_state(tmp_path, "RED")
    d = pg.decide(_hook("Bash", command="echo hi > src/a.py"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "a.py" in d["reason"]


def test_shell_redirect_extracts_quoted_windows_style_path(tmp_path):
    target = tmp_path / "src" / "a.py"
    tool, paths, command = pg.parse_hook_input(_hook("Bash", command=f'echo hi > "{target}"'))
    assert tool == "Bash"
    assert paths == [str(target)]
    assert command == f'echo hi > "{target}"'


def test_direct_run_state_write_denied(tmp_path):
    sp = _write_state(tmp_path, "IMPLEMENTED")
    target = tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json"
    d = pg.decide(_hook("Edit", file_path=str(target), new_string="{}"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "run-state.json" in d["reason"]
    assert "WHY:" in d["reason"] and "RECOVER:" in d["reason"]


def test_shell_redirect_into_run_state_denied(tmp_path):
    sp = _write_state(tmp_path, "IMPLEMENTED")
    d = pg.decide(_hook("Bash", command="echo '{}' > docs/agent-runs/r1/run-state.json"), tmp_path, sp)
    assert d["decision"] == "deny"


def test_settings_json_write_denied(tmp_path):
    sp = _write_state(tmp_path, "IMPLEMENTED")
    d = pg.decide(_hook("Edit", file_path=str(tmp_path / ".claude" / "settings.json"), new_string="{}"), tmp_path, sp)
    assert d["decision"] == "deny"


def test_no_active_run_allows_code_write(tmp_path):
    # require-active-run is deferred (design §7): no run-state → allow.
    d = pg.decide(_hook("Write", file_path=str(tmp_path / "src" / "a.py"), content="x"), tmp_path, None)
    assert d["decision"] == "allow"


def test_emit_pretooluse_protocol(capsys):
    pg._emit({"decision": "deny", "reason": "nope"})
    out = json.loads(capsys.readouterr().out)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    assert hso["permissionDecisionReason"] == "nope"


# --- G1: non-Edit/Write write commands must not bypass the phase lock ----------
# Threat model: prevent *unintentional* bypass — a worker reaching for sed/cp/mv/dd
# instead of the Edit/Write tool — not a determined adversary obfuscating argv.

def test_sed_inplace_code_write_denied_in_non_impl_phase(tmp_path):
    sp = _write_state(tmp_path, "RED")
    target = (tmp_path / "src" / "a.py").as_posix()
    d = pg.decide(_hook("Bash", command=f"sed -i 's/x/y/' {target}"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "a.py" in d["reason"]
    assert "WHY:" in d["reason"] and "RECOVER:" in d["reason"]


def test_cp_into_code_denied_in_non_impl_phase(tmp_path):
    sp = _write_state(tmp_path, "RED")
    target = (tmp_path / "src" / "a.py").as_posix()
    d = pg.decide(_hook("Bash", command=f"cp /tmp/forged.py {target}"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "a.py" in d["reason"]


def test_mv_into_code_denied_in_non_impl_phase(tmp_path):
    sp = _write_state(tmp_path, "RED")
    target = (tmp_path / "src" / "a.py").as_posix()
    d = pg.decide(_hook("Bash", command=f"mv /tmp/x.py {target}"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "a.py" in d["reason"]


def test_tee_into_code_denied_in_non_impl_phase(tmp_path):
    sp = _write_state(tmp_path, "RED")
    target = (tmp_path / "src" / "a.py").as_posix()
    d = pg.decide(_hook("Bash", command=f"echo body | tee {target}"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "a.py" in d["reason"]


def test_dd_into_code_denied_in_non_impl_phase(tmp_path):
    sp = _write_state(tmp_path, "RED")
    target = (tmp_path / "src" / "a.py").as_posix()
    d = pg.decide(_hook("Bash", command=f"dd if=/tmp/x of={target}"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "a.py" in d["reason"]


def test_python_c_inline_write_denied_in_non_impl_phase(tmp_path):
    sp = _write_state(tmp_path, "RED")
    target = (tmp_path / "src" / "a.py").as_posix()
    d = pg.decide(
        _hook("Bash", command=f"python -c \"open('{target}','w').write('x')\""),
        tmp_path, sp,
    )
    assert d["decision"] == "deny"
    assert "WHY:" in d["reason"] and "RECOVER:" in d["reason"]


def test_git_apply_denied_conservatively_in_non_impl_phase(tmp_path):
    sp = _write_state(tmp_path, "RED")
    d = pg.decide(_hook("Bash", command="git apply patch.diff"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "WHY:" in d["reason"] and "RECOVER:" in d["reason"]


def test_write_command_allowed_in_impl_phase(tmp_path):
    # The same write commands are legitimate once code writes are unlocked.
    sp = _write_state(tmp_path, "IMPLEMENTED")
    target = (tmp_path / "src" / "a.py").as_posix()
    assert pg.decide(_hook("Bash", command=f"sed -i 's/x/y/' {target}"),
                     tmp_path, sp)["decision"] == "allow"
    assert pg.decide(_hook("Bash", command=f"cp /tmp/forged.py {target}"),
                     tmp_path, sp)["decision"] == "allow"
    assert pg.decide(_hook("Bash", command=f"python -c \"open('{target}','w').write('x')\""),
                     tmp_path, sp)["decision"] == "allow"


def test_write_command_into_doc_path_allowed_in_non_impl_phase(tmp_path):
    # Write commands targeting non-code paths stay allowed (only code is phase-locked).
    sp = _write_state(tmp_path, "RED")
    target = (tmp_path / "docs" / "design" / "x.md").as_posix()
    d = pg.decide(_hook("Bash", command=f"cp /tmp/notes.md {target}"), tmp_path, sp)
    assert d["decision"] == "allow"


# --- G2: SSOT (run-state.json) hard block via any write command ----------------

def test_cp_into_run_state_denied(tmp_path):
    sp = _write_state(tmp_path, "IMPLEMENTED")
    target = (tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json").as_posix()
    d = pg.decide(_hook("Bash", command=f"cp /tmp/forged {target}"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "run-state.json" in d["reason"]


def test_mv_into_run_state_denied(tmp_path):
    sp = _write_state(tmp_path, "IMPLEMENTED")
    target = (tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json").as_posix()
    d = pg.decide(_hook("Bash", command=f"mv /tmp/forged {target}"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "run-state.json" in d["reason"]


def test_read_of_run_state_is_not_blocked(tmp_path):
    # Reads of the SSOT (and the CLI's own status command) must stay allowed —
    # the block is on *writes*, not on mentioning run-state.json.
    sp = _write_state(tmp_path, "RED")
    target = (tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json").as_posix()
    assert pg.decide(_hook("Bash", command=f"cat {target}"),
                     tmp_path, sp)["decision"] == "allow"
    assert pg.decide(_hook("Bash", command=f"e2e-dev-harness status --state {target}"),
                     tmp_path, sp)["decision"] == "allow"


# --- U1: hook-config block must point at the REAL installer command -------------

def test_hook_config_block_points_to_real_installer_command(tmp_path):
    # The block must guide to a directly-runnable installer command. The legacy
    # text named `install-e2e-dev-harness`, which is not a bare command (its real
    # form is `node tools/install-e2e-dev-harness.mjs`); `e2e-harness init` is the
    # npm-linked entrypoint a user can run as-is.
    sp = _write_state(tmp_path, "IMPLEMENTED")
    d = pg.decide(
        _hook("Edit", file_path=str(tmp_path / ".claude" / "settings.json"), new_string="{}"),
        tmp_path, sp,
    )
    assert d["decision"] == "deny"
    assert "e2e-harness init" in d["reason"]
    assert "WHY:" in d["reason"] and "RECOVER:" in d["reason"]
