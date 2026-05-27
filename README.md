# E2E Dev Harness

This repository contains an agent-neutral delivery harness for serious Java/Spring/Maven requirement implementation. It is designed for Codex, Claude Code, Gemini CLI, OpenCode, CI jobs, and any runtime that can read `SKILL.md` and execute the bundled Python scripts.

The harness is not just process documentation. It provides machine-checkable gates, run-state files, artifact registries, replay verification, workflow tiers, review profiles, and optional pre-action hooks that can block code writes before the implementation phase.

## Layout

```text
skills/e2e-dev-harness/
  SKILL.md
  hooks/
    claude-code-settings.example.json
    codex-pre-action.example.json
    gemini-pre-action.example.json
  references/
    execution-control.md
    implementation-gates.md
    common-review-issues.md
    ...
  review-profiles/
  scripts/
    e2e_dev_workflow.py
    phase_guard.py
    run_state.py
    artifact_registry.py
    harness_verify.py
    run_summary.py
    task_tier.py
    ...
tests/
  test_e2e_dev_workflow_scripts.py
```

## Quick Start

Run discovery before implementation:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_workflow.py prepare . `
  --design-doc docs\design\<feature>.md `
  --workflow-tier auto `
  --agent-mode strict `
  --agent-scope discovery `
  --service-scope discovery `
  --include-agent-content
```

After affected services or paths are known, create an agent-run archive:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_workflow.py plan . `
  --design-doc docs\design\<feature>.md `
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
| `basic` | Small scoped delivery work | clarification, bounded impact summary, test evidence, completion proof, run-state, artifact registry, run summary |
| `standard` | Normal requirement implementation | `basic` plus R1/R2/R3 reviews, coverage matrix, requirements archive |
| `critical` | MQ/HTTP/DB/security/payment/refund/cross-service work | `standard` plus GitNexus impact artifact, contracts, service plans, handoffs, strict guard |
| `audited` | Audit, compliance, incident, or production-critical work | `critical` plus harness policy, harness replay, completion replay, state history |

## Hook Configuration

The hook examples are templates. To enforce them, copy or merge the matching file into the target runtime's project hook configuration.

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

If the Codex host does not expose pre-action hooks, use `phase_guard.py` in the local wrapper or CI before allowing file-write steps, and always run `e2e_dev_workflow.py guard` over the saved verify result.

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

Move the run into implementation phase after required planning/red-test evidence exists:

```powershell
python skills\e2e-dev-harness\scripts\run_state.py . `
  --state docs\agent-runs\<run>\run-state.json `
  --transition IMPLEMENTED `
  --gate implementation `
  --gate-status started `
  --evidence docs\agent-runs\<run>\evidence\red-test.txt `
  --json
```

Run the same `phase_guard.py` command again. Expected:

```json
{
  "ready": true
}
```

## Harness Replay

Replay a run and write summary artifacts:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_workflow.py verify . `
  --harness `
  --workflow-tier critical `
  --state docs\agent-runs\<run>\run-state.json `
  --strict-workflow `
  --summary-json docs\agent-runs\<run>\run-summary.json `
  --summary-md docs\agent-runs\<run>\run-summary.md `
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

`workflow_guard.py` and `e2e_dev_workflow.py guard` return exit code `0` when ready and `2` when blocked.

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_workflow.py guard . `
  --verify-status docs\agent-runs\<run>\evidence\verify.json `
  --strict `
  --require-completion `
  --json
```

Use this in pre-push or CI after the implementation gate writes a verify status artifact.

## Development Checks

Run the local test suite:

```powershell
python -m unittest discover -s tests
python -m compileall -q skills\e2e-dev-harness\scripts
git diff --check
```
