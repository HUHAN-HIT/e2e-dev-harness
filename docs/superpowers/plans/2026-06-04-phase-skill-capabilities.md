# Phase Skill Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current monolithic `e2e-dev-harness` skill into a control-plane skill that dispatches phase-specific worker skills without weakening deterministic gates, role isolation, or evidence contracts.

**Architecture:** Keep `skills/e2e-dev-harness/SKILL.md` as the coordinator/control-plane entrypoint. Add phase capability metadata to scheduled tasks, context packs, runtime spawn requests, and role templates, then introduce small worker skills for clarification, planning, TDD red, implementation, review, and completion. Gates and scripts remain authoritative; worker skills only describe stage-local behavior and bounded inputs.

**Tech Stack:** Python stdlib harness scripts, Markdown skills, GitNexus evidence, `unittest`, existing `agent-schedule.json`, context packs, runtime adapters, handoff ready markers.

---

## Target Outcomes

1. The coordinator loads only the core harness skill and control-plane references during normal dispatch.
2. Each scheduled worker task declares a machine-readable phase capability such as `e2e-clarification`, `e2e-tdd-red`, or `e2e-implementation`.
3. Context packs and spawn prompts expose the required worker skill and the minimal reference set for that phase.
4. Worker skills are short, stage-specific, and backed by existing gate scripts rather than duplicated long rules.
5. Existing runs, schedules, and role templates remain backward compatible when `required_skill` is absent.
6. Validation proves that phase skill metadata reaches schedules, context packs, runtime spawn requests, generated role templates, docs, and installed skill packaging.

## Non-Goals

1. Do not rewrite the harness into a new orchestration system.
2. Do not remove existing `references/*.md` files before phase skills have proven coverage.
3. Do not let worker skills bypass `clarify`, `gate`, `dispatch-complete`, `handoff`, `ac-progress`, `guard`, or strict completion evidence.
4. Do not force multi-agent execution for small low-risk work; keep `single` and `single-review` behavior.
5. Do not duplicate the full coordinator hard rules into every worker skill.

## Design Principles

1. **Control plane stays central:** lifecycle, schedule, dispatch, phase locks, recovery, and gates stay in scripts.
2. **Skills become capabilities:** worker skills describe how a fresh worker performs one stage, not how the whole harness works.
3. **File boundaries beat chat memory:** handoffs, context packs, invocation JSON, and evidence paths remain the durable communication layer.
4. **Backward-compatible fields first:** add fields such as `required_skill`, `required_skill_path`, and `skill_reference_set`; do not replace `agent`, `phase`, `role_template`, or `runtime_subagent_type`.
5. **Tests before behavior:** every contract change starts with a failing focused test.

## Proposed Capability Map

| Phase or role | Required skill | Skill location | Primary inputs | Primary outputs |
| --- | --- | --- | --- | --- |
| `clarify` / `requirements-clarifier` | `e2e-harness-clarification` | `skills/e2e-harness-clarification/SKILL.md` | root instructions, request, dependency seeds | `handoffs/01-requirements-clarifier.md` |
| `plan` / `implementation-planner` | `e2e-harness-planning` | `skills/e2e-harness-planning/SKILL.md` | requirements handoff, R1 review, service scope | implementation plan and service schedule evidence |
| `tdd-red` | `e2e-harness-tdd-red` | `skills/e2e-harness-tdd-red/SKILL.md` | service design, ACs, test impact plan | failing test evidence and TDD handoff |
| `implement` | `e2e-harness-implementation` | `skills/e2e-harness-implementation/SKILL.md` | service design, red test evidence, claimed task | code changes, green tests, manifest, coverage rows |
| `r1-review`, `r2-review`, `r3-review` | `e2e-harness-review` | `skills/e2e-harness-review/SKILL.md` | review request, relevant handoffs, invocation JSON | phase review report |
| `coverage-review` / completion | `e2e-harness-completion` | `skills/e2e-harness-completion/SKILL.md` | manifests, coverage matrix, reviews, rework | completion evidence, archive, strict guard report |

## File Structure

Create:

- `skills/e2e-harness-clarification/SKILL.md` - stage-local rules for requirements clarification.
- `skills/e2e-harness-planning/SKILL.md` - stage-local rules for planning and service slicing.
- `skills/e2e-harness-tdd-red/SKILL.md` - stage-local rules for red-test workers.
- `skills/e2e-harness-implementation/SKILL.md` - stage-local rules for implementation workers.
- `skills/e2e-harness-review/SKILL.md` - stage-local rules for independent reviewers.
- `skills/e2e-harness-completion/SKILL.md` - stage-local rules for coverage and completion workers.
- `skills/e2e-dev-harness/references/phase-skill-capabilities.md` - coordinator-facing contract for phase skill dispatch.

