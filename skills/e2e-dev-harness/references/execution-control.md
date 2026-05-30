# Execution Control

Use execution control when an agent runtime supports pre-tool or pre-action hooks.
The hook is the enforcement layer: it blocks code writes until the active run enters the implementation phase.

## Phase Lock

`run_state.py` writes `docs/agent-runs/<run>/.phase-lock` beside `run-state.json`.
The lock records the lifecycle and the phases that may write production code.

Code writes are allowed only when lifecycle is `IMPLEMENTED`.
Documentation and run artifacts under `docs/agent-runs/` remain writable so agents can prepare evidence before implementation.
For multi-service runs, `.phase-lock` also carries selected services and claimed owners from `run-state.json`.
`phase_guard.py` blocks production-code writes when the touched service has no claimed code-developer task, and blocks a single write action that touches multiple services.
The guard recognizes direct file tools, `apply_patch`, and common shell write commands. Claude Code hook matchers must include `Bash`; otherwise shell-based writes bypass the guard.

## Guard Command

```bash
python skills/e2e-dev-harness/scripts/phase_guard.py . \
  --tool Edit \
  --path services/payment-service/src/main/java/com/acme/PaymentService.java \
  --run-dir docs/agent-runs/<run> \
  --json
```

The command returns exit code `0` when allowed and `2` when blocked.

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
```

Each runtime has different hook wiring, but all examples call the same `phase_guard.py` command. The Codex and Gemini files are templates unless the host runner explicitly supports blocking pre-action or pre-tool configuration; writing the template alone is not enforcement.
If a runtime cannot pass hook JSON through stdin, pass `--tool`, `--path`, and `--run-dir` explicitly.

## Hook Install and Check

Use `install_hooks.py` to install or validate project-local hook configuration:

```bash
python skills/e2e-dev-harness/scripts/install_hooks.py . --runtime claude --json
python skills/e2e-dev-harness/scripts/install_hooks.py . --runtime claude --check --json
```

Supported runtimes are `claude`, `codex`, and `gemini`.
Claude settings are merged into `.claude/settings.json`; Codex and Gemini templates are written under project-local hook folders.

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
