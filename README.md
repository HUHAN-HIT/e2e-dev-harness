# E2E Dev Harness

This repository contains an agent-neutral delivery harness for serious Java/Spring/Maven requirement implementation. It is designed for Codex, Claude Code, Gemini CLI, OpenCode, CI jobs, and any runtime that can read `SKILL.md` and execute the bundled Python scripts.

The harness is not just process documentation. It provides machine-checkable gates, run-state files, agent schedules, artifact registries, replay verification, workflow tiers, review profiles, and optional runtime hook templates that can block code writes before the implementation phase and block premature finalization when the active agent runtime actually supports blocking hooks.

## Layout

```text
skills/e2e-dev-harness/
  SKILL.md
  hooks/
    claude-code-settings.example.json
    codex-pre-action.example.json
    gemini-pre-action.example.json
    opencode-plugin.example.js
  ci/
    github-actions-harness.yml
  references/
    execution-control.md
    implementation-gates.md
    common-review-issues.md
    ...
  review-profiles/
  scripts/
    e2e_dev_harness.py
    install_hooks.py
    phase_guard.py
    harness_stop_guard.py
    session_checkpoint.py
    auto_transition.py
    run_state.py
    artifact_registry.py
    harness_verify.py
    run_summary.py
    execution_trace.py
    checkpoint_gate.py
    command_evidence.py
    test_impact_plan.py
    context_pack.py
    tdd_evidence.py
    task_tier.py
    task_alignment_guard.py
    ...
tests/
  test_e2e_dev_harness_scripts.py
```

## Quick Start

The recommended way to install and drive the harness is the **`e2e-harness` Node CLI** (`bin/e2e-harness.js`). It always resolves the canonical skill copy at `~/.claude/skills/e2e-dev-harness-v2`, so the hooks it writes never depend on your current directory or which checkout you ran it from.

> **Make the command global first.** This package ships *inside this repo* and is **not published to npm**, so `npx e2e-harness …` will 404. Register it once with `npm link`, then call it bare from anywhere — no path, no `npx`:
>
> ```bash
> npm link              # run from the repo root
> # equivalently, after `e2e-harness install`: e2e-harness link
> e2e-harness unlink    # remove the global command later
> ```

### 1. Install to this machine

```bash
e2e-harness install
```

Copies the bundled skill into `~/.claude/skills/e2e-dev-harness-v2`, records the Python interpreter in `.harness-env.json`, and backs up any previous install to `~/.claude/skill-backups/` (outside the skills directory, so the backup is never re-discovered as a duplicate skill).

### 2. Initialize a business repository (one command)

From inside the business repo (or pass its path), run:

```bash
e2e-harness init               # targets the current directory
e2e-harness init <business-repo>
```

