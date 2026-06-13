"""doctor: lightweight project readiness diagnostics for installer contracts."""
from __future__ import annotations

import json
from pathlib import Path


def run(args) -> tuple[int, dict]:
    project_root = Path(args.project_root).resolve()
    settings = project_root / ".claude" / "settings.json"
    strict = bool(getattr(args, "strict", False))

    settings_available = settings.is_file()
    settings_parseable: bool | None = None
    if settings_available:
        try:
            json.loads(settings.read_text(encoding="utf-8"))
            settings_parseable = True
        except (OSError, ValueError):
            settings_parseable = False

    checks = {
        "project_root": {
            "available": project_root.is_dir(),
            "path": str(project_root),
        },
        "claude_settings": {
            "available": settings_available,
            "parseable": settings_parseable,
            "path": str(settings),
        },
    }
    blocked = []
    if not checks["project_root"]["available"]:
        blocked.append(f"Project root does not exist: {project_root}")
    # F6: --strict promotes settings readiness from informational to a hard blocker.
    # The DEFAULT stays shallow on purpose — the installer's `--doctor-only` action
    # runs before settings are written, so default readiness must not depend on them.
    # Deeper gating (hooks wired, installed-skill drift, agent-team chain) layers on
    # behind this same flag without breaking the default doctor-only contract.
    if strict:
        if not settings_available:
            blocked.append(f".claude/settings.json missing: {settings}")
        elif settings_parseable is False:
            blocked.append(f".claude/settings.json is not valid JSON: {settings}")

    return (0 if not blocked else 2), {
        "schema": "e2e-dev-harness.doctor.v1",
        "project_root": str(project_root),
        "ready": not blocked,
        "strict": strict,
        "checks": checks,
        "blocked_reasons": blocked,
    }