Modify:

- `skills/e2e-dev-harness/SKILL.md` - link to the phase capability contract and clarify coordinator-only loading.
- `skills/e2e-dev-harness/scripts/orchestration_plan.py` - assign `required_skill`, `required_skill_path`, and `skill_reference_set` when generating scheduled tasks.
- `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py` - include capability metadata in bootstrap `requirements-clarifier` schedules and generated role templates.
- `skills/e2e-dev-harness/scripts/e2e_dev_harness.py` - preserve compatibility wrappers for generated role template text if still mirrored there.
- `skills/e2e-dev-harness/scripts/context_pack.py` - copy skill capability metadata into context packs and validate local skill paths.
- `skills/e2e-dev-harness/scripts/dispatcher.py` - include required skill metadata in invocation JSON and worker prompts.
- `skills/e2e-dev-harness/scripts/runtime_adapters.py` - include required skill metadata in runtime spawn request arguments or message payloads.
- `skills/e2e-dev-harness/scripts/agent_scheduler.py` - validate capability fields only when present and keep legacy schedules accepted.
- `tests/test_orchestration.py` - schedule, dispatch, and runtime spawn contract coverage.
- `tests/test_e2e_dev_harness_scripts.py` - context pack and role template coverage.
- `tests/test_enterprise_harness_architecture.py` - runtime adapter and enterprise contract coverage.
- `tests/test_skill_docs.py` - documentation and skill package coverage.

## Task 1: Schedule Capability Contract

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/orchestration_plan.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Modify: `tests/test_orchestration.py`

- [ ] **Step 1: Write the failing schedule test**

Add a focused assertion near the existing schedule role-template tests in `tests/test_orchestration.py`:

```python
def test_generated_schedule_declares_phase_required_skills(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        design = repo / "docs" / "design" / "feature.md"
        design.parent.mkdir(parents=True)
        design.write_text("## Acceptance Criteria\n- AC-1: prove behavior.\n", encoding="utf-8")

        result = orchestration_plan.plan(repo, mode="single-review", design_doc=design, create_archive=True)
        schedule = json.loads((repo / result["handoff_artifacts"]["agent_schedule"]).read_text(encoding="utf-8"))
        by_phase = {task["phase"]: task for task in schedule["tasks"]}

        self.assertEqual("e2e-harness-clarification", by_phase["clarify"]["required_skill"])
        self.assertEqual("skills/e2e-harness-clarification/SKILL.md", by_phase["clarify"]["required_skill_path"])
        self.assertIn("clarification-gate", " ".join(by_phase["clarify"]["skill_reference_set"]))
        self.assertEqual("e2e-harness-tdd-red", by_phase["tdd-red"]["required_skill"])
        self.assertEqual("e2e-harness-implementation", by_phase["implement"]["required_skill"])
        self.assertEqual("e2e-harness-review", by_phase["r2-review"]["required_skill"])
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: FAIL because generated tasks do not yet declare `required_skill`.

- [ ] **Step 3: Add the capability mapping**

In `orchestration_plan.py`, add a small mapping function:

```python
PHASE_SKILL_CAPABILITIES = {
    "clarify": ("e2e-harness-clarification", "skills/e2e-harness-clarification/SKILL.md", ["clarification-gate", "agent-instructions"]),
    "plan": ("e2e-harness-planning", "skills/e2e-harness-planning/SKILL.md", ["agent-orchestration", "implementation-gates"]),
    "tdd-red": ("e2e-harness-tdd-red", "skills/e2e-harness-tdd-red/SKILL.md", ["tdd-java-spring", "agent-orchestration"]),
    "implement": ("e2e-harness-implementation", "skills/e2e-harness-implementation/SKILL.md", ["tdd-java-spring", "implementation-gates"]),
    "r1-review": ("e2e-harness-review", "skills/e2e-harness-review/SKILL.md", ["review-profiles", "common-review-issues"]),
    "r2-review": ("e2e-harness-review", "skills/e2e-harness-review/SKILL.md", ["review-profiles", "common-review-issues"]),
    "r3-review": ("e2e-harness-review", "skills/e2e-harness-review/SKILL.md", ["review-profiles", "common-review-issues"]),
    "coverage-review": ("e2e-harness-completion", "skills/e2e-harness-completion/SKILL.md", ["implementation-gates", "requirements-archive"]),
}
```

Apply it inside task generation without removing existing fields:

```python
skill, path, refs = phase_skill_capability(phase)
task["required_skill"] = skill
task["required_skill_path"] = path
task["skill_reference_set"] = refs
```

Also add the same fields to the bootstrap requirements schedule created by `e2e_harness/cli/commands/start.py`.

- [ ] **Step 4: Run the focused test and confirm it passes**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: PASS for the new test and no regressions in the file.

## Task 2: Context Pack Skill Metadata

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/context_pack.py`
- Modify: `tests/test_e2e_dev_harness_scripts.py`

