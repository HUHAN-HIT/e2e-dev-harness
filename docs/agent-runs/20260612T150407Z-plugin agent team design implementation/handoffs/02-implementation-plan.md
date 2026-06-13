# Plugin Agent Team Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for all production-code changes. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement plugin-style agent-team planning for `skills/e2e-dev-harness` while preserving current runtime adapter and dispatch compatibility.

**Architecture:** Add a pure `e2e_harness.adapters.agent_team` package that expands lifecycle phases into worker packets. Runtime adapters remain responsible only for turning one worker packet into a runtime descriptor. Dispatch becomes team-aware but keeps legacy single-worker response fields for existing callers.

**Tech Stack:** Python stdlib, existing `e2e_harness` modules, YAML profile files parsed through available project YAML support, pytest.

---

## File Structure

- Create `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/__init__.py`: public exports for provider registry helpers.
- Create `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/base.py`: protocol-like provider contract and request/plan helper types.
- Create `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/builtin.py`: deterministic builtin provider that performs single-worker parity and evidence-key fan-out.
- Create `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/registry.py`: bundled/project-local profile loading and provider selection.
- Create `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/schema.py`: profile validation with path and field errors.
- Create `skills/e2e-dev-harness/agent-teams/default-minimal.yaml`
- Create `skills/e2e-dev-harness/agent-teams/default-standard.yaml`
- Create `skills/e2e-dev-harness/agent-teams/default-critical.yaml`
- Create `skills/e2e-dev-harness/agent-teams/default-audited.yaml`
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/adapters/runtime/__init__.py`: support packet-level `runtime_subagent_type` under existing env precedence.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py`: select provider/profile, write agent-team plan and dispatch invocation artifacts, emit one or more descriptors.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/core/dispatch.py`: only if a worker-packet helper needs optional `runtime_subagent_type`.
- Modify CLI parser file discovered during implementation to add `--team-profile`, `--max-workers`, and optional JSON behavior only if not already present.
- Create `skills/e2e-dev-harness/tests/test_agent_team_provider.py`
- Create `skills/e2e-dev-harness/tests/test_agent_team_dispatch.py`
- Create `skills/e2e-dev-harness/tests/test_agent_team_profiles.py`
- Extend `skills/e2e-dev-harness/tests/test_runtime_spawn.py`
- Extend `skills/e2e-dev-harness/tests/test_runtime_adapter_contract.py`
- Extend `skills/e2e-dev-harness/tests/test_review_fanout.py`
- Update `skills/e2e-dev-harness/SKILL.md`
- Update `skills/e2e-dev-harness/references/agent-orchestration.md`

## Required GitNexus Impact Before Editing

- Before editing `runtime.__init__`, run impact for `_subagent_type`, `_claude_code`, and `_opencode`.
- Before editing `cli/commands/dispatch.py`, run impact for `run` with file path `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py`.
- Before editing `core/dispatch.py`, run impact for `worker_packet`.
- If parser changes are needed, identify the parser symbol with GitNexus context/query, then run upstream impact before editing it.
- If docs only change, no symbol impact is required, but run `gitnexus_detect_changes(scope="all")` before any commit.

## Task 1: Provider Parity Red Tests

**Files:**
- Create: `skills/e2e-dev-harness/tests/test_agent_team_provider.py`
- Later create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/__init__.py`
- Later create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/base.py`
- Later create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/builtin.py`

- [ ] **Step 1: Write failing provider parity tests**

