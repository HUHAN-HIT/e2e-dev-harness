# E2E Dev Harness

This repository contains an agent-neutral delivery harness for serious Java/Spring/Maven requirement implementation. It is designed for Codex, Claude Code, Gemini CLI, OpenCode, CI jobs, and any runtime that can read `SKILL.md` and execute the bundled Python scripts.

The harness is not just process documentation. It provides machine-checkable gates, run-state files, agent schedules, artifact registries, replay verification, workflow tiers, review profiles, and optional pre-action hook templates that can block code writes before the implementation phase when the active agent runtime actually supports blocking hooks.

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
    auto_transition.py
    run_state.py
    artifact_registry.py
    harness_verify.py
    run_summary.py
    execution_trace.py
    checkpoint_gate.py
    command_evidence.py
    tdd_evidence.py
    task_tier.py
    task_alignment_guard.py
    ...
tests/
  test_e2e_dev_harness_scripts.py
```

## Quick Start

Create a controlled run before analysis or implementation. This writes the
starter design artifact, run-state, `.phase-lock`, artifact registry, and
agent schedule. Production code writes stay locked until the implementation
gate passes.

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py start . `
  --feature "<feature>" `
  --request "<original user request>"
```

Ask the harness what is allowed next:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py next . `
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
  review-requests/
  reviews/
  evidence/
```

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

## Hook Configuration

The hook examples are templates. To enforce them, copy or merge the matching file into the target runtime's project hook configuration. `install_hooks.py` can place or validate project-local files, but Codex and Gemini enforcement still depends on whether the host runner exposes a blocking pre-action/pre-tool hook.
You can also install or check project-local hook configuration with:

```powershell
python skills\e2e-dev-harness\scripts\install_hooks.py . --runtime claude --json
python skills\e2e-dev-harness\scripts\install_hooks.py . --runtime claude --check --json
```

All examples call the same guard:

```powershell
python skills\e2e-dev-harness\scripts\phase_guard.py . --hook-input - --json
```

`phase_guard.py` reads `docs/agent-runs/<run>/.phase-lock` and blocks code-writing tools unless the lifecycle is `IMPLEMENTED`. It still allows harness artifacts under `docs/agent-runs/` to be written before implementation.

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
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python skills/e2e-dev-harness/scripts/phase_guard.py . --hook-input - --json"
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
  "tools": ["Write", "Edit", "MultiEdit", "NotebookEdit"],
  "command": "python skills/e2e-dev-harness/scripts/phase_guard.py . --hook-input - --json",
  "blocking": true
}
```

If the Codex host does not expose pre-action hooks, use `phase_guard.py` in the local wrapper or CI before allowing file-write steps, and always run `e2e_dev_harness.py guard` over the saved verify result.

### Gemini CLI

If your Gemini runner supports pre-tool hooks, merge:

```text
skills/e2e-dev-harness/hooks/gemini-pre-action.example.json
```

The intended mapping is:

```json
{
  "event": "pre-tool-use",
  "tools": ["write_file", "replace", "edit", "multi_edit"],
  "command": "python skills/e2e-dev-harness/scripts/phase_guard.py . --hook-input - --json",
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
python skills\e2e-dev-harness\scripts\phase_guard.py . `
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

Use `run_state.py --transition IMPLEMENTED` only as an explicit repair command when a previously successful gate did not write the transition.

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