`init` does the whole setup with minimal input: it detects the runtime, **installs the skill if it is missing**, materializes the `phase_guard_v2` + `stop_guard_v2` hooks into `<repo>/.claude/settings.json` (rewriting `__HARNESS_V2_SCRIPTS__` to the installed skill's absolute `scripts/` path — never your checkout), then runs a finishing check. It prints a one-line summary and **executes immediately**; an existing `settings.json` is backed up first and the merge is idempotent (re-running adds nothing).

Flags: `--dry-run` (preview without writing), `--runtime auto|claude`, `--no-doctor`, `--force` (wire hooks even if no Python interpreter is found).

### 3. Day-to-day commands

```bash
e2e-harness status   <repo>           # doctor: hooks / index / run-state readiness
e2e-harness next     <repo>           # next allowed harness action
e2e-harness map      <repo>           # compact "you are here" navigation map
e2e-harness dispatch <repo>           # dispatch state + open scheduled tasks
e2e-harness gc       <repo>           # report artifact-retention cleanup candidates
e2e-harness cleanup  <repo> --execute # apply artifact-retention cleanup
e2e-harness exec <script.py> <args>   # run any bundled scripts/<script>.py
```

`gc` and `cleanup` forward to `gc:run`, which is dry-run by default and deletes only with `--execute`. `exec` forwards to `~/.claude/skills/e2e-dev-harness/scripts/<script.py>`; any other subcommand is passed through to `e2e_dev_harness.py`. Override the skill location with `E2E_HARNESS_HOME` and the interpreter with `E2E_HARNESS_PYTHON`.

### 4. Tool maintenance (this machine)

```bash
e2e-harness update      # re-copy the bundled skill (backs up the previous one)
e2e-harness uninstall   # remove ~/.claude/skills/e2e-dev-harness
e2e-harness env         # JSON diagnostics: node / python / install / link state
e2e-harness version     # print name and version
e2e-harness link        # (re)register the global command
e2e-harness unlink      # remove the global command
```

`env` exits non-zero when the skill is not installed or no Python is found, so it doubles as a CI readiness probe.

### Legacy installer (deprecated for hook install)

`tools/install-e2e-dev-harness.mjs` predates the `e2e-harness` CLI. **Do not use it to install hooks:** it runs `install_hooks.py` from `<repo>/skills/e2e-dev-harness`, which bakes your checkout path into the target project's hooks and breaks them if the checkout moves or is renamed. Use `e2e-harness init` instead. Its multi-runtime skill-sync presets (`--sync`, `--target` for Codex/Gemini/OpenCode) remain usable until folded into the CLI:

```powershell
node tools\install-e2e-dev-harness.mjs --sync --yes
```

The editable Python CLI remains available when you want global command aliases:

```powershell
python -m pip install -e .[dev,ast]
e2eh --version
```

After the editable CLI is installed, the shorter tool-first project bootstrap is:

```powershell
e2eh install C:\path\to\business-repo --full --yes
```

When you are already in the target repository, the repo argument can be omitted:

```powershell
e2eh install --full --yes
```

Full installer usage is documented in
[`docs/e2e-dev-harness-installer.md`](docs/e2e-dev-harness-installer.md).

The long command is still available:

```powershell
python -m pip install -e .[dev]
e2e-dev-harness --version
e2e-dev-harness doctor . --json
```

`doctor` checks Python, skill layout, project markers, pytest, Maven, GitNexus, and Claude hook readiness. Use `--strict` in CI or onboarding scripts when warnings should block adoption.

Create a controlled run before analysis or implementation. This writes the
starter design artifact, run-state, `.phase-lock`, artifact registry, and
agent schedule. Production code writes stay locked until the implementation
gate passes.

```powershell
e2e-dev-harness start . `
  --feature "<feature>" `
  --request "<original user request>"
```

Ask the harness what is allowed next:

```powershell
e2e-dev-harness next . `
  --state docs\agent-runs\<run>\run-state.json
```

### Development Navigation Map

Use `e2e-harness map <repo> --state <run-state.json>` for the shortest "you are here" view. The map is a read-only projection of the current `next` result and does not advance lifecycle state.

The map reports:

- current lifecycle, workflow stage, and phase
- ready/blocked status
- one next safe action
- active dispatch work
- allowed and forbidden writes now
- required evidence and key artifact paths

The map has three detail levels:

- Compact stdout: `you_are_here`, `state_confidence`, `next_single_action`, `primary_blocker_code`, and a short `must_read_paths` list.
- `coordinator-summary.json`: durable coordinator resume view with bounded diagnostic checks and authority pointers.
- `full_result_path` / `--json-full`: full control-plane result with execution packet, workflow overview, preflight, and state diagnostics.

Use `state_confidence` as the first trust signal:

- `ready`: run-state and derived views agree.
- `degraded`: the main lifecycle is readable, but a derived view such as `coordinator-summary.json` is stale.
- `blocked`: a required control-plane surface is missing, invalid, or inconsistent.

The map remains read-only. Repair still goes through the command named in `next_single_action` or through doctor/recovery commands.

Use `next --json-full` or the `full_result_path` when you need the complete workflow plan, execution packet, todo policy, or checkpoint details. Use `doctor --state` when environment health or state consistency looks abnormal.

Then fill the generated design doc and run clarification/discovery:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py clarify . `
  --design-doc docs\design\<feature>.md `
  --run-state docs\agent-runs\<run>\run-state.json

python skills\e2e-dev-harness\scripts\e2e_dev_harness.py prepare . `
  --design-doc docs\design\<feature>.md `
  --workflow-tier auto `
  --agent-mode strict `
  --agent-scope discovery `
  --service-scope discovery `
  --include-agent-content
```

After affected services or paths are known, create the full agent-run archive:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py plan . `
  --design-doc docs\design\<feature>.md `
  --agent-run-dir docs\agent-runs\<run> `
  --service-scope affected `
  --service services\<service> `
  --create-archive
```

This creates:

```text
docs/agent-runs/<run>/
  run-state.json
  .phase-lock
  artifact-registry.json
  run-summary.json
  run-summary.md
  exec-plan.md
  handoffs/
  service-designs/
  review-requests/
  reviews/
  evidence/
```

`next` also writes `docs/agent-runs/<run>/session-checkpoint.json`. Runtime hooks validate this checkpoint before code writes, so a resumed or compacted agent must reload the current lifecycle and next action instead of continuing from a stale chat summary.

## Workflow Tiers

Use `--workflow-tier auto|basic|standard|critical|audited`.

All tiers keep auditable evidence, test proof, and replayable run records. The tier only controls evidence depth and orchestration strength.

| Tier | Use When | Required Evidence |
| --- | --- | --- |
| `basic` | Small scoped delivery work | clarification, bounded impact summary, test evidence, completion proof, task alignment, run-state, artifact registry, run summary |
| `standard` | Normal requirement implementation | `basic` plus R1/R2/R3 reviews, coverage matrix, requirements archive |
| `critical` | MQ/HTTP/DB/security/payment/refund/cross-service work | `standard` plus GitNexus impact artifact, contracts, service plans, handoffs, strict guard |
| `audited` | Audit, compliance, incident, or production-critical work | `critical` plus harness policy, harness replay, completion replay, state history |

## Dependency Scan Parser

`cross_service_dependency_scan.py` reports `java_parser.backend`. The current scanner uses `regex-fallback` even when `tree_sitter` packages are installed, and reports `ast_parser_active: false`, because silently claiming AST precision would hide missed Java call paths. Treat `regex-fallback` as acceptable for lightweight discovery; for high-risk Java impact decisions, require GitNexus evidence and use `--require-tree-sitter-ast` if the run policy demands an active AST parser.

GitNexus command roles are intentionally separated:

- `gitnexus context` takes a code symbol such as a class, function, method, or `Class.method`; do not pass service directories.
- `gitnexus impact` or `gitnexus detect-changes` owns affected-scope analysis.
- In multi-service runs, generate evidence only for the services declared in the global design/service slices, not every detected module in the repository.

For `critical` or `audited` completion, GitNexus evidence is a gate input, not a best-effort hint. If MCP/CLI/index access fails, pause and ask the user whether to approve degradation. Approved degradation must be recorded in an evidence file containing `Approval: user-approved`, `Reason:`, and `Fallback Evidence:` or `Compensating Evidence:`, then passed with `--gitnexus-degradation`.

For `critical` or `audited` implementation, dependency discovery evidence is required before production code opens. This prevents compile-driven discovery after the implementation has already been written.

Knowledge graph refresh status is run-scoped. Prefer:

```powershell
python skills\e2e-dev-harness\scripts\kg_refresh.py . `
  --mode auto `
  --status-file docs\agent-runs\<run>\evidence\knowledge-graph-refresh.json
```

Implementation gates first read the current run's evidence file, then the latest
run evidence, and only then fall back to root-level legacy files such as
`knowledge-graph\knowledge-graph-refresh.json`. A stale root file with
`status: skipped` or `reason: no knowledge graph configured` is blocked when the
repository already has `.gitnexus\meta.json`; regenerate run-scoped evidence
instead of editing the phase lock or downgrading the gate.

## Incremental Test Scope

For large Maven repositories, do not default to full-suite testing on every turn. Generate a test impact plan from changed files and dependency evidence, then run every required command in that plan.

```powershell
git diff --name-only > docs\agent-runs\<run>\evidence\changed-files.txt

python skills\e2e-dev-harness\scripts\e2e_dev_harness.py test-impact . `
  --changed-files docs\agent-runs\<run>\evidence\changed-files.txt `
  --dependency-report docs\agent-runs\<run>\evidence\cross-service-dependencies.json `
  --output docs\agent-runs\<run>\evidence\test-impact-plan.json
```

Completion can then prove that the planned affected commands actually passed:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py gate . `
  --phase completion `
  --design-doc docs\design\<feature>.md `
  --unit-test-evidence docs\agent-runs\<run>\evidence\green-test.txt `
  --test-impact-plan docs\agent-runs\<run>\evidence\test-impact-plan.json
```

If the plan contains `mvn -pl services\foo -am test`, the unit-test evidence must contain that command with `exit_code: 0`. Root/shared build or source changes intentionally expand to `mvn test`.

## Context Packs

For multi-agent runs, generate a request-scoped context pack per scheduled agent instead of passing the full conversation or all run artifacts.

Work is split by role even for one service: design, test, code, semantic review, and coverage must be different agent roles with ready handoff artifacts between them. `plan --create-archive` writes short role templates under `agent-roles/`, and `agent-schedule.json` requires each role task to reference one. Multi-service work adds service-local design slices and parallel service code agents. If the global design declares multiple affected services/modules, orchestration must use `multi` even when the caller supplied `--mode single`; high-risk or large single-service work uses `single-review`, not `multi`, so risk words alone do not force service splitting.

```text
docs/agent-runs/<run>/service-designs/<service>.md
docs/agent-runs/<run>/service-plans/<service>/implementation-plan.md
docs/agent-runs/<run>/service-plans/<service>/test-impact-plan.json
```

Multi-service `plan --create-archive` writes run-state lifecycle `SERVICE_DESIGN_REQUIRED`. Dispatch service-design workers to produce the slices, then validate returned evidence before R2/TDD red or dispatching code agents; the command below transitions the run-state to `PLANNED` only when every global AC is mapped into concrete service slices with runtime path, first red test, expected failure, required Maven command, dependency boundary, and test impact. The global design template includes `System Sequence`; service slices include `Local Sequence`, and cross-service, contract, shared-state, or event dependencies must keep that local sequence concrete enough to drive the first red test and dependency-edge implementation.

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py service-design . `
  --global-design docs\design\<feature>.md `
  --service-design-dir docs\agent-runs\<run>\service-designs `
  --run-state docs\agent-runs\<run>\run-state.json
```

```powershell
python skills\e2e-dev-harness\scripts\context_pack.py . `
  --agent-schedule docs\agent-runs\<run>\agent-schedule.json `
  --service services\<service> `
  --output docs\agent-runs\<run>\context-packs\<service>.json `
  --max-files 12 `
  --max-chars 120000
```

The pack lists allowed inputs, allowed outputs, dependency phase, and budget. A pack that exceeds file or byte limits is blocked, forcing the coordinator to summarize inputs before dispatch.

For Claude Code project integrations, start with L0 serial isolated dispatch instead of trying true parallelism first: read `agent-schedule.json`, claim the next ready task, spawn a fresh subagent/session with only its role template and context pack, complete the task with a scheduled evidence file, then dispatch the next dependent task. This keeps role isolation and handoff gates active without making the core skill depend on a specific runtime scheduler.

**Prerequisite for autonomous dispatch:** install the runtime hooks first with
`python skills\e2e-dev-harness\scripts\install_hooks.py . --runtime claude --json`
(see [Hook Configuration](#hook-configuration)). The hooks back the
`supports_task_hook`/`supports_blocking_stop` capabilities the dispatcher relies
on to confirm a spawned `Task` and to block premature finalization. Without an
enforceable runtime hook, `dispatch-next`/`dispatch-beat` force
`WAITING_DISPATCH`: the coordinator must then acknowledge each spawned worker
manually with `dispatch-ack` before `dispatch-complete` will accept its evidence.
Autonomous, hook-confirmed dispatch is the installed-hooks path; manual `dispatch-ack`
is the fallback when hooks are absent.

The bundled dispatcher provides the first Claude Code/Superpowers execution loop:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py runtime-capabilities . --runtime claude-code
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py dispatch-beat . `
  --schedule docs\agent-runs\<run>\agent-schedule.json `
  --state docs\agent-runs\<run>\run-state.json `
  --runtime claude-code `
  --max-workers 4
```

`dispatch-beat` scans the schedule for the next ready wave and reports earlier
skipped tasks with their blockers. It validates dependency phases, ready handoff
markers, role templates, and context-pack budgets before claiming tasks. It then
writes `context-packs/<task-id>.json`, claims each task, writes dispatcher
invocation JSON, and returns self-contained Claude Code `Task` prompts. Each
subagent must use only its context pack and scheduled outputs. `dispatch-next`
remains the compatibility wrapper for `dispatch-beat --max-workers 1`. After a
subagent returns evidence, close the task:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py dispatch-complete . `
  --schedule docs\agent-runs\<run>\agent-schedule.json `
  --state docs\agent-runs\<run>\run-state.json `
  --task-id T10 `
  --agent code-developer-payment `
  --evidence docs\agent-runs\<run>\service-plans\payment\code-agent.md
```

If the active runtime cannot spawn an independent subagent/session, `dispatch-beat`
records `WAITING_DISPATCH` with `dispatch.status=waiting_dispatch` and emits a
manual dispatch packet. Claude Code Stop hooks allow that paused handoff state so
the coordinator can start a fresh session, but completion gates still fail until
scheduled tasks, reviews, handoffs, and evidence are complete.

`start` now writes a bootstrap schedule with a `requirements-clarifier` task, so
clarification can be delegated before the full plan archive exists. The
coordinator still runs deterministic control-plane commands such as
`plan --create-archive`, but requirements, use cases, implementation planning,
tests, semantic reviews, service code, and coverage work must move through
scheduled subagents whenever the runtime can provide isolated Task sessions.

For R1/R2/R3 tasks, `dispatch-complete` immediately runs the reviewer gate against
the reported review evidence. A reviewer task is not marked complete when the
report fails independence, request-hash, required-field, or no-code-change checks.

Before a multi-service code agent writes code, claim the scheduled service task. Phase guard blocks unclaimed service writes and blocks one claimed task from editing multiple services:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py agent-task . `
  --schedule docs\agent-runs\<run>\agent-schedule.json `
  --action claim `
  --task-id T04 `
  --agent code-developer-order-service `
  --state docs\agent-runs\<run>\run-state.json
```

After service-local ACs, tests, and review evidence are done, complete the task. The evidence path must exist and match one of the task outputs in `agent-schedule.json`:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py agent-task . `
  --schedule docs\agent-runs\<run>\agent-schedule.json `
  --action complete `
  --task-id T04 `
  --agent code-developer-order-service `
  --state docs\agent-runs\<run>\run-state.json `
  --evidence docs\agent-runs\<run>\service-plans\order-service\unit-test-evidence.txt
```

## AC Progress

Do not stop after the first passing AC unless the user explicitly scoped the run to that AC. Before R3, prove all assigned ACs for the global design or service design slice are implemented and tested:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py ac-progress . `
  --service-design docs\agent-runs\<run>\service-designs\<service>.md `
  --coverage-matrix docs\agent-runs\<run>\service-plans\<service>\coverage-matrix.md `
  --implementation-manifest docs\agent-runs\<run>\service-plans\<service>\implementation-manifest.md `
  --unit-test-evidence docs\agent-runs\<run>\service-plans\<service>\unit-test-evidence.txt
```

If this blocks on `AC-2`, dispatch or continue code-developer TDD red/green for `AC-2`; do not ask whether to start R3.

## Hook Configuration

The hook examples are templates. To enforce them, run `install_hooks.py` from the installed skill directory so the generated hook command points to absolute guard script paths. Do not copy the example command verbatim into another repository; `python skills/e2e-dev-harness/scripts/phase_guard.py ...` only works when that repository contains the skill source tree. Codex and Gemini enforcement still depends on whether the host runner exposes a blocking pre-action/pre-tool hook.
For one-command setup from the harness source repository, prefer the bootstrap
installer with `--project <business-repo> --yes`; this updates the skill
runtime copy, writes the hook config into the business repository instead of the
harness source repository, and runs `doctor`. Use `--hooks-only` when the skill
copy is already current and only hook wiring needs repair.
You can also install or check project-local hook configuration with:

```powershell
python skills\e2e-dev-harness\scripts\install_hooks.py . --runtime claude --json
python skills\e2e-dev-harness\scripts\install_hooks.py . --runtime claude --check --json
python skills\e2e-dev-harness\scripts\install_hooks.py . --runtime opencode --json
python skills\e2e-dev-harness\scripts\install_hooks.py . --runtime opencode --check --json
```

The installed Claude hooks use two guards. The first argument is the target repository, not the current shell directory.

Code exploration/write guard:

```powershell
"C:\absolute\path\to\python.exe" "C:\absolute\path\to\skills\e2e-dev-harness\scripts\phase_guard.py" "C:\absolute\path\to\target-repo" --hook-input - --require-active-run-for-read --require-session-checkpoint --checkpoint-max-age-minutes 30 --json
```

Stop/finalization guard:

```powershell
"C:\absolute\path\to\python.exe" "C:\absolute\path\to\skills\e2e-dev-harness\scripts\harness_stop_guard.py" "C:\absolute\path\to\target-repo" --hook-input - --strict --json
```

`phase_guard.py` reads `docs/agent-runs/<run>/.phase-lock`. With `--require-active-run-for-read`, code `Read`/`Grep`/`Glob` is blocked until `start` creates an active run, and dispatch-gated phases require an active worker before code exploration. Red-test writes under `src/test`, `test`, or `tests` during `PLANNED` require an active `test-case-developer`; runtime production and test writes during `IMPLEMENTED` require an active `code-developer`. `IMPLEMENTED` must come from run-state transition history with ready implementation-gate evidence; editing `.phase-lock` and `run-state.json` by hand is blocked. In multi-service runs it also requires a claimed service code-developer task for runtime code writes in the touched service/module. It recognizes direct file tools including Claude `Update`, `apply_patch`, common shell write commands, and inline Python/Node/PowerShell mutation patterns; unknown tools touching code paths fail closed. Harness artifacts under `docs/agent-runs/` may be written before implementation except control files such as `.phase-lock`, `run-state.json`, `artifact-registry.json`, and `agent-schedule.json`.

With `--require-session-checkpoint`, production/test code writes also require a fresh `session-checkpoint.json` produced by `e2e_dev_harness.py next`. If run-state changes or the checkpoint ages out, the hook blocks and forces the agent to reload the state machine before continuing.

`harness_stop_guard.py` is wired to Claude Code `Stop` with `--strict`. It blocks Claude from ending a run while lifecycle is non-terminal, or while the post-code run still has open scheduled tasks. A run directory without `run-state.json` blocks only when it contains files; empty stale scaffold directories are ignored with a warning. This is the guard that prevents "compiled successfully, summary emitted, R2/R3/completion skipped" behavior.

### Claude Code

1. Create `.claude/` in the target repository if it does not exist.
2. Merge this file into `.claude/settings.json`:

```text
skills/e2e-dev-harness/hooks/claude-code-settings.example.json
```

Minimal project config:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read|Grep|Glob|Task|TaskCreate|Write|Edit|Update|MultiEdit|NotebookEdit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "\"C:\\absolute\\path\\to\\python.exe\" \"C:\\absolute\\path\\to\\skills\\e2e-dev-harness\\scripts\\phase_guard.py\" \"C:\\absolute\\path\\to\\target-repo\" --hook-input - --require-active-run-for-read --require-session-checkpoint --checkpoint-max-age-minutes 30 --json"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "\"C:\\absolute\\path\\to\\python.exe\" \"C:\\absolute\\path\\to\\skills\\e2e-dev-harness\\scripts\\harness_stop_guard.py\" \"C:\\absolute\\path\\to\\target-repo\" --hook-input - --strict --json"
          }
        ]
      }
    ]
  }
}
```

3. Restart Claude Code or reload project settings.
4. Verify with the manual check below.

### Codex

Codex runtimes differ by host. If your Codex runner supports pre-action hook configuration, merge:

```text
skills/e2e-dev-harness/hooks/codex-pre-action.example.json
```

The intended mapping is:

```json
{
  "event": "pre-action",
  "tools": ["Read", "Grep", "Glob", "Write", "Edit", "MultiEdit", "NotebookEdit"],
  "command": "\"C:\\absolute\\path\\to\\python.exe\" \"C:\\absolute\\path\\to\\skills\\e2e-dev-harness\\scripts\\phase_guard.py\" \"C:\\absolute\\path\\to\\target-repo\" --hook-input - --require-active-run-for-read --json",
  "blocking": true
}
```

If the Codex host does not expose pre-action hooks, use `phase_guard.py` or the portable `pre-code` command in the local wrapper or CI before allowing file-write steps, and always run `e2e_dev_harness.py guard` over the saved verify result.

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py pre-code . `
  --tool Edit `
  --path services\payment-service\src\main\java\PaymentService.java `
  --run-dir docs\agent-runs\<run>