- [ ] **Step 1: Write the failing context-pack test**

Add coverage next to `test_context_pack_builds_request_scoped_task_budget`:

```python
def test_context_pack_includes_required_worker_skill(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
        schedule.parent.mkdir(parents=True)
        schedule.write_text(json.dumps({
            "tasks": [{
                "id": "T01",
                "agent": "requirements-clarifier",
                "phase": "clarify",
                "status": "ready",
                "required_skill": "e2e-harness-clarification",
                "required_skill_path": "skills/e2e-harness-clarification/SKILL.md",
                "skill_reference_set": ["clarification-gate", "agent-instructions"],
                "inputs": [],
                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
            }]
        }), encoding="utf-8")

        result = context_pack.build_pack(repo, schedule, task_id="T01")

        self.assertEqual("e2e-harness-clarification", result["required_skill"])
        self.assertEqual("skills/e2e-harness-clarification/SKILL.md", result["required_skill_path"])
        self.assertEqual(["clarification-gate", "agent-instructions"], result["skill_reference_set"])
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```powershell
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py
```

Expected: FAIL because `context_pack.build_pack()` does not yet expose these keys.

- [ ] **Step 3: Copy capability metadata into context packs**

Update `context_pack.build_pack()` to include:

```python
"required_skill": task.get("required_skill", ""),
"required_skill_path": task.get("required_skill_path", ""),
"skill_reference_set": task.get("skill_reference_set", []),
```

Update `validate()` so it warns, but does not block, when `required_skill_path` is present and missing from the repository. This keeps old schedules compatible while making packaging gaps visible.

- [ ] **Step 4: Run focused validation**

Run:

```powershell
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py
```

Expected: PASS.

## Task 3: Dispatcher And Runtime Spawn Contract

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/dispatcher.py`
- Modify: `skills/e2e-dev-harness/scripts/runtime_adapters.py`
- Modify: `tests/test_orchestration.py`
- Modify: `tests/test_enterprise_harness_architecture.py`

- [ ] **Step 1: Write the failing prompt test**

In `tests/test_orchestration.py`, add a dispatch prompt assertion:

```python
def test_worker_prompt_names_required_skill_and_reference_set(self) -> None:
    task = {
        "id": "T01",
        "agent": "requirements-clarifier",
        "phase": "clarify",
        "required_skill": "e2e-harness-clarification",
        "required_skill_path": "skills/e2e-harness-clarification/SKILL.md",
        "skill_reference_set": ["clarification-gate"],
        "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
    }
    pack = {
        "allowed_inputs": [],
        "allowed_outputs": task["outputs"],
        "required_skill": task["required_skill"],
        "required_skill_path": task["required_skill_path"],
        "skill_reference_set": task["skill_reference_set"],
    }
    prompt = dispatcher.task_prompt(task, pack, Path("docs/agent-runs/run/dispatch-invocations/T01.json"), Path("."))

    self.assertIn("Required worker skill: e2e-harness-clarification", prompt)
    self.assertIn("Skill file: skills/e2e-harness-clarification/SKILL.md", prompt)
    self.assertIn("Reference set: clarification-gate", prompt)
```

- [ ] **Step 2: Write the failing runtime spawn test**

In `tests/test_enterprise_harness_architecture.py`, add:

```python
def test_runtime_spawn_request_carries_required_skill_metadata(self) -> None:
    adapter = runtime_adapters.adapter_for("codex")
    task = {
        "id": "T01",
        "agent": "requirements-clarifier",
        "phase": "clarify",
        "required_skill": "e2e-harness-clarification",
        "required_skill_path": "skills/e2e-harness-clarification/SKILL.md",
    }

    request = adapter.spawn(task, "worker prompt", Path("docs/agent-runs/run/agent-schedule.json"), None, Path("."))

    self.assertEqual("e2e-harness-clarification", request["required_skill"])
    self.assertEqual("skills/e2e-harness-clarification/SKILL.md", request["required_skill_path"])
```

