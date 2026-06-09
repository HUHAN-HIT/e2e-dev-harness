from pathlib import Path

from e2e_harness.adapters.hooks import paths as hp


def test_code_path_by_suffix(tmp_path):
    assert hp.is_code_path(tmp_path, Path("src/app/foo.py")) is True
    assert hp.is_code_path(tmp_path, Path("src/app/Foo.java")) is True


def test_code_filename(tmp_path):
    assert hp.is_code_path(tmp_path, Path("service/pom.xml")) is True


def test_docs_and_artifacts_not_code(tmp_path):
    assert hp.is_code_path(tmp_path, Path("docs/design/x.md")) is False
    assert hp.is_code_path(tmp_path, Path("docs/agent-runs/r1/run-state.json")) is False
    assert hp.is_code_path(tmp_path, Path("docs/superpowers/plans/p.md")) is False


def test_non_code_suffix(tmp_path):
    assert hp.is_code_path(tmp_path, Path("README.txt")) is False


def test_outside_repo_not_code(tmp_path):
    assert hp.is_code_path(tmp_path, Path("/etc/passwd.py")) is False


def test_control_file_detection(tmp_path):
    assert hp.is_control_file_path(tmp_path, Path("docs/agent-runs/r1/run-state.json")) is True
    assert hp.is_control_file_path(tmp_path, Path("src/run-state.json")) is True
    assert hp.is_control_file_path(tmp_path, Path("src/app.py")) is False


def test_hook_config_detection(tmp_path):
    assert hp.is_hook_config_path(tmp_path, Path(".claude/settings.json")) is True
    assert hp.is_hook_config_path(tmp_path, Path(".opencode/plugins/e2e.js")) is True
    assert hp.is_hook_config_path(tmp_path, Path("src/settings.json")) is False


def test_discover_run_state_picks_latest(tmp_path):
    runs = tmp_path / "docs" / "agent-runs"
    (runs / "old").mkdir(parents=True)
    (runs / "new").mkdir(parents=True)
    old = runs / "old" / "run-state.json"
    new = runs / "new" / "run-state.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    import os, time
    t = time.time()
    os.utime(old, (t - 100, t - 100))
    os.utime(new, (t, t))
    assert hp.discover_run_state(tmp_path) == new


def test_discover_run_state_none_when_absent(tmp_path):
    assert hp.discover_run_state(tmp_path) is None
