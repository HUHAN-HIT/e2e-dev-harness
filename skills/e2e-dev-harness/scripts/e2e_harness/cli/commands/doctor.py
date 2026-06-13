"""doctor: lightweight project readiness diagnostics for installer contracts.

`doctor` without `--state` is the installer readiness check (`doctor.v1`).
`doctor --state <run-state>` is a separate read-only run-diagnosis surface
(`doctor-state.v1`) that never mutates state or replays verification.
"""
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.core import run_state, state_diagnosis


def _run_state_diagnosis(args, state_path) -> tuple[int, dict]:
    state = run_state.load(state_path)
    payload = state_diagnosis.diagnose_run(state, state_path, getattr(args, "repo", "."))
    return (2 if payload["run_blocked"] else 0), payload


def run(args) -> tuple[int, dict]:
    # --state carries the run-state path (cli/main.py:75); None => installer readiness.
    state_path = getattr(args, "state", None)
    if state_path:
        return _run_state_diagnosis(args, state_path)
    project_root = Path(args.project_root).resolve()
    settings = project_root / ".claude" / "settings.json"
    opencode_plugin = project_root / ".opencode" / "plugins" / "e2e-dev-harness.js"
    strict = bool(getattr(args, "strict", False))
    runtime = str(getattr(args, "runtime", "claude") or "claude").lower()

    settings_available = settings.is_file()
    settings_parseable: bool | None = None
    if settings_available:
        try:
            json.loads(settings.read_text(encoding="utf-8"))
            settings_parseable = True
        except (OSError, ValueError):
            settings_parseable = False

    opencode_available = opencode_plugin.is_file()
    opencode_has_phase_guard: bool | None = None
    opencode_has_stop_guard: bool | None = None
    if opencode_available:
        try:
            body = opencode_plugin.read_text(encoding="utf-8")
            opencode_has_phase_guard = "phase_guard.py" in body
            opencode_has_stop_guard = "stop_guard.py" in body
        except OSError:
            opencode_has_phase_guard = False
            opencode_has_stop_guard = False

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
        "opencode_plugin": {
            "available": opencode_available,
            "contains_phase_guard": opencode_has_phase_guard,
            "contains_stop_guard": opencode_has_stop_guard,
            "path": str(opencode_plugin),
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
        if runtime == "opencode":
            if not opencode_available:
                blocked.append(f".opencode plugin missing: {opencode_plugin}")
            elif not opencode_has_phase_guard or not opencode_has_stop_guard:
                blocked.append(f".opencode plugin is missing harness hook references: {opencode_plugin}")
        else:
            if not settings_available:
                blocked.append(f".claude/settings.json missing: {settings}")
            elif settings_parseable is False:
                blocked.append(f".claude/settings.json is not valid JSON: {settings}")

    return (0 if not blocked else 2), {
        "schema": "e2e-dev-harness.doctor.v1",
        "project_root": str(project_root),
        "runtime": runtime,
        "ready": not blocked,
        "strict": strict,
        "checks": checks,
        "blocked_reasons": blocked,
    }
