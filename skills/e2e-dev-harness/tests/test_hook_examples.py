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
    assert "__HARNESS_V2_SCRIPTS__" in pre and "__HARNESS_V2_SCRIPTS__" in stop


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
        assert 'python "__HARNESS_V2_SCRIPTS__/' in command


def test_opencode_plugin_calls_phase_guard():
    text = (HOOKS_DIR / "opencode-plugin.example.js").read_text(encoding="utf-8")
    assert "phase_guard.py" in text
    assert "tool.execute.before" in text
    assert "permissionDecision" in text
    assert "__HARNESS_V2_SCRIPTS__" in text
