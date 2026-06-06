"""Single authoritative control-plane state for harness runs."""

from __future__ import annotations

from pathlib import Path

from common import atomic_write_json, posix
from e2e_harness.domain.control_plane_models import default_control_plane


CONTROL_PLANE_FILE = "control-plane.json"


def control_plane_path(run_dir: Path) -> Path:
    return run_dir / CONTROL_PLANE_FILE


def create(repo: Path, run_dir: Path, run_id: str) -> dict:
    path = control_plane_path(run_dir if run_dir.is_absolute() else repo / run_dir)
    data = default_control_plane(run_id)
    atomic_write_json(path, data)
    return {
        "ready": True,
        "control_plane_path": posix(path),
        "run_id": run_id,
    }
