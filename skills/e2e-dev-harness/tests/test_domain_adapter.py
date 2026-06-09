from pathlib import Path
import pytest
from e2e_harness.adapters.domain import select
from e2e_harness.adapters.domain import backend, frontend


def _mk(p: Path, name: str, body: str = "{}"):
    f = p / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    return f


def test_detect_backend_by_pyproject(tmp_path):
    _mk(tmp_path, "pyproject.toml", "[tool]\n")
    assert select(tmp_path).name == "backend"


def test_detect_frontend_by_package_json_with_react(tmp_path):
    _mk(tmp_path, "package.json", '{"dependencies":{"react":"^18"}}')
    assert select(tmp_path).name == "frontend"


def test_empty_repo_falls_back_to_backend_default(tmp_path):
    assert select(tmp_path).name == "backend"


def test_explicit_overrides_marker(tmp_path):
    _mk(tmp_path, "package.json", '{"dependencies":{"react":"^18"}}')
    assert select(tmp_path, explicit="backend").name == "backend"


def test_unknown_adapter_raises(tmp_path):
    with pytest.raises(KeyError):
        select(tmp_path, explicit="mobile")


def test_fullstack_frontend_wins_by_order(tmp_path):
    _mk(tmp_path, "pyproject.toml", "")
    _mk(tmp_path, "package.json", '{"dependencies":{"vue":"^3"}}')
    assert select(tmp_path).name == "frontend"
