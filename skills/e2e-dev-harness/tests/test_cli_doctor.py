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
