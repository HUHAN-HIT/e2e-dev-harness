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

Use the Node bootstrap installer when setting up the skill for an agent runtime.
It is a dry run by default and only writes files or runs install commands when
`--yes` is supplied:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target codex `
  --install-root $env:USERPROFILE `
  --skip-python-cli `
  --json
```

Install the skill plus the editable Python CLI:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target codex `
  --install-root $env:USERPROFILE `
  --yes
```

External tools are conservative by default. GitNexus and Graphify are detected
but not installed unless `--install-external` is provided. Superpowers is
probed as a skill/plugin capability; use `--strict-superpowers` to fail the
installer when required Superpowers skills are missing.

Install the local harness entry point when working from this repository:

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

Multi-service `plan --create-archive` writes run-state lifecycle `SERVICE_DESIGN_REQUIRED`. Validate the service slices before R2/TDD red or dispatching code agents; the command below transitions the run-state to `PLANNED` only when every global AC is mapped into concrete service slices with runtime path, first red test, expected failure, required Maven command, dependency boundary, and test impact:

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

If this blocks on `AC-2`, continue TDD red/green for `AC-2`; do not ask whether to start R3.

## Hook Configuration

The hook examples are templates. To enforce them, run `install_hooks.py` from the installed skill directory so the generated hook command points to absolute guard script paths. Do not copy the example command verbatim into another repository; `python skills/e2e-dev-harness/scripts/phase_guard.py ...` only works when that repository contains the skill source tree. Codex and Gemini enforcement still depends on whether the host runner exposes a blocking pre-action/pre-tool hook.
You can also install or check project-local hook configuration with:

```powershell
python skills\e2e-dev-harness\scripts\install_hooks.py . --runtime claude --json
python skills\e2e-dev-harness\scripts\install_hooks.py . --runtime claude --check --json
```

The installed Claude hooks use two guards. The first argument is the target repository, not the current shell directory.

Code exploration/write guard:

```powershell
"C:\absolute\path\to\python.exe" "C:\absolute\path\to\skills\e2e-dev-harness\scripts\phase_guard.py" "C:\absolute\path\to\target-repo" --hook-input - --require-active-run-for-read --require-session-checkpoint --checkpoint-max-age-minutes 30 --json
```

Stop/finalization guard:

```powershell
"C:\absolute\path\to\python.exe" "C:\absolute\path\to\skills\e2e-dev-harness\scripts\harness_stop_guard.py" "C:\absolute\path\to\target-repo" --hook-input - --json
```

`phase_guard.py` reads `docs/agent-runs/<run>/.phase-lock`. With `--require-active-run-for-read`, code `Read`/`Grep`/`Glob` is blocked until `start` creates an active run. It allows red-test writes under `src/test`, `test`, or `tests` during `PLANNED`/`RED_READY`, but blocks runtime production code until lifecycle `IMPLEMENTED`. `IMPLEMENTED` must come from run-state transition history with ready implementation-gate evidence; editing `.phase-lock` and `run-state.json` by hand is blocked. In multi-service runs it also requires a claimed service code-developer task for runtime code writes in the touched service/module. It recognizes direct file tools including Claude `Update`, `apply_patch`, common shell write commands, and inline Python/Node/PowerShell mutation patterns; unknown tools touching code paths fail closed. Harness artifacts under `docs/agent-runs/` may be written before implementation except control files such as `.phase-lock`, `run-state.json`, `artifact-registry.json`, and `agent-schedule.json`.

With `--require-session-checkpoint`, production/test code writes also require a fresh `session-checkpoint.json` produced by `e2e_dev_harness.py next`. If run-state changes or the checkpoint ages out, the hook blocks and forces the agent to reload the state machine before continuing.

`harness_stop_guard.py` is wired to Claude Code `Stop`. It blocks Claude from ending a run while lifecycle is `IMPLEMENTED`, `REVIEWED`, or `REWORK_REQUIRED`, or while the post-code run still has open scheduled tasks. This is the guard that prevents "compiled successfully, summary emitted, R2/R3/completion skipped" behavior.

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
        "matcher": "Read|Grep|Glob|Write|Edit|Update|MultiEdit|NotebookEdit|Bash",
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
            "command": "\"C:\\absolute\\path\\to\\python.exe\" \"C:\\absolute\\path\\to\\skills\\e2e-dev-harness\\scripts\\harness_stop_guard.py\" \"C:\\absolute\\path\\to\\target-repo\" --hook-input - --json"
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
