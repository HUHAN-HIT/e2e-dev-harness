import json
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness.py"


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def test_validate_builtin_is_ok(tmp_path):
    code, res = _run("validate-pipeline", "--pipeline", "critical", cwd=tmp_path)
    assert code == 0
    assert res["ok"] is True and res["errors"] == []
    assert res["pipeline"] == "critical"


def test_validate_valid_custom_path_is_ok(tmp_path):
    f = tmp_path / "good.yaml"
    f.write_text("name: g\nphases: [CREATED, CLARIFIED, VERIFIED]\n", encoding="utf-8")
    code, res = _run("validate-pipeline", "--pipeline", str(f), cwd=tmp_path)
    assert code == 0 and res["ok"] is True


def test_validate_unsatisfiable_custom_path_is_rejected(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text(
        "name: b\nphases:\n  - CREATED\n  - phase: CLARIFIED\n    exit_gate: [clarification, ghost]\n  - VERIFIED\n",
        encoding="utf-8")
    code, res = _run("validate-pipeline", "--pipeline", str(f), cwd=tmp_path)
    assert code == 1
    assert res["ok"] is False
    assert any("ghost" in e for e in res["errors"])
