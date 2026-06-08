# Design: `e2e-harness init` — one-command project initialization

**Date:** 2026-06-08
**Status:** Approved (brainstorming)
**Author:** baymax

## Problem

Wiring the v2 harness into a business repository currently takes the long,
flag-heavy `node tools/install-e2e-dev-harness.mjs --project <path> --with-hooks
--runtime claude --yes`, while the canonical global command `e2e-harness` lost
its `init` verb in the v2 cutover. The README still documents the legacy v1
`e2e-harness init <repo> --runtime claude`, which now fails. Users want to `cd`
into their project and run a single command that auto-prepares everything with
minimal input.

## Decisions (from brainstorming)

1. **Entry point:** consolidate into `e2e-harness init` (the global CLI).
2. **Execution model:** one-line summary → execute immediately, with rollback on
   failure (`--dry-run` available for preview).
3. **Scope:** full set — runtime auto-detect + auto-install skill if missing +
   merge hooks into `.claude/settings.json` + python detection + finishing
   verification.
4. **Implementation route:** native in `bin/`/`lib/` (route B), extracting the
   hook-materialization logic into a single source of truth `lib/hooks.js`.
   Rationale: `tools/install-e2e-dev-harness.mjs` is **not** in `package.json`
   `files`, so delegating to it would break under npm distribution; `bin`/`lib`
   are packaged and unit-testable via `node --test`.

## Command surface

```
e2e-harness init [project-dir]
    [--runtime auto|claude]   # default auto -> claude
    [--dry-run]               # preview only, no writes
    [--no-doctor]             # skip finishing verification
    [--force]                 # proceed even when python is missing
```

- `project-dir` defaults to the current working directory (the "init in the
  project directory" goal).
- Default behavior **executes** (decision 2): print a one-line summary plus a
  diff of added hook entries, then write. `--dry-run` previews without writing.

## Architecture

Thin dispatch in `bin/e2e-harness.js`; orchestration in `lib/init.js`; the
hook merge/substitution logic is the single source of truth in `lib/hooks.js`.

### Orchestration (`lib/init.js`)

```
resolve project-root (arg | cwd) -> validate it is a directory
  -> detect runtime: scan project for .claude/.codex/.agents; default claude;
       --runtime overrides
  -> ensure skill installed: if skillHome() is absent, call installToMachine()
       to copy the skill into ~/.claude/skills/e2e-dev-harness-v2
  -> detect python (detectPython / resolvePython); if missing -> exit 3 with
       guidance (unless --force); record interpreter in .harness-env.json
  -> materialize hooks (lib/hooks.js): merge into <project>/.claude/settings.json
  -> finishing verification (doctor): selfCheck + assert settings.json contains
       both hook entries and the referenced scripts exist on disk
  -> print one-line summary + diff
```

### Hook single source of truth (`lib/hooks.js`, CJS)

Ported from `tools/install-e2e-dev-harness.mjs`:

- Read `~/.claude/skills/e2e-dev-harness-v2/hooks/claude-code-settings.example.json`.
- **Parse JSON first, then substitute** `__HARNESS_V2_SCRIPTS__` ->
  `<skillHome>/scripts` only inside string leaves (substituting a Windows path
  with backslashes into raw JSON text would break `JSON.parse` — keep the
  parse-then-walk approach the mjs already uses).
- Merge into `<project>/.claude/settings.json` under `hooks.PreToolUse`
  (`phase_guard_v2.py`) and `hooks.Stop` (`stop_guard_v2.py`).
- **Idempotent:** if an entry with the same `command` already exists, skip it and
  report "already configured".
- Back up the existing `settings.json` to `.bak.<ts>` before writing; restore on
  failure (decision 2).

The substitution target is `<skillHome>/scripts` because the template command is
`python __HARNESS_V2_SCRIPTS__/harness_v2/adapters/hooks/phase_guard_v2.py` and
the installed layout is `scripts/harness_v2/adapters/hooks/*.py`.

## Runtime honesty

v2 ships only the claude `settings.json` template, so `init` writes claude-format
hooks. If a project has `.codex` but no `.claude`, runtime detection **warns** and
points to the opencode plugin example, but still defaults to writing
`.claude/settings.json`. codex/agents hook formats are out of scope.

## Error handling / rollback

| Situation | Behavior |
|-----------|----------|
| project-dir is not a directory | exit 2 with error |
| skill install fails | abort **before** touching project files; no half state |
| python missing | exit 3 + guidance (set `E2E_HARNESS_PYTHON`); `--force` bypasses |
| settings.json write throws | restore from backup, then re-raise |
| re-run | idempotent skip, report "already configured" |

## Finishing verification (doctor)

Reuse `lib/lifecycle.js` `selfCheck` (node / python / install / link state) plus:
assert `settings.json` now contains both hook entries and the referenced
`phase_guard_v2.py` / `stop_guard_v2.py` exist on disk. This avoids depending on
an unconfirmed v2 python doctor verb. `--no-doctor` skips it.

## One-line summary (example)

```
init: runtime=claude skill=ok(~/.claude/skills/e2e-dev-harness-v2) python=python3.12 hooks=+2 settings=.claude/settings.json(backup) doctor=ok
```

## Files changed & testing (TDD, `node --test`)

- New: `lib/hooks.js`, `lib/init.js`
- Edit: `bin/e2e-harness.js` — add `init` to `HELP` and to dispatch
- New: `test/init.test.js` covering:
  - runtime detection (`.claude` present, `.codex`-only warn, default claude)
  - idempotent merge (second run adds nothing)
  - `--dry-run` writes nothing
  - backup + rollback on write failure
  - python-missing fail-fast (exit 3) and `--force` bypass
  - `__HARNESS_V2_SCRIPTS__` substituted to `<skillHome>/scripts`
- Docs: fix README / MIGRATION `init` section (remove stale v1 description)

## Explicitly out of scope (YAGNI)

- Do not also install the 6 worker skills (`installToMachine` installs only the
  main skill; hooks only need the main skill's scripts; worker skills stay with
  `install` / the mjs).
- Do not materialize codex/agents hook formats (no v2 settings template exists).
- Do not run pip / external (GitNexus, Graphify) installs from `init`.