```

### Gemini CLI

If your Gemini runner supports pre-tool hooks, merge:

```text
skills/e2e-dev-harness/hooks/gemini-pre-action.example.json
```

The intended mapping is:

```json
{
  "event": "pre-tool-use",
  "tools": ["read_file", "grep", "glob", "write_file", "replace", "edit", "multi_edit"],
  "command": "\"C:\\absolute\\path\\to\\python.exe\" \"C:\\absolute\\path\\to\\skills\\e2e-dev-harness\\scripts\\phase_guard.py\" \"C:\\absolute\\path\\to\\target-repo\" --hook-input - --require-active-run-for-read --json",
  "blocking": true
}
```

If the runner uses different tool names, keep the command and update only the tool matcher list.

### OpenCode

Install the project plugin instead of copying the template by hand:

```powershell
python skills\e2e-dev-harness\scripts\install_hooks.py . --runtime opencode --json
```

This writes:

```text
.opencode/plugins/e2e-dev-harness.js
```

The plugin registers `tool.execute.before`, passes OpenCode tool input to `phase_guard.py`, normalizes common path fields such as `filePath` and `patchText`, and throws on guard failure so the tool execution is blocked. It includes `--require-active-run-for-read` and `--require-session-checkpoint`; run `e2e_dev_harness.py start` and `e2e_dev_harness.py next` before code exploration or edits.

For role isolation, keep reviewer and design agents with write permissions disabled in OpenCode agent configuration. Code agents may receive edit permission, but the plugin remains the phase/scope gate.

### Post-Gate Transition Adapter

When a runtime can run post-tool hooks, use `auto_transition.py` after a gate status file is written. It advances state only from a ready gate status artifact; it does not bypass `gate`.

```powershell
python skills\e2e-dev-harness\scripts\auto_transition.py . `
  --status-file docs\agent-runs\<run>\evidence\implementation-gate.json `
  --state docs\agent-runs\<run>\run-state.json `
  --json
```