- [ ] **Step 3: Run focused tests and confirm failure**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
```

Expected: FAIL on missing prompt/spawn metadata.

- [ ] **Step 4: Update prompt and runtime spawn payloads**

In `dispatcher.task_prompt()`, add a compact section before allowed inputs:

```text
Required worker skill: <required_skill>
Skill file: <required_skill_path>
Reference set: <comma-separated skill_reference_set>
```

In `runtime_adapters.RuntimeAdapter.spawn()`, add top-level metadata to returned spawn requests:

```python
"required_skill": str(task.get("required_skill", "")),
"required_skill_path": str(task.get("required_skill_path", "")),
```

For Codex spawn requests, also include the metadata inside `arguments` so runtimes that consume only the message payload still receive it.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
```

Expected: PASS.

## Task 4: Worker Skill Skeletons

**Files:**
- Create: `skills/e2e-harness-clarification/SKILL.md`
- Create: `skills/e2e-harness-planning/SKILL.md`
- Create: `skills/e2e-harness-tdd-red/SKILL.md`
- Create: `skills/e2e-harness-implementation/SKILL.md`
- Create: `skills/e2e-harness-review/SKILL.md`
- Create: `skills/e2e-harness-completion/SKILL.md`
- Modify: `tests/test_skill_docs.py`

- [ ] **Step 1: Write the failing skill-doc test**

Add a test to `tests/test_skill_docs.py`:

```python
def test_phase_worker_skills_are_small_and_stage_scoped(self) -> None:
    expected = {
        "e2e-harness-clarification": "clarification",
        "e2e-harness-planning": "planning",
        "e2e-harness-tdd-red": "red test",
        "e2e-harness-implementation": "implementation",
        "e2e-harness-review": "review",
        "e2e-harness-completion": "completion",
    }
    for skill, phrase in expected.items():
        path = ROOT / "skills" / skill / "SKILL.md"
        self.assertTrue(path.exists(), skill)
        text = path.read_text(encoding="utf-8")
        self.assertIn(f"name: {skill}", text)
        self.assertIn(phrase, text.lower())
        self.assertIn("Do not inherit coordinator chat context", text)
        self.assertLess(len(text.splitlines()), 140)
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```powershell
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: FAIL because phase worker skills do not exist.

- [ ] **Step 3: Create compact worker skills**

Each `SKILL.md` must include only:

1. YAML `name` and `description`.
2. Allowed inputs.
3. Required outputs.
4. First command or first evidence action.
5. Stop conditions.
6. Gate command to run before returning.
7. A line saying `Do not inherit coordinator chat context`.

Example for clarification:

```markdown
---
name: e2e-harness-clarification
description: Use for e2e-dev-harness requirements-clarifier worker tasks that must clarify intent, acceptance criteria, impact, and open questions from a fresh isolated context.
---

# E2E Harness Clarification Worker

Do not inherit coordinator chat context.

Use only the context pack, allowed inputs, project instructions selected for clarification, and GitNexus/dependency evidence requested by the schedule.

Write `docs/agent-runs/<run>/handoffs/01-requirements-clarifier.md`.

Run `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py clarify . --design-doc <design-doc>` before returning evidence.

Ask the user only for intent confirmation, unresolved product decisions, or explicit tool-degradation approval.
```

Apply the same compact pattern to the other five skills with their phase-specific output and gate command.

- [ ] **Step 4: Run skill documentation tests**

Run:

```powershell
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: PASS.

## Task 5: Role Template Capability References

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`
- Modify: `tests/test_orchestration.py`

- [ ] **Step 1: Write the failing role-template test**

Add:

```python
def test_role_templates_name_required_worker_skill(self) -> None:
    text = e2e_dev_harness.role_template_text("requirements-clarifier")

    self.assertIn("Required worker skill", text)
    self.assertIn("e2e-harness-clarification", text)
    self.assertIn("Do not inherit coordinator chat context", text)
```

- [ ] **Step 2: Run and confirm failure**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: FAIL on missing skill references.

- [ ] **Step 3: Update role template text**

Add a compact capability section to generated role templates:

```markdown
## Required Worker Skill
- Skill: `<required_skill>`
- Skill file: `<required_skill_path>`
- Load only this worker skill plus the context pack and listed input files.
- Do not inherit coordinator chat context.
```

