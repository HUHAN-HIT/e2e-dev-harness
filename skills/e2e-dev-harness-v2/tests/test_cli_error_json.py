import json
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness_v2.py"


def test_unknown_pipeline_emits_json_not_traceback(tmp_path):
    from harness_v2.core import run_state
    st = run_state.new_run_state("r1", "f", "r", tier="bogus", pipeline="bogus")
    p = tmp_path / "run-state.json"
    run_state.save(p, st)
    proc = subprocess.run(
        [sys.executable, str(ENTRY), "next", "--state", str(p), "--repo", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode != 0
    payload = json.loads(proc.stdout or "{}")
    assert "error" in payload
    assert "bogus" in payload["error"]