## Verify Hook Behavior

Create or locate a run archive, then check a code write before implementation:

```powershell
"C:\absolute\path\to\python.exe" "C:\absolute\path\to\skills\e2e-dev-harness\scripts\phase_guard.py" "C:\absolute\path\to\target-repo" `
  --tool Edit `
  --path services\payment-service\src\main\java\PaymentService.java `
  --run-dir docs\agent-runs\<run> `
  --json
```

Expected before implementation:

```json
{
  "ready": false
}
```

Check the stop guard after code is implemented but before R3/completion:

```powershell
"C:\absolute\path\to\python.exe" "C:\absolute\path\to\skills\e2e-dev-harness\scripts\harness_stop_guard.py" "C:\absolute\path\to\target-repo" `
  --run-dir docs\agent-runs\<run> `
  --json
```

Expected while lifecycle is `IMPLEMENTED`:

```json
{
  "ready": false
}
```

Open the implementation phase through the implementation gate after required planning/red-test evidence exists. The gate updates `run-state.json` and `.phase-lock` automatically when it passes:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py gate . `
  --phase implementation `
  --run-state docs\agent-runs\<run>\run-state.json `
  --design-doc docs\design\<feature>.md `
  --kg-status-file docs\agent-runs\<run>\evidence\knowledge-graph-refresh.json `
  --review-dir docs\agent-runs\<run>\reviews `
  --red-test-evidence docs\agent-runs\<run>\evidence\red-test.txt `
  --json
```

