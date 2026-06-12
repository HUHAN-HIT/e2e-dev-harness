"""doctor: lightweight project readiness diagnostics for installer contracts."""
from __future__ import annotations

from pathlib import Path


def run(args) -> tuple[int, dict]:
    project_root = Path(args.project_root).resolve()
    settings = project_root / ".claude" / "settings.json"
    checks = {
        "project_root": {
            "available": project_root.is_dir(),
            "path": str(project_root),
        },
        "claude_settings": {
            "available": settings.is_file(),
            "path": str(settings),
        },
    }
    blocked = []
    if not checks["project_root"]["available"]:
        blocked.append(f"Project root does not exist: {project_root}")

    return (0 if not blocked else 2), {
        "schema": "e2e-dev-harness.doctor.v1",
        "project_root": str(project_root),
        "ready": not blocked,
        "checks": checks,
        "blocked_reasons": blocked,
    }