Keep existing role template sections so `agent_scheduler.role_template_blockers()` continues to pass.

- [ ] **Step 4: Run focused validation**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: PASS.

## Task 6: Coordinator Skill Slimming Contract

**Files:**
- Create: `skills/e2e-dev-harness/references/phase-skill-capabilities.md`
- Modify: `skills/e2e-dev-harness/SKILL.md`
- Modify: `tests/test_skill_docs.py`

- [ ] **Step 1: Write the failing docs test**

Add:

```python
def test_main_harness_skill_points_to_phase_capability_contract(self) -> None:
    skill = (ROOT / "skills" / "e2e-dev-harness" / "SKILL.md").read_text(encoding="utf-8")
    contract = ROOT / "skills" / "e2e-dev-harness" / "references" / "phase-skill-capabilities.md"

    self.assertTrue(contract.exists())
    self.assertIn("phase-skill-capabilities.md", skill)
    self.assertIn("coordinator loads the core harness skill", contract.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run and confirm failure**

Run:

```powershell
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: FAIL until the reference doc exists and is linked.

- [ ] **Step 3: Add the coordinator-facing contract**

`phase-skill-capabilities.md` must document:

1. Capability map from phase to skill.
2. Required schedule fields.
3. Context pack propagation.
4. Runtime spawn propagation.
5. Backward compatibility behavior when fields are missing.
6. The rule that gates remain authoritative.

Update `skills/e2e-dev-harness/SKILL.md` with one compact bullet under hard rules:

```markdown
- Phase workers load stage-specific skills from scheduled `required_skill` metadata; the coordinator loads only the core harness skill, context-pack paths, and compact evidence summaries (`references/phase-skill-capabilities.md`).
```

- [ ] **Step 4: Run skill-doc tests**

Run:

```powershell
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: PASS.

## Task 7: Compatibility And Validation Gates

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/agent_scheduler.py`
- Modify: `tests/test_orchestration.py`
- Modify: `tests/test_e2e_dev_harness_scripts.py`

- [ ] **Step 1: Write backward compatibility tests**

Add tests proving old schedules without `required_skill` still claim and complete when role templates and existing evidence are valid.

Expected assertion shape:

```python
self.assertTrue(result["ready"])
self.assertFalse(any("required_skill" in reason for reason in result.get("blocked_reasons", [])))
```

- [ ] **Step 2: Write strict validation tests for malformed fields**

Add tests where `required_skill_path` resolves outside the repo:

```python
task["required_skill_path"] = "../outside/SKILL.md"
```

Expected: claim or context-pack validation returns a blocker or warning that names `required_skill_path`.

- [ ] **Step 3: Implement additive validation**

In `agent_scheduler.py`, validate capability fields only when present:

1. `required_skill` must be a non-empty lowercase hyphenated token when present.
2. `required_skill_path` must resolve inside the repository when present.
3. Missing phase skill files should warn during early rollout, not block legacy schedules.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py
```

Expected: PASS.

## Task 8: End-To-End Dispatch Evidence

**Files:**
- Modify: `tests/test_orchestration.py`
- Modify: `tests/test_enterprise_harness_architecture.py`

- [ ] **Step 1: Add an end-to-end schedule-to-spawn test**

Create a test that:

1. Generates an archive.
2. Builds a context pack for `requirements-clarifier`.
3. Runs `dispatcher.dispatch_next()` or `dispatch_beat()`.
4. Asserts the spawn request contains the required skill.
5. Asserts the generated prompt contains only path references and not full coordinator chat.

Expected assertions:

```python
self.assertEqual("e2e-harness-clarification", spawn["required_skill"])
self.assertIn("Context Pack:", prompt_text)
self.assertNotIn("full coordinator chat", prompt_text.lower())
```

- [ ] **Step 2: Run and confirm failure**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: FAIL until metadata is propagated through the full dispatch path.

- [ ] **Step 3: Patch dispatch path gaps**

Patch only the missing propagation point shown by the failing test. Likely surfaces are:

1. `orchestration_plan.with_role_template()`
2. `context_pack.build_pack()`
3. `dispatcher.dispatch_packet_for_task()`
4. `runtime_adapters.RuntimeAdapter.spawn()`

- [ ] **Step 4: Run full focused orchestration validation**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
```

Expected: PASS.

## Task 9: Packaging And Installer Coverage

