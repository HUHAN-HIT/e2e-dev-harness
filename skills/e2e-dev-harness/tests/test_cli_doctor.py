import json
import subprocess
import sys
from pathlib import Path


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