```python
from pathlib import Path

from e2e_harness import pipeline
from e2e_harness.adapters.agent_team import builtin
from e2e_harness.core import dispatch


def _request(phase, tmp_path: Path, **overrides):
    base = {
        "schema": "e2e-dev-harness.agent-team-request.v1",
        "run_state_path": "docs/agent-runs/r1/run-state.json",
        "repo_root": str(tmp_path),
        "runtime": "codex",
        "pipeline": "standard",
        "phase": {
            "name": phase.name,
            "worker_role": phase.worker_role,
            "worker_skill": phase.worker_skill,
            "produces": list(phase.produces),
            "exit_gate": list(phase.exit_gate),
            "allows_code_write": phase.allows_code_write,
        },
        "context_paths": ["docs/agent-runs/r1/run-state.json"],
        "team_profile": "default-standard",
        "constraints": {"max_workers": 1, "fresh_context": True, "allow_code_write": False},
    }
    base.update(overrides)
    return base


def test_builtin_provider_matches_worker_packet_for_single_worker_phase(tmp_path):
    phase = next(p for p in pipeline.build_spine("standard") if p.name == "PLANNED")
    plan = builtin.BuiltinAgentTeamProvider().plan_phase(_request(phase, tmp_path))
    expected = dispatch.worker_packet(phase, "docs/agent-runs/r1/run-state.json")

    assert plan["schema"] == "e2e-dev-harness.agent-team-plan.v1"
    assert plan["provider"] == "builtin"
    assert plan["profile"] == "default-standard"
    assert plan["phase"] == "PLANNED"
    assert len(plan["workers"]) == 1
    worker = plan["workers"][0]
    assert worker["role"] == expected["role"]
    assert worker["skill"] == expected["skill"]
    assert worker["context_paths"] == expected["context_paths"]
    assert worker["expected_outputs"] == expected["expected_outputs"]


def test_builtin_provider_is_pure_and_does_not_touch_run_state(tmp_path):
    phase = next(p for p in pipeline.build_spine("standard") if p.name == "PLANNED")
    run_state = tmp_path / "run-state.json"
    run_state.write_text('{"current_phase": "PLANNED"}', encoding="utf-8")
    before = run_state.read_text(encoding="utf-8")

    plan = builtin.BuiltinAgentTeamProvider().plan_phase(
        _request(phase, tmp_path, run_state_path=str(run_state))
    )

    assert plan["workers"]
    assert run_state.read_text(encoding="utf-8") == before
```

- [ ] **Step 2: Run red test**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_agent_team_provider.py -q`

Expected: FAIL with `ModuleNotFoundError` or import error for `e2e_harness.adapters.agent_team`.

## Task 2: Provider Parity Implementation

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/__init__.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/base.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/builtin.py`

- [ ] **Step 1: Add minimal provider package**

Implement `BuiltinAgentTeamProvider.plan_phase(request)` to:

- Validate request schema string.
- Copy phase role, skill, context paths, and produces into one worker.
- Include `evidence_contract.required_keys`.
- Return schema `e2e-dev-harness.agent-team-plan.v1`.

- [ ] **Step 2: Run provider tests**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_agent_team_provider.py -q`

Expected: PASS for provider parity and purity tests.

## Task 3: Runtime Subagent Override Red Tests

**Files:**
- Modify: `skills/e2e-dev-harness/tests/test_runtime_spawn.py`
- Modify: `skills/e2e-dev-harness/tests/test_runtime_adapter_contract.py`
- Later modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/runtime/__init__.py`

- [ ] **Step 1: Write failing runtime tests**

Add tests proving:

- Claude Code uses packet `runtime_subagent_type` when no env override exists.
- OpenCode uses packet `runtime_subagent_type` when no env override exists.
- Env override still wins for both runtimes.
- Codex ignores this field and remains model-unpinned.

- [ ] **Step 2: Run red tests**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_runtime_spawn.py skills/e2e-dev-harness/tests/test_runtime_adapter_contract.py -q`

Expected: FAIL because `_subagent_type` does not read the packet.

## Task 4: Runtime Subagent Override Implementation

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/runtime/__init__.py`

- [ ] **Step 1: Run required GitNexus impact**

Run MCP impact on `_subagent_type`, `_claude_code`, and `_opencode`, upstream, repo `e2e-dev-workflow`.

Expected: Report risk and direct callers before editing. Warn before continuing if HIGH or CRITICAL.

