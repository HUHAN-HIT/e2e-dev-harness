import json
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parents[1] / "hooks"


def test_claude_settings_registers_both_hooks():
    data = json.loads((HOOKS_DIR / "claude-code-settings.example.json").read_text(encoding="utf-8"))
    hooks = data["hooks"]
    pre = json.dumps(hooks["PreToolUse"])
    stop = json.dumps(hooks["Stop"])
    assert "phase_guard.py" in pre
    assert "stop_guard.py" in stop
    assert "__HARNESS_SCRIPTS__" in pre and "__HARNESS_SCRIPTS__" in stop


def test_claude_pretooluse_matches_write_tools():
    data = json.loads((HOOKS_DIR / "claude-code-settings.example.json").read_text(encoding="utf-8"))
    matcher = data["hooks"]["PreToolUse"][0]["matcher"]
    for tool in ("Edit", "Write", "MultiEdit", "Bash"):
        assert tool in matcher


def test_claude_commands_quote_placeholder_path():
    data = json.loads((HOOKS_DIR / "claude-code-settings.example.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for groups in data["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]
    assert commands
    for command in commands:
        assert 'python "__HARNESS_SCRIPTS__/' in command


def test_opencode_plugin_calls_phase_guard():
    text = (HOOKS_DIR / "opencode-plugin.example.js").read_text(encoding="utf-8")
    assert "phase_guard.py" in text
    assert "tool.execute.before" in text
    assert "permissionDecision" in text
    assert "__HARNESS_SCRIPTS__" in text


def test_opencode_plugin_wires_stop_softguard():
    text = (HOOKS_DIR / "opencode-plugin.example.js").read_text(encoding="utf-8")
    # session.idle is opencode's "agent finished" event; we bridge it to stop_guard.
    assert "session.idle" in text
    assert "stop_guard.py" in text
    # the reminder surfaces via the opencode client log API (toast is an event,
    # not a callable), so the plugin must take `client` from its context.
    assert "client" in text
    # the plugin must be a proper opencode plugin function (returns hooks), not a
    # bare hooks-object export — otherwise `client` is unavailable.
    assert "async (" in text
    # explicit downgrade note: opencode has no Stop-veto, so this is advisory only.
    lowered = text.lower()
    assert "soft" in lowered or "advisory" in lowered or "cannot" in lowered