Manual `run_state.py --transition IMPLEMENTED` is blocked unless it includes `--gate implementation`, `--gate-status passed`, and existing implementation-gate evidence. Prefer rerunning the gate; use manual transition only to repair a previously successful gate status write failure.

Run the same `phase_guard.py` command again. Expected:

```json
{
  "ready": true
}
```

## Intent And Checkpoints

For high-risk work, require user-intent anchoring before planning:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py clarify . `
  --design-doc docs\design\<feature>.md `
  --require-intent
```

The design must include `Restated Intent`, written in the agent's own words, before the user confirms it. Store phase confirmations under `docs\agent-runs\<run>\confirmations\` and require them at gates:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py gate . `
  --phase implementation `
  --checkpoint-mode required `
  --confirmation-dir docs\agent-runs\<run>\confirmations
```

Use `--checkpoint-mode advisory` when non-interactive CI should report missing confirmations without blocking.

## Command Evidence

Use `command_evidence.py` for Maven, GitNexus, security, or custom verification commands when evidence must include command, exit code, elapsed time, output hashes, and environment metadata:

```powershell
python skills\e2e-dev-harness\scripts\command_evidence.py . `
  --command "mvn test" `
  --output docs\agent-runs\<run>\evidence\maven-test.json
```

## TDD Modes

Use scenario-based TDD enforcement:

| Scenario | Mode | Evidence |
| --- | --- | --- |
| small/simple change | `--tdd-mode auto` resolves to `basic` | non-empty red evidence that names the expected failing test or failure reason |
| normal standard requirement | `--tdd-mode auto` resolves to `basic` plus R2/R3 reviews | red evidence, green unit-test JSON, coverage matrix |
| API/MQ/payment/data/security/cross-service | `--tdd-mode auto` resolves to `strict` when the workflow tier is `critical` or `audited` | red command JSON with non-zero exit code, green command JSON with zero exit code |
| audit/compliance run | `--tdd-mode strict` | strict red/green evidence plus trace and replay |

`auto` is the default. The gate reads the design and dependency report to classify the workflow tier; high-risk API/MQ/payment/data/security/cross-service work cannot silently pass with lightweight post-hoc test notes.

## Harness Replay

Replay a run and write summary artifacts:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py verify . `
  --harness `
  --workflow-tier critical `
  --state docs\agent-runs\<run>\run-state.json `
  --strict-workflow `
  --summary-json docs\agent-runs\<run>\run-summary.json `
  --summary-md docs\agent-runs\<run>\run-summary.md `
  --json
