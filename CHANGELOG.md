# Changelog

## 0.2.0 - 2026-05-31

- Added editable-install metadata and console scripts through `pyproject.toml`.
- Added `doctor` checks for Python, skill layout, project markers, pytest, Maven, GitNexus, and Claude PreToolUse/Stop hook readiness.
- Added a Claude Stop guard that blocks premature finalization after implementation until R3, completion, guard, and archive closure are done.
- Added `--version` to the unified CLI.
- Hardened phase guard provenance and shell-mutation detection in the current development line.

## 0.1.0 - 2026-05-30

- Renamed the workflow to `e2e-dev-harness`.
- Added run-state, phase-lock, artifact registry, multi-service scheduling, semantic review gates, TDD evidence, and strict completion verification.