- [ ] **Step 2: Implement packet fallback**

Change `_subagent_type(role)` to `_subagent_type(role, packet=None)`, return env override first, then packet `runtime_subagent_type`, then `PORTABLE_SUBAGENT_TYPE`. Pass the packet from `_claude_code` and `_opencode`.

- [ ] **Step 3: Run green tests**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_runtime_spawn.py skills/e2e-dev-harness/tests/test_runtime_adapter_contract.py -q`

Expected: PASS.

## Task 5: Profile Schema and Builtin Profiles Red Tests

**Files:**
- Create: `skills/e2e-dev-harness/tests/test_agent_team_profiles.py`
- Later create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/schema.py`
- Later create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/registry.py`
- Later create: `skills/e2e-dev-harness/agent-teams/default-*.yaml`

- [ ] **Step 1: Write failing profile tests**

Cover deterministic bundled profile loading, explicit project-local profile loading, no silent override, and invalid profile errors that include path and field.

- [ ] **Step 2: Run red tests**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_agent_team_profiles.py -q`

Expected: FAIL because registry/schema/profile files do not exist.

## Task 6: Profile Schema and Registry Implementation

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/schema.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/registry.py`
- Create: `skills/e2e-dev-harness/agent-teams/default-minimal.yaml`
- Create: `skills/e2e-dev-harness/agent-teams/default-standard.yaml`
- Create: `skills/e2e-dev-harness/agent-teams/default-critical.yaml`
- Create: `skills/e2e-dev-harness/agent-teams/default-audited.yaml`

- [ ] **Step 1: Implement minimal schema validator**

Validate required top-level fields: `schema`, `name`, `roles`. Validate role `skill`, `runtime_subagent_type`, and positive integer `max_workers` when present. Validate phase worker overrides when present.

- [ ] **Step 2: Implement registry**

Load bundled profiles from `skills/e2e-dev-harness/agent-teams`. Allow project-local `.e2e/agent-teams/<name>.yaml` only when an explicit name is requested.

- [ ] **Step 3: Run profile tests**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_agent_team_profiles.py -q`

Expected: PASS.

## Task 7: Review Fan-Out Red Tests

**Files:**
- Modify: `skills/e2e-dev-harness/tests/test_agent_team_provider.py`
- Modify: `skills/e2e-dev-harness/tests/test_review_fanout.py`
- Later modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/builtin.py`

- [ ] **Step 1: Add fan-out tests**

Assert critical/audited `REVIEWED` phase plans produce workers:

- `REVIEWED-r1` with `expected_outputs == ["r1_review"]`
- `REVIEWED-r2` with `expected_outputs == ["r2_review"]`
- `REVIEWED-r3` with `expected_outputs == ["r3_review"]`

- [ ] **Step 2: Run red tests**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_agent_team_provider.py skills/e2e-dev-harness/tests/test_review_fanout.py -q`

Expected: FAIL until provider reads phase/profile fan-out.

## Task 8: Review Fan-Out Implementation

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/builtin.py`
- Modify: `skills/e2e-dev-harness/agent-teams/default-critical.yaml`
- Modify: `skills/e2e-dev-harness/agent-teams/default-audited.yaml`

- [ ] **Step 1: Implement evidence-key fan-out**

For profile phase strategy `evidence-key-fanout`, expand configured workers and assign each worker one expected output. Include stable ids, parallel groups, and producer ids in evidence contract.

- [ ] **Step 2: Run fan-out tests**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_agent_team_provider.py skills/e2e-dev-harness/tests/test_review_fanout.py -q`

Expected: PASS.

## Task 9: Dispatch Red Tests