**Files:**
- Modify: `pyproject.toml`
- Modify: `tools/install-e2e-dev-harness.mjs`
- Modify: `tests/test_unified_cli.py`
- Modify: `tests/test_skill_docs.py`

- [ ] **Step 1: Add packaging test coverage**

Add assertions that phase worker skill directories are included by install/copy behavior and not treated as generated artifacts.

Expected skill set:

```python
{
    "e2e-dev-harness",
    "e2e-harness-clarification",
    "e2e-harness-planning",
    "e2e-harness-tdd-red",
    "e2e-harness-implementation",
    "e2e-harness-review",
    "e2e-harness-completion",
}
```

- [ ] **Step 2: Run expected failing checks**

Run:

```powershell
python -m unittest discover -s tests -p test_unified_cli.py
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: FAIL if installer or packaging tests do not yet know the new skill directories.

- [ ] **Step 3: Update install/copy logic**

Ensure installed target runtimes receive all phase worker skill directories together with `e2e-dev-harness`. Keep the original `e2e-dev-harness` install path unchanged.

- [ ] **Step 4: Run installer-related checks**

Run:

```powershell
node --check tools\install-e2e-dev-harness.mjs
python -m unittest discover -s tests -p test_unified_cli.py
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: PASS.

## Task 10: Broad Verification And GitNexus Change Audit

**Files:**
- No planned source edits unless verification exposes a gap.

- [ ] **Step 1: Run focused suites**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
python -m unittest discover -s tests -p test_skill_docs.py
python -m unittest discover -s tests -p test_unified_cli.py
```

Expected: PASS.

- [ ] **Step 2: Run the full suite**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 3: Run GitNexus affected-flow audit**

Run before commit:

```powershell
gitnexus detect-changes --repo C:\Users\14907\Documents\Codex\2026-05-23\skill-skill-superpowers-skill-tdd-graphify --scope unstaged
```

Expected: affected symbols are limited to schedule capability metadata, context-pack propagation, runtime spawn contract, worker skill docs, installer packaging, and tests.

- [ ] **Step 4: Report residual risk**

Report:

1. Whether legacy schedules without `required_skill` still pass.
2. Whether each new worker skill stayed under 140 lines.
3. Whether context pack and spawn request both expose required skill metadata.
4. Whether full `unittest` passed.
5. Whether GitNexus detected only expected affected flows.

## Rollout Strategy

1. Land Tasks 1-3 first. This gives machine-readable capability metadata without changing worker behavior.
2. Land Tasks 4-6 second. This creates worker skills and documents coordinator loading behavior.
3. Land Tasks 7-8 third. This proves compatibility and end-to-end dispatch propagation.
4. Land Task 9 after propagation is stable. Installer changes should not precede working metadata.
5. Run Task 10 before commit or PR.

## Acceptance Criteria

1. `agent-schedule.json` tasks include phase skill metadata for all generated phase roles.
2. `context_pack.build_pack()` carries `required_skill`, `required_skill_path`, and `skill_reference_set`.
3. Runtime spawn requests expose the same metadata for Claude Code and Codex runtimes.
4. Worker prompts tell the fresh worker which phase skill to load and forbid inherited coordinator chat context.
5. Six phase worker skills exist and stay compact.
6. The main harness skill links to `references/phase-skill-capabilities.md`.
7. Legacy schedules without skill metadata remain accepted.
8. Focused and full test suites pass.
9. GitNexus `detect-changes` reports only expected affected surfaces before commit.

## Risk Controls

| Risk | Control |
| --- | --- |
| Skill rule drift | Keep hard gates in scripts and keep worker skills short. |
| Context bloat from too many skills | Coordinator loads only metadata and paths; worker loads one phase skill. |
| Legacy schedule breakage | Capability fields are additive and optional during rollout. |
| Runtime inconsistency | Test both Task-style and Codex spawn payloads. |
| False sense of isolation | Invocation JSON and prompt continue to declare `fork_context: False` and no inherited chat. |
| Small task overhead | Preserve existing `single` and `single-review` decision logic. |

## Self-Review

Spec coverage: This plan covers schedule metadata, context packs, runtime spawn requests, role templates, worker skills, coordinator docs, compatibility, packaging, verification, and GitNexus audit.

Placeholder scan: No implementation step depends on unresolved placeholders; each task includes concrete files, fields, tests, commands, and expected results.

Type consistency: The same field names are used throughout: `required_skill`, `required_skill_path`, and `skill_reference_set`.
