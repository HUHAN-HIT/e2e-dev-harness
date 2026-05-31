# Execution Control

Use execution control when an agent runtime supports pre-tool, pre-action, or stop hooks.
The hook is the enforcement layer: it blocks code exploration before `start`, blocks code writes until implementation, forces resumed sessions to reload run-state before code writes, and blocks premature finalization after code has been written but before review/completion closure.

## Phase Lock

`run_state.py` writes `docs/agent-runs/<run>/.phase-lock` beside `run-state.json`.
The lock records the lifecycle and the phases that may write production code.

Code writes are allowed only when lifecycle is `IMPLEMENTED`.
`IMPLEMENTED` must be backed by run-state transition history and ready implementation-gate evidence; matching `.phase-lock` and `run-state.json` values are not enough.
Documentation and run artifacts under `docs/agent-runs/` remain writable so agents can prepare evidence before implementation, except control files such as `.phase-lock`, `run-state.json`, `artifact-registry.json`, and `agent-schedule.json`.
For multi-service runs, `.phase-lock` also carries selected services and claimed owners from `run-state.json`.
`phase_guard.py` blocks production-code writes when the touched service has no claimed code-developer task, and blocks a single write action that touches multiple services.
The guard recognizes direct file tools including Claude `Update`, `apply_patch`, common shell write commands, and inline Python/Node/PowerShell mutation patterns. Unknown tools touching code paths fail closed.
Claude Code hook matchers must include `Read`, `Grep`, `Glob`, `Task`, `Update`, and `Bash`; otherwise code exploration, code-agent dispatch, update-style edits, or shell writes can bypass the guard.
`Task`/`TaskCreate` hooks block implementation-agent dispatch until the run has passed the implementation gate; requirements, design, test-design, handoff, and reviewer tasks remain allowed before implementation.
Read targets outside the configured repository are allowed with a warning instead of being treated as project code, which prevents a stale or mismatched hook target from blocking recovery reads while still blocking code writes outside the target repo.
Direct edits to harness control files and hook configuration are blocked as bypass attempts.
When this happens, the guard returns `not_deadlock: true`, the current `lifecycle`, `allowed_actions`, `forbidden_actions`, and `next_valid_command` so the agent is routed back to the state machine instead of asking to disable hooks.
Unscoped shell mutations are denied by default because service scope cannot be enforced without target paths.

## Stop Guard

Claude Code can stop after a successful compile unless finalization is also guarded. Configure the Claude `Stop` hook to run:

```bash
python skills/e2e-dev-harness/scripts/harness_stop_guard.py . \
  --hook-input - \
  --strict \
  --json
```

`harness_stop_guard.py` discovers the latest `docs/agent-runs/<run>/run-state.json` unless `--run-state` or `--run-dir` is supplied. Runtime hooks must pass `--strict` so every non-terminal lifecycle blocks finalization; this prevents a resumed or impatient agent from stopping after clarify, planning, compile, or partial implementation.
The exception is `WAITING_DISPATCH` / `dispatch.status=waiting_dispatch`: this
state means the current coordinator cannot proceed without an independent
subagent/session. The Stop hook may allow the coordinator turn to end so the
worker can be started, but the run is not complete and completion gates still
require finished scheduled tasks, independent reviews, and evidence.

## Guard Command

```bash
python skills/e2e-dev-harness/scripts/phase_guard.py . \
  --tool Edit \
  --path services/payment-service/src/main/java/com/acme/PaymentService.java \
  --run-dir docs/agent-runs/<run> \
  --json
```

Use `--require-active-run-for-read` in runtime hooks so `Read`/`Grep`/`Glob` on project code block until `e2e_dev_harness.py start` creates `.phase-lock`.
Use `--require-session-checkpoint` so code writes block unless `e2e_dev_harness.py next` has written a fresh `session-checkpoint.json` matching current run-state.

The command returns exit code `0` when allowed and `2` when blocked.

## Resume Checkpoint

`e2e_dev_harness.py next --state docs/agent-runs/<run>/run-state.json` writes `docs/agent-runs/<run>/session-checkpoint.json`.
The checkpoint records lifecycle, run-state fingerprint, next allowed phase, and creation time.
If context compaction or a long session leaves the agent with stale ordering assumptions, `phase_guard.py --require-session-checkpoint` blocks the next code write until `next` is rerun.

When a runtime cannot enforce hooks, run the portable pre-code wrapper before any planned code edit:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py pre-code . \
  --tool Edit \
  --path services/payment-service/src/main/java/com/acme/PaymentService.java \
  --run-dir docs/agent-runs/<run>
```

## Hook Examples

Example configurations live under:

```text
skills/e2e-dev-harness/hooks/claude-code-settings.example.json
skills/e2e-dev-harness/hooks/codex-pre-action.example.json
skills/e2e-dev-harness/hooks/gemini-pre-action.example.json
skills/e2e-dev-harness/hooks/opencode-plugin.example.js
```

Each runtime has different hook wiring. Pre-action examples call `phase_guard.py`; Claude also installs a `Stop` hook that calls `harness_stop_guard.py`. OpenCode installs a project plugin under `.opencode/plugins/e2e-dev-harness.js` and blocks via `tool.execute.before`. The Codex and Gemini files are templates unless the host runner explicitly supports blocking pre-action or pre-tool configuration; writing the template alone is not enforcement.
If a runtime cannot pass hook JSON through stdin, pass `--tool`, `--path`, and `--run-dir` explicitly.

## Hook Install and Check

Use `install_hooks.py` to install or validate project-local hook configuration:

```bash
python skills/e2e-dev-harness/scripts/install_hooks.py . --runtime claude --json
python skills/e2e-dev-harness/scripts/install_hooks.py . --runtime claude --check --json
python skills/e2e-dev-harness/scripts/install_hooks.py . --runtime opencode --json
```

Supported runtimes are `claude`, `codex`, `gemini`, and `opencode`.
Claude settings are merged into `.claude/settings.json`; Codex and Gemini templates are written under project-local hook folders.
`e2e_dev_harness.py pre-code` checks project-level Claude settings first and then user-level `%USERPROFILE%\.claude\settings.json`. `PreToolUse` configuration gates reads/writes; `Stop` configuration gates finalization. `PostToolUse` can audit but cannot prevent the write.
Do not stack broad write-blocking hooks such as `gateguard-fact-force` on the same project unless they explicitly allow harness artifacts, design docs, red-test evidence, handoffs, and review reports; `install_hooks.py --check` reports this as a conflict because it can prevent the harness from producing the evidence needed to advance phases.

## Post-Gate Transition

`auto_transition.py` is a post-tool adapter for runtimes that can react after a gate status artifact is written.
It transitions lifecycle only when the status JSON reports `"ready": true`; it does not bypass gate validation.

```bash
python skills/e2e-dev-harness/scripts/auto_transition.py . \
  --status-file docs/agent-runs/<run>/evidence/implementation-gate.json \
  --state docs/agent-runs/<run>/run-state.json \
  --json
```

## CI Guard

`workflow_guard.py` is still the CI gate over saved `verify` results.
It exits with `0` when ready and `2` when blocked, so CI and hooks can consume it directly.

For GitHub Actions, copy `skills/e2e-dev-harness/ci/github-actions-harness.yml` into `.github/workflows/` and replace the `<run>` placeholders.
The bundled workflow uses `windows-latest`; do not switch it to Linux unless the project has explicitly standardized on Linux CI.
