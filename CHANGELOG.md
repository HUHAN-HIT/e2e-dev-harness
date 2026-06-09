# Changelog

## Unreleased

**Rename: the harness is promoted to its canonical name `e2e-dev-harness`.** The interim
`-v2`-suffixed skill directory, entry script, hook scripts, and Python console script drop the
suffix; the internal Python package is renamed to `e2e_harness` and the hook placeholder to
`__HARNESS_SCRIPTS__`. Persisted run-state / worker-packet / descriptor schema identifiers also
drop the `-v2` segment and are strictly validated on read, so run-states created before this
change are not loadable and must be restarted. The Node CLI name (`e2e-harness`), env vars
(`E2E_HARNESS_HOME` / `E2E_HARNESS_PYTHON`), and `.harness-env.json` are unchanged.

## 0.2.0 - 2026-06-08

**v2 cutover (M5): e2e-dev-harness is now the default; legacy skill retired.** See `MIGRATION.md`.

### Added
- v2 harness as default canonical skill: SSOT `run-state.json`, terminating spine, declarative
  tier-scaled gates, `DomainAdapter` (backend + frontend), worker subagents self-loading Superpowers.
- Declarative tier pipelines `pipelines/*.yaml` (`minimal`/`standard`/`critical`/`audited`) +
  `validate-pipeline` invariant check + user-custom pipelines.
- U7 tool-layer hook enforcement: `phase_guard.py` (PreToolUse phase-lock) + `stop_guard.py`
  (Stop, continue-until-VERIFIED); installer materializes them via `--with-hooks`.
- PyYAML (`pyyaml>=6`) declared as a runtime dependency.

### Changed
- CLI surface 35 verbs → 6 (`start`/`next`/`dispatch`/`submit`/`gate`/`status`) + `validate-pipeline`.
- Python console scripts retarget to `e2e_harness.cli.main:main` (canonical:
  `e2e-dev-harness`/`e2eh` aliases retained). Node CLI dispatches v2 verbs to `e2e_dev_harness.py`.
- Installer copies the v2 skill (skips test/cache artifacts) and wires v2 hooks instead of the
  legacy `install_hooks.py`.

### Removed
- Legacy `skills/e2e-dev-harness/` skill (~70 scripts) and its flat `py-modules` packaging.

### Deferred (recoverable from git history — see `MIGRATION.md`)
- session-checkpoint, recover/gc/timeline, dir-graph contract.

---

## 0.2.0-legacy - 2026-05-31

- Added editable-install metadata and console scripts through `pyproject.toml`.
- Added `doctor` checks for Python, skill layout, project markers, pytest, Maven, GitNexus, and Claude PreToolUse/Stop hook readiness.
- Added a Claude Stop guard that blocks premature finalization after implementation until R3, completion, guard, and archive closure are done.
- Added `--version` to the unified CLI.
- Hardened phase guard provenance and shell-mutation detection in the current development line.

## 0.1.0 - 2026-05-30

- Renamed the workflow to `e2e-dev-harness`.
- Added run-state, phase-lock, artifact registry, multi-service scheduling, semantic review gates, TDD evidence, and strict completion verification.