**Files:**
- Create: `skills/e2e-dev-harness/tests/test_agent_team_dispatch.py`
- Later modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py`
- Later modify parser file discovered in CLI package if extra flags are needed.

- [ ] **Step 1: Write failing dispatch tests**

Cover:

- Default single-worker dispatch preserves legacy `role`, `skill`, `expected_outputs`, and `worker_descriptor`.
- Critical/audited `REVIEWED` dispatch emits multiple descriptors and an `agent_team_plan`.
- Manual runtime with team plan returns `dispatch_blocked` and does not mark state dispatch.
- Dispatch writes `agent-team-plan.json` and a `dispatch-invocations/*.json` record.

- [ ] **Step 2: Run red tests**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_agent_team_dispatch.py -q`

Expected: FAIL because dispatch does not consume agent-team plans.

## Task 10: Dispatch Implementation

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py`
- Modify: CLI parser file if adding flags is needed.
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/dispatch.py` only if helper extension is needed.

- [ ] **Step 1: Run required GitNexus impact**

Run MCP impact on `run` in dispatch command and `worker_packet` before editing those symbols.

Expected: Report risk and affected callers. Warn before continuing if HIGH or CRITICAL.

- [ ] **Step 2: Implement team-aware dispatch**

Use registry/provider to build a phase plan. Spawn descriptors through the existing runtime adapter for every ready worker. Preserve legacy top-level single worker fields when exactly one worker exists.

- [ ] **Step 3: Write artifacts**

Write `docs/agent-runs/<run>/agent-team-plan.json` and `docs/agent-runs/<run>/dispatch-invocations/<phase>-<timestamp>.json` with descriptor summaries and blocked records.

- [ ] **Step 4: Run dispatch tests**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_agent_team_dispatch.py skills/e2e-dev-harness/tests/test_dispatch.py skills/e2e-dev-harness/tests/test_cli_e2e.py -q`

Expected: PASS.

## Task 11: Documentation and Sync

**Files:**
- Modify: `skills/e2e-dev-harness/SKILL.md`
- Modify: `skills/e2e-dev-harness/references/agent-orchestration.md`

- [ ] **Step 1: Update docs**

Document the boundary: lifecycle decides evidence, agent team decides workers, runtime adapter decides descriptors, gates decide transitions.

- [ ] **Step 2: Run installer sync**

Run: `node tools\install-e2e-dev-harness.mjs --sync --yes --json`

Expected: Exit 0 and installed-copy metadata updated as intended.

## Task 12: Final Verification

**Files:**
- All changed implementation, test, docs, and profile files.

- [ ] **Step 1: Run focused suites**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_runtime_spawn.py
python -m pytest skills/e2e-dev-harness/tests/test_runtime_adapter_contract.py
python -m pytest skills/e2e-dev-harness/tests/test_agent_team_provider.py
python -m pytest skills/e2e-dev-harness/tests/test_agent_team_profiles.py
python -m pytest skills/e2e-dev-harness/tests/test_agent_team_dispatch.py
python -m pytest skills/e2e-dev-harness/tests/test_dispatch.py
python -m pytest skills/e2e-dev-harness/tests/test_cli_e2e.py
```

Expected: All pass.

- [ ] **Step 2: Run harness verification evidence commands**

Capture passing tests as `passing_tests`, test substance manifest, final `verification`, and audited `audit_replay` evidence in the run directory using existing command-evidence utilities or accepted harness evidence format.

- [ ] **Step 3: Run GitNexus change detection**

Run: `gitnexus_detect_changes({ repo: "e2e-dev-workflow", scope: "all" })`

Expected: Affected symbols and flows match runtime adapter, agent-team provider, dispatch, tests, docs, and profile files.

- [ ] **Step 4: Run broad safety check**

Run: `python -m pytest skills/e2e-dev-harness/tests`

Expected: PASS, or document any pre-existing unrelated failures with evidence.

## Self-Review

- Spec coverage: AC-001 through AC-011 map to Tasks 1-12.
- Placeholder scan: no TBD/TODO/fill-later placeholders remain.
- Type consistency: request schema, plan schema, worker packet schema, and runtime descriptor fields match the approved design document.
