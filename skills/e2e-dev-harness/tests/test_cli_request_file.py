"""start: UTF-8 file channel for feature/request + loud mojibake rejection.

The child env deliberately strips PYTHONIOENCODING so these tests prove the
harness emits UTF-8 stdout *intrinsically* — independent of the console
codepage (cp936/GBK on Windows). Without the in-process UTF-8 reconfigure,
non-ASCII JSON would be written in the platform codepage and fail to decode.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness.py"


def _child_env():
    env = dict(os.environ)
    env.pop("PYTHONIOENCODING", None)  # do not let an external override mask the bug
    return env


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          env=_child_env())
    return proc.returncode, json.loads(proc.stdout or "{}")


def test_request_file_preserves_chinese_and_tiers_critical(tmp_path):
    """Chinese requirement via a UTF-8 file survives intact and tiers correctly."""
    req = tmp_path / "request.txt"
    req.write_text("在支付/退款/转账/分账四个场景做风控引擎与多级资金清结算", encoding="utf-8")
    feat = tmp_path / "feature.txt"
    feat.write_text("智能交易风控引擎", encoding="utf-8")

    # No --tier: the classifier must be active by default (default == auto).
    code, res = _run("start", "--repo", str(tmp_path),
                     "--feature-file", str(feat), "--request-file", str(req),
                     cwd=tmp_path)
    assert code == 0, res
    assert res["tier"] == "critical"

    st = json.loads(Path(res["run_state"]).read_text(encoding="utf-8"))
    assert st["feature"] == "智能交易风控引擎"
    assert st["request"].startswith("在支付/退款/转账/分账")


def test_corrupted_inline_request_is_rejected_loudly(tmp_path):
    """A request already mangled to U+FFFD must error, not silently tier minimal."""
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "��֧��/�˿�", cwd=tmp_path)
    assert code == 2
    assert "corrupt" in res.get("error", "").lower()


def test_inline_and_file_conflict_errors(tmp_path):
    req = tmp_path / "r.txt"
    req.write_text("做支付风控", encoding="utf-8")
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "x", "--request-file", str(req), cwd=tmp_path)
    assert code == 2
    assert "error" in res