```

Record phase timing and optional token usage during `verify`:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py verify . `
  --skip-maven `
  --trace-file docs\agent-runs\<run>\execution-trace.json `
  --json
```

Refresh the artifact registry after planned files are written:

```powershell
python skills\e2e-dev-harness\scripts\artifact_registry.py . `
  --registry docs\agent-runs\<run>\artifact-registry.json `
  --refresh `
  --json
```

## CI Guard

`workflow_guard.py` and `e2e_dev_harness.py guard` return exit code `0` when ready and `2` when blocked.

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py guard . `
  --verify-status docs\agent-runs\<run>\evidence\verify.json `
  --strict `
  --require-completion `
  --json
```

Use this in pre-push or CI after the implementation gate writes a verify status artifact.
For GitHub Actions, copy and edit:

```text
skills/e2e-dev-harness/ci/github-actions-harness.yml
```

The bundled workflow targets `windows-latest` because this harness is maintained for Windows-first Java/Maven projects.

Strict completion also validates phase coverage. A run is blocked if plan did not create harness state, R1/R2/R3 reviews are missing, TDD red/green evidence is absent, completion gate was skipped, or the strict guard result is not saved for final reporting. Save guard output into the run evidence directory:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py guard . `
  --verify-status docs\agent-runs\<run>\evidence\verify.json `
  --strict `
  --require-completion `
  --status-file docs\agent-runs\<run>\evidence\strict-guard.json `
  --json
```

## Development Checks

Run the local test suite:

```powershell
python -m unittest discover -s tests
python -m compileall -q skills\e2e-dev-harness\scripts
git diff --check
```
