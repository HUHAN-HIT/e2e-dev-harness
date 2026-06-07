# Phase Skill Capabilities (Control-Plane SSOT Aligned) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Project rule (CLAUDE.md):** Before editing any function/class/method, run `gitnexus_impact({target, direction:"upstream"})` and report blast radius. Before each commit, run `gitnexus_detect_changes()`. Do not edit symbols flagged HIGH/CRITICAL without surfacing it first.

**Relationship to prior plans:** This supersedes `docs/superpowers/plans/2026-06-04-phase-skill-capabilities.md`. That plan predated the control-plane SSOT work (`2026-06-06-single-file-control-plane.md`, `2026-06-07-control-plane-ssot.md`) and the `minimal` tier (`2026-06-07-gate-streamlining.md`). It wrote `required_skill` fields **into `agent-schedule.json` via `orchestration_plan.py`**, which reopens the schedule-as-truth write path SSOT just closed, and its phase→skill map assumed the full phase set with no `minimal` tier degradation. This plan keeps the same external contract (workers learn which stage skill to load) but attaches the metadata at the **control-plane engine seam** so the schedule projection carries it for free.

**Goal:** Give each dispatched worker a machine-readable signal of which stage-specific skill and reference subset to load, sourced from the control plane, without weakening deterministic gates, role isolation, or evidence contracts, and without writing capability fields onto the legacy schedule as independent truth.

**Architecture:** Add a phase→capability map and accessors to `agent_roles.py` (the existing canonical phase-metadata home alongside `PHASE_REGISTRY`). Inject the three additive fields (`required_skill`, `required_skill_path`, `skill_reference_set`) at the control-plane normalization seam (`engine/control_plane.py::_normalize_task` and `task_contract`) so every task entering the control plane — planner expansion, legacy import, repair task — gets them. The existing `_schedule_projection()` copies `data["tasks"]` verbatim, so the projected `agent-schedule.json` carries the fields with **no schedule-write code**. Context packs, worker prompts, runtime spawn requests, and role templates then surface the metadata. Six compact worker skills describe stage-local behavior; gates and scripts stay authoritative.

**Tech Stack:** Python stdlib harness scripts, Markdown skills, `unittest`, control-plane engine (`e2e_harness/engine/control_plane.py`, `e2e_harness/domain/control_plane_models.py`), context packs, runtime adapters, GitNexus impact/detect-changes.

---

## Target Outcomes

1. The coordinator loads only the core harness skill and control-plane references during normal dispatch.
2. Capability metadata is a property of the **control-plane task**, applied at normalization, never written onto the schedule as an independent source of truth.
3. Each generated phase task exposes `required_skill`, `required_skill_path`, and `skill_reference_set` through the schedule projection, context packs, prompts, spawn requests, and role templates.
4. Worker skills are short, stage-specific, and backed by existing gate scripts rather than duplicated long rules.
5. Legacy schedules and `minimal`-tier single-pass runs remain valid; unmapped phases simply carry no capability fields (additive, non-blocking).
6. Validation proves the metadata reaches the control plane, the schedule projection, context packs, runtime spawn requests, generated role templates, docs, and installed skill packaging.

## Non-Goals

1. Do not rewrite the harness into a new orchestration system.
2. Do not modify `orchestration_plan.py` to write capability fields onto `agent-schedule.json` as an authoritative source (that is the SSOT leak this plan avoids).
3. Do not remove existing `references/*.md` files before phase skills have proven coverage.
4. Do not let worker skills bypass `clarify`, `gate`, `dispatch-complete`, `handoff`, `ac-progress`, `guard`, or strict completion evidence.
5. Do not force multi-agent execution for `minimal`/`single`/`single-review` work; keep their existing behavior.
6. Do not duplicate the full coordinator hard rules into every worker skill.

## Design Principles

1. **Control plane stays the single source of truth:** capability metadata lives on the control-plane task and reaches the schedule only via the existing projection.
2. **One injection seam:** `_normalize_task` and `task_contract` are the only places that derive phase-keyed metadata; capability fields join them, so planner/import/repair paths all get them.
3. **Skills become capabilities:** worker skills describe how a fresh worker performs one stage, not how the whole harness works.
4. **Backward-compatible and tier-safe:** fields are additive and optional; unmapped phases (including `minimal`-tier single-pass) carry no capability fields and never block.
5. **Tests before behavior:** every contract change starts with a failing focused test.

## Proposed Capability Map

| Phase | Required skill | Skill location | Reference set |
| --- | --- | --- | --- |
| `clarify` | `e2e-harness-clarification` | `skills/e2e-harness-clarification/SKILL.md` | `clarification-gate`, `agent-instructions` |
| `plan` | `e2e-harness-planning` | `skills/e2e-harness-planning/SKILL.md` | `agent-orchestration`, `implementation-gates` |
| `tdd-red` | `e2e-harness-tdd-red` | `skills/e2e-harness-tdd-red/SKILL.md` | `tdd-java-spring`, `agent-orchestration` |
| `implement` | `e2e-harness-implementation` | `skills/e2e-harness-implementation/SKILL.md` | `tdd-java-spring`, `implementation-gates` |
| `r1-review`, `r2-review`, `r3-review` | `e2e-harness-review` | `skills/e2e-harness-review/SKILL.md` | `review-profiles`, `common-review-issues` |
| `coverage-review` | `e2e-harness-completion` | `skills/e2e-harness-completion/SKILL.md` | `implementation-gates`, `requirements-archive` |
| any other / coordination / minimal-only phase | *(none)* | *(none)* | *(empty)* |

The `minimal` tier's single-pass worker uses phase `implement` (see `orchestration_plan.py` minimal task owning "minimal implementation, red-green-refactor, verification"), so it maps to `e2e-harness-implementation` automatically. If a future minimal task uses a bespoke phase, it falls through to the "none" row and carries no capability fields — graceful, non-blocking degradation.

## File Structure

Create:

- `skills/e2e-harness-clarification/SKILL.md` — stage-local rules for requirements clarification.
- `skills/e2e-harness-planning/SKILL.md` — stage-local rules for planning and service slicing.
- `skills/e2e-harness-tdd-red/SKILL.md` — stage-local rules for red-test workers.
- `skills/e2e-harness-implementation/SKILL.md` — stage-local rules for implementation workers.
- `skills/e2e-harness-review/SKILL.md` — stage-local rules for independent reviewers.
- `skills/e2e-harness-completion/SKILL.md` — stage-local rules for coverage and completion workers.
- `skills/e2e-dev-harness/references/phase-skill-capabilities.md` — coordinator-facing contract for phase skill dispatch.

Modify:

- `skills/e2e-dev-harness/scripts/agent_roles.py` — add `PHASE_SKILL_CAPABILITIES` map and `phase_required_skill` / `phase_required_skill_path` / `phase_skill_reference_set` accessors.
- `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py` — inject capability fields in `_normalize_task` and `task_contract`.
- `skills/e2e-dev-harness/scripts/context_pack.py` — copy capability metadata into context packs; warn (not block) when a present `required_skill_path` is missing from the repo.
- `skills/e2e-dev-harness/scripts/dispatcher.py` — name the required skill and reference set in `task_prompt`.
- `skills/e2e-dev-harness/scripts/runtime_adapters.py` — include capability metadata in spawn requests (Task-style and Codex).
- `skills/e2e-dev-harness/scripts/e2e_dev_harness.py` — add a compact "Required Worker Skill" section to generated role templates.
- `skills/e2e-dev-harness/scripts/agent_scheduler.py` — additive validation of capability fields only when present.
- `skills/e2e-dev-harness/SKILL.md` — one bullet linking the phase capability contract.
- `pyproject.toml`, `tools/install-e2e-dev-harness.mjs` — package the six new skill directories.
- Tests: `tests/test_orchestration.py`, `tests/test_e2e_dev_harness_scripts.py`, `tests/test_enterprise_harness_architecture.py`, `tests/test_skill_docs.py`, `tests/test_unified_cli.py`.

---

## Task 1: Phase Capability Map + Accessors (`agent_roles.py`)

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/agent_roles.py`
- Modify: `tests/test_orchestration.py`

- [ ] **Step 0: Impact analysis**

Run and report blast radius before editing:

```text
gitnexus_impact({target: "agent_roles", direction: "upstream"})
gitnexus_impact({target: "phase_role_group", direction: "upstream"})
```

Surface any HIGH/CRITICAL before proceeding.

- [ ] **Step 1: Write the failing accessor test**

Add to `tests/test_orchestration.py`:

```python
def test_phase_skill_capability_accessors(self) -> None:
    self.assertEqual("e2e-harness-clarification", agent_roles.phase_required_skill("clarify"))
    self.assertEqual(
        "skills/e2e-harness-clarification/SKILL.md",
        agent_roles.phase_required_skill_path("clarify"),
    )
    self.assertIn("clarification-gate", agent_roles.phase_skill_reference_set("clarify"))
    self.assertEqual("e2e-harness-implementation", agent_roles.phase_required_skill("implement"))
    self.assertEqual("e2e-harness-review", agent_roles.phase_required_skill("r2-review"))
    # Unmapped phase degrades to empty (tier-safe, additive).
    self.assertEqual("", agent_roles.phase_required_skill("coordination"))
    self.assertEqual("", agent_roles.phase_required_skill_path("coordination"))
    self.assertEqual([], agent_roles.phase_skill_reference_set("coordination"))
```

Ensure `import agent_roles` is present in the test module (it already imports the harness scripts package).

- [ ] **Step 2: Run the focused test and confirm it fails**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: FAIL — `agent_roles` has no `phase_required_skill`.

- [ ] **Step 3: Add the map and accessors**

In `agent_roles.py`, near `PHASE_REGISTRY` / `PHASE_ROLE_GROUPS`, add:

```python
# Phase -> (required_skill, required_skill_path, reference_set). Additive and
# optional: phases absent here (coordination, minimal-only bespoke phases) carry
# no capability fields and never block. Gates in scripts remain authoritative.
PHASE_SKILL_CAPABILITIES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "clarify": (
        "e2e-harness-clarification",
        "skills/e2e-harness-clarification/SKILL.md",
        ("clarification-gate", "agent-instructions"),
    ),
    "plan": (
        "e2e-harness-planning",
        "skills/e2e-harness-planning/SKILL.md",
        ("agent-orchestration", "implementation-gates"),
    ),
    "tdd-red": (
        "e2e-harness-tdd-red",
        "skills/e2e-harness-tdd-red/SKILL.md",
        ("tdd-java-spring", "agent-orchestration"),
    ),
    "implement": (
        "e2e-harness-implementation",
        "skills/e2e-harness-implementation/SKILL.md",
        ("tdd-java-spring", "implementation-gates"),
    ),
    "r1-review": (
        "e2e-harness-review",
        "skills/e2e-harness-review/SKILL.md",
        ("review-profiles", "common-review-issues"),
    ),
    "r2-review": (
        "e2e-harness-review",
        "skills/e2e-harness-review/SKILL.md",
        ("review-profiles", "common-review-issues"),
    ),
    "r3-review": (
        "e2e-harness-review",
        "skills/e2e-harness-review/SKILL.md",
        ("review-profiles", "common-review-issues"),
    ),
    "coverage-review": (
        "e2e-harness-completion",
        "skills/e2e-harness-completion/SKILL.md",
        ("implementation-gates", "requirements-archive"),
    ),
}


def phase_required_skill(phase: str) -> str:
    entry = PHASE_SKILL_CAPABILITIES.get(str(phase).strip())
    return entry[0] if entry else ""


def phase_required_skill_path(phase: str) -> str:
    entry = PHASE_SKILL_CAPABILITIES.get(str(phase).strip())
    return entry[1] if entry else ""


def phase_skill_reference_set(phase: str) -> list[str]:
    entry = PHASE_SKILL_CAPABILITIES.get(str(phase).strip())
    return list(entry[2]) if entry else []
```

- [ ] **Step 4: Run the focused test and confirm it passes**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: PASS, no regressions in the file.

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/agent_roles.py tests/test_orchestration.py
git commit -m "feat(roles): add phase skill capability map and accessors"
```

## Task 2: Inject Capability Fields At The Control-Plane Seam

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py`
- Modify: `tests/test_orchestration.py`

- [ ] **Step 0: Impact analysis**

```text
gitnexus_impact({target: "_normalize_task", direction: "upstream"})
gitnexus_impact({target: "task_contract", direction: "upstream"})
```

Report callers (expect `replace_tasks`, `import_legacy`, repair-task creation, schedule projection consumers). Surface HIGH/CRITICAL.

- [ ] **Step 1: Write the failing normalization test**

Add to `tests/test_orchestration.py`:

```python
def test_normalize_task_adds_phase_skill_capability(self) -> None:
    task = control_plane._normalize_task({"agent": "requirements-clarifier", "phase": "clarify"})

    self.assertEqual("e2e-harness-clarification", task["required_skill"])
    self.assertEqual("skills/e2e-harness-clarification/SKILL.md", task["required_skill_path"])
    self.assertEqual(["clarification-gate", "agent-instructions"], task["skill_reference_set"])

def test_normalize_task_unmapped_phase_has_empty_capability(self) -> None:
    task = control_plane._normalize_task({"agent": "coordinator", "phase": "coordination"})

    self.assertEqual("", task["required_skill"])
    self.assertEqual("", task["required_skill_path"])
    self.assertEqual([], task["skill_reference_set"])

def test_normalize_task_preserves_explicit_capability(self) -> None:
    task = control_plane._normalize_task({
        "agent": "requirements-clarifier",
        "phase": "clarify",
        "required_skill": "custom-skill",
    })

    self.assertEqual("custom-skill", task["required_skill"])
```

Ensure the test module imports the engine: `from e2e_harness.engine import control_plane`.

- [ ] **Step 2: Run the focused test and confirm it fails**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: FAIL — normalized task has no `required_skill`.

- [ ] **Step 3: Inject in `_normalize_task`**

In `e2e_harness/engine/control_plane.py`, inside `_normalize_task`, after the existing `copy.setdefault("depends_on_phases", agent_roles.depends_on_for_phase(phase))` line, add:

```python
    copy.setdefault("required_skill", agent_roles.phase_required_skill(phase))
    copy.setdefault("required_skill_path", agent_roles.phase_required_skill_path(phase))
    copy.setdefault("skill_reference_set", agent_roles.phase_skill_reference_set(phase))
```

(`agent_roles` is already imported in this module — it is used for `phase_role_group`.)

- [ ] **Step 4: Inject in `task_contract`**

In the same file, in `task_contract()`, where phase-derived fields are assembled (alongside `role_group` / `runtime_subagent_type` / `depends_on_phases`), add equivalent keys so directly-built contracts match normalized tasks:

```python
        "required_skill": str(extra.get("required_skill", "") or agent_roles.phase_required_skill(phase)),
        "required_skill_path": str(extra.get("required_skill_path", "") or agent_roles.phase_required_skill_path(phase)),
        "skill_reference_set": list(extra.get("skill_reference_set", []) or agent_roles.phase_skill_reference_set(phase)),
```

- [ ] **Step 5: Write the projection test**

Add to `tests/test_orchestration.py`:

```python
def test_schedule_projection_carries_capability_fields(self) -> None:
    data = control_plane.default_control_plane("run-1")
    data["tasks"] = [control_plane._normalize_task({"agent": "requirements-clarifier", "phase": "clarify"})]

    projection = control_plane._schedule_projection(data)
    task = projection["tasks"][0]

    self.assertEqual("e2e-harness-clarification", task["required_skill"])
    self.assertEqual("skills/e2e-harness-clarification/SKILL.md", task["required_skill_path"])
```

- [ ] **Step 6: Run focused tests and confirm pass**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: PASS. `_schedule_projection` already copies `data["tasks"]` verbatim, so it needs no edit — the projection test proves the fields ride the projection.

- [ ] **Step 7: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/engine/control_plane.py tests/test_orchestration.py
git commit -m "feat(control-plane): derive phase skill capability at the normalization seam"
```

## Task 3: End-To-End Plan → Schedule Projection Evidence

**Files:**
- Modify: `tests/test_orchestration.py`

- [ ] **Step 1: Write the failing end-to-end schedule test**

Prove a real planned run surfaces capability fields through the control plane and its schedule projection. Add to `tests/test_orchestration.py`:

```python
def test_planned_run_schedule_declares_phase_required_skills(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        design = repo / "docs" / "design" / "feature.md"
        design.parent.mkdir(parents=True)
        design.write_text("## Acceptance Criteria\n- AC-1: prove behavior.\n", encoding="utf-8")

        result = orchestration_plan.plan(repo, mode="single-review", design_doc=design, create_archive=True)
        schedule = json.loads(
            (repo / result["handoff_artifacts"]["agent_schedule"]).read_text(encoding="utf-8")
        )
        by_phase = {task["phase"]: task for task in schedule["tasks"]}

        if "clarify" in by_phase:
            self.assertEqual("e2e-harness-clarification", by_phase["clarify"]["required_skill"])
        if "implement" in by_phase:
            self.assertEqual("e2e-harness-implementation", by_phase["implement"]["required_skill"])
        if "r2-review" in by_phase:
            self.assertEqual("e2e-harness-review", by_phase["r2-review"]["required_skill"])
```

> Note: if `orchestration_plan.plan()` builds the schedule independently of `_normalize_task`, this test will fail. In that case, in Step 3 route the planner's task list through the `agent_roles.phase_required_skill` accessors at the point the schedule tasks are assembled — **without** adding schedule-only persistence as an authoritative source. The control plane's `replace_tasks`/`_normalize_task` remains the SSOT seam; this only keeps the projected schedule consistent before control-plane folding.

- [ ] **Step 2: Run and observe**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: PASS if the planner already normalizes via the engine; FAIL if the planner builds schedule tasks without the accessors.

- [ ] **Step 3: If failing, apply the accessors at plan assembly**

In `orchestration_plan.py`, at the single point where each scheduled task dict is finalized, add the capability fields from the accessors (read-only derivation):

```python
phase = task.get("phase", "")
task.setdefault("required_skill", agent_roles.phase_required_skill(phase))
task.setdefault("required_skill_path", agent_roles.phase_required_skill_path(phase))
task.setdefault("skill_reference_set", agent_roles.phase_skill_reference_set(phase))
```

Add `import agent_roles` if not present.

- [ ] **Step 4: Run and confirm pass**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_orchestration.py skills/e2e-dev-harness/scripts/orchestration_plan.py
git commit -m "test(plan): assert planned schedule projects phase skill capability"
```

## Task 4: Context Pack Skill Metadata

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/context_pack.py`
- Modify: `tests/test_e2e_dev_harness_scripts.py`

- [ ] **Step 0: Impact analysis**

```text
gitnexus_impact({target: "build_pack", direction: "upstream"})
```

- [ ] **Step 1: Write the failing context-pack test**

Add to `tests/test_e2e_dev_harness_scripts.py`, near `test_context_pack_builds_request_scoped_task_budget`:

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

```powershell
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py
```

Expected: FAIL — `build_pack()` does not expose these keys.

- [ ] **Step 3: Expose the keys in `build_pack`**

In `context_pack.py::build_pack`, add to the returned dict (next to `allowed_inputs` / `allowed_outputs`):

```python
        "required_skill": task.get("required_skill", ""),
        "required_skill_path": task.get("required_skill_path", ""),
        "skill_reference_set": task.get("skill_reference_set", []) if isinstance(task.get("skill_reference_set"), list) else [],
```

- [ ] **Step 4: Add a non-blocking packaging warning in `validate`**

In `context_pack.py::validate`, after the existing input/output checks, add:

```python
    required_skill_path = data.get("required_skill_path", "")
    if isinstance(required_skill_path, str) and required_skill_path:
        if not resolve_repo_path(repo, required_skill_path).exists():
            warnings.append(f"required_skill_path missing from repo: {required_skill_path}")
```

Confirm `validate` already accumulates a `warnings` list; if it returns blockers only, add a `warnings` key to its return and assert on it.

- [ ] **Step 5: Run focused validation and confirm pass**

```powershell
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/e2e-dev-harness/scripts/context_pack.py tests/test_e2e_dev_harness_scripts.py
git commit -m "feat(context-pack): expose required worker skill metadata"
```

## Task 5: Dispatcher Prompt + Runtime Spawn Contract

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/dispatcher.py`
- Modify: `skills/e2e-dev-harness/scripts/runtime_adapters.py`
- Modify: `tests/test_orchestration.py`
- Modify: `tests/test_enterprise_harness_architecture.py`

- [ ] **Step 0: Impact analysis**

```text
gitnexus_impact({target: "task_prompt", direction: "upstream"})
gitnexus_impact({target: "spawn", direction: "upstream"})
```

- [ ] **Step 1: Write the failing prompt test**

Add to `tests/test_orchestration.py`:

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

Add to `tests/test_enterprise_harness_architecture.py`:

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

- [ ] **Step 3: Run both and confirm failure**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
```

Expected: FAIL on missing prompt section / spawn keys.

- [ ] **Step 4: Add the prompt section**

In `dispatcher.py::task_prompt`, insert a compact block into `lines` immediately before the `"Allowed inputs:"` line:

```python
    required_skill = str(pack.get("required_skill", "") or task.get("required_skill", ""))
    if required_skill:
        lines.append(f"Required worker skill: {required_skill}")
        lines.append(f"Skill file: {pack.get('required_skill_path', '') or task.get('required_skill_path', '')}")
        reference_set = pack.get("skill_reference_set", []) or task.get("skill_reference_set", [])
        if reference_set:
            lines.append("Reference set: " + ", ".join(str(item) for item in reference_set))
        lines.append("Load only this worker skill plus the context pack and listed input files.")
        lines.append("")
```

- [ ] **Step 5: Add spawn metadata**

In `runtime_adapters.py::RuntimeAdapter.spawn`, add to the returned spawn request dict (top level):

```python
            "required_skill": str(task.get("required_skill", "")),
            "required_skill_path": str(task.get("required_skill_path", "")),
```

For the Codex adapter, also place the same two keys inside the `arguments` payload so runtimes that read only the message payload still receive them. Mirror exactly where the existing `phase` / `agent` keys are added.

- [ ] **Step 6: Run both and confirm pass**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add skills/e2e-dev-harness/scripts/dispatcher.py skills/e2e-dev-harness/scripts/runtime_adapters.py tests/test_orchestration.py tests/test_enterprise_harness_architecture.py
git commit -m "feat(dispatch): surface required worker skill in prompt and spawn request"
```

## Task 6: Compatibility & Additive Validation (`agent_scheduler.py`)

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/agent_scheduler.py`
- Modify: `tests/test_orchestration.py`

- [ ] **Step 0: Impact analysis**

```text
gitnexus_impact({target: "agent_scheduler", direction: "upstream"})
```

- [ ] **Step 1: Write the backward-compatibility test**

Add to `tests/test_orchestration.py` — a legacy schedule task with no capability fields must still pass with no capability blocker:

```python
def test_legacy_task_without_capability_is_not_blocked(self) -> None:
    task = {"id": "T01", "agent": "requirements-clarifier", "phase": "clarify", "status": "ready"}

    blockers = agent_scheduler.capability_blockers(task)

    self.assertEqual([], blockers)
```

- [ ] **Step 2: Write the malformed-field tests**

```python
def test_capability_path_outside_repo_is_blocked(self) -> None:
    task = {
        "id": "T01",
        "agent": "requirements-clarifier",
        "phase": "clarify",
        "required_skill": "e2e-harness-clarification",
        "required_skill_path": "../outside/SKILL.md",
    }

    blockers = agent_scheduler.capability_blockers(task)

    self.assertTrue(any("required_skill_path" in reason for reason in blockers))

def test_capability_skill_token_must_be_hyphenated_lowercase(self) -> None:
    task = {"id": "T01", "phase": "clarify", "required_skill": "Bad Skill Name"}

    blockers = agent_scheduler.capability_blockers(task)

    self.assertTrue(any("required_skill" in reason for reason in blockers))
```

- [ ] **Step 3: Run and confirm failure**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: FAIL — `agent_scheduler.capability_blockers` does not exist.

- [ ] **Step 4: Implement additive validation**

In `agent_scheduler.py`, add:

```python
import re

_SKILL_TOKEN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def capability_blockers(task: dict) -> list[str]:
    """Validate phase skill capability fields only when present. Missing fields
    are allowed (legacy/minimal-tier compatibility)."""
    blockers: list[str] = []
    skill = task.get("required_skill", "")
    if skill and not _SKILL_TOKEN.match(str(skill)):
        blockers.append(f"required_skill must be a lowercase hyphenated token: {skill!r}")
    path = task.get("required_skill_path", "")
    if path:
        normalized = str(path).replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            blockers.append(f"required_skill_path must resolve inside the repository: {path!r}")
    return blockers
```

Wire `capability_blockers` into the existing claim/role-template blocker aggregation where other per-task blockers are collected, so present-but-malformed fields surface during claim. Do not block on *missing* fields.

- [ ] **Step 5: Run and confirm pass**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/e2e-dev-harness/scripts/agent_scheduler.py tests/test_orchestration.py
git commit -m "feat(scheduler): additive validation for phase skill capability fields"
```

## Task 7: Worker Skill Skeletons

**Files:**
- Create: `skills/e2e-harness-clarification/SKILL.md`
- Create: `skills/e2e-harness-planning/SKILL.md`
- Create: `skills/e2e-harness-tdd-red/SKILL.md`
- Create: `skills/e2e-harness-implementation/SKILL.md`
- Create: `skills/e2e-harness-review/SKILL.md`
- Create: `skills/e2e-harness-completion/SKILL.md`
- Modify: `tests/test_skill_docs.py`

- [ ] **Step 1: Write the failing skill-doc test**

Add to `tests/test_skill_docs.py`:

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

- [ ] **Step 2: Run and confirm failure**

```powershell
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: FAIL — phase worker skills do not exist.

- [ ] **Step 3: Create the six compact worker skills**

Each `SKILL.md` contains only: YAML `name`/`description`, allowed inputs, required outputs, first evidence action, stop conditions, the gate command to run before returning, and the line `Do not inherit coordinator chat context`.

`skills/e2e-harness-clarification/SKILL.md`:

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

`skills/e2e-harness-planning/SKILL.md`:

```markdown
---
name: e2e-harness-planning
description: Use for e2e-dev-harness implementation-planner worker tasks that turn clarified requirements into a service-sliced implementation plan and schedule from a fresh isolated context.
---

# E2E Harness Planning Worker

Do not inherit coordinator chat context.

Use only the context pack, the requirements handoff, any R1 review, and service-scope inputs listed in the schedule.

Write the implementation plan and service schedule evidence named in the task outputs.

Run `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py gate . --phase plan` before returning evidence.

Ask the user only for scope or sequencing decisions that the requirements handoff does not resolve.
```

`skills/e2e-harness-tdd-red/SKILL.md`:

```markdown
---
name: e2e-harness-tdd-red
description: Use for e2e-dev-harness tdd-red worker tasks that write failing tests proving acceptance criteria before any implementation, from a fresh isolated context.
---

# E2E Harness TDD Red Worker

Do not inherit coordinator chat context.

Use only the context pack, the service design, the acceptance criteria, and the test impact plan listed in the schedule.

Write the failing test files and the red-test evidence named in the task outputs.

Run the service test command and capture failing output before returning evidence.

Stop after tests fail for the intended reason; do not implement production code in this task.
```

`skills/e2e-harness-implementation/SKILL.md`:

```markdown
---
name: e2e-harness-implementation
description: Use for e2e-dev-harness implement worker tasks that make red tests green with minimal code, produce a manifest and coverage rows, from a fresh isolated context.
---

# E2E Harness Implementation Worker

Do not inherit coordinator chat context.

Use only the context pack, the service design, the red-test evidence, and the claimed task listed in the schedule.

Write the code changes, green tests, implementation manifest, and coverage rows named in the task outputs.

Run the service test command and the implementation gate before returning evidence.

Stop after tests pass and the manifest is written; do not perform R1/R2/R3 self-review in this session.
```

`skills/e2e-harness-review/SKILL.md`:

```markdown
---
name: e2e-harness-review
description: Use for e2e-dev-harness r1/r2/r3 reviewer worker tasks that independently review a phase from a fresh isolated context and never review their own implementation.
---

# E2E Harness Review Worker

Do not inherit coordinator chat context.

Use only the context pack, the review request, the relevant handoffs, and the invocation JSON listed in the schedule.

Write the phase review report named in the task outputs.

Run `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py gate . --phase <review-phase>` before returning evidence.

Stop after the review report is written; do not modify implementation files.
```

`skills/e2e-harness-completion/SKILL.md`:

```markdown
---
name: e2e-harness-completion
description: Use for e2e-dev-harness coverage-review and completion worker tasks that assemble the coverage matrix, completion evidence, and strict guard report from a fresh isolated context.
---

# E2E Harness Completion Worker

Do not inherit coordinator chat context.

Use only the context pack, the implementation manifests, the coverage matrix, the reviews, and any rework records listed in the schedule.

Write the completion evidence, archive, and strict guard report named in the task outputs.

Run the coverage gate and the strict completion guard before returning evidence.

Stop after the guard report is written; do not reopen implementation tasks.
```

- [ ] **Step 4: Run and confirm pass**

```powershell
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-harness-clarification skills/e2e-harness-planning skills/e2e-harness-tdd-red skills/e2e-harness-implementation skills/e2e-harness-review skills/e2e-harness-completion tests/test_skill_docs.py
git commit -m "feat(skills): add six compact phase worker skills"
```

## Task 8: Role Template Capability Reference

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`
- Modify: `tests/test_orchestration.py`

- [ ] **Step 0: Impact analysis**

```text
gitnexus_impact({target: "role_template_text", direction: "upstream"})
```

- [ ] **Step 1: Write the failing role-template test**

Add to `tests/test_orchestration.py`:

```python
def test_role_templates_name_required_worker_skill(self) -> None:
    text = e2e_dev_harness.role_template_text("requirements-clarifier")

    self.assertIn("Required Worker Skill", text)
    self.assertIn("e2e-harness-clarification", text)
    self.assertIn("Do not inherit coordinator chat context", text)
```

- [ ] **Step 2: Run and confirm failure**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: FAIL on missing skill section.

- [ ] **Step 3: Update role template text**

In `e2e_dev_harness.py::role_template_text`, map the role to its phase, derive the skill from the accessors, and append a compact section (keep all existing sections so `agent_scheduler.role_template_blockers()` still passes). Use the same `sections`/append pattern the function already uses:

```python
    import agent_roles
    role_phase = {
        "requirements-clarifier": "clarify",
        "implementation-planner": "plan",
        "tdd-red": "tdd-red",
        "implementer": "implement",
        "r1-reviewer": "r1-review",
        "r2-reviewer": "r2-review",
        "r3-reviewer": "r3-review",
        "coverage-reviewer": "coverage-review",
    }.get(role, "")
    skill = agent_roles.phase_required_skill(role_phase)
    if skill:
        sections.append(
            "## Required Worker Skill\n"
            f"- Skill: `{skill}`\n"
            f"- Skill file: `{agent_roles.phase_required_skill_path(role_phase)}`\n"
            "- Load only this worker skill plus the context pack and listed input files.\n"
            "- Do not inherit coordinator chat context.\n"
        )
```

If `agent_roles` already exposes a role→phase helper, use it instead of the inline dict. Verify the role-name keys against the actual role identifiers `role_template_text` is called with (adjust keys to match real role strings if they differ).

- [ ] **Step 4: Run and confirm pass**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_dev_harness.py tests/test_orchestration.py
git commit -m "feat(roles): name required worker skill in generated role templates"
```

## Task 9: Coordinator Contract Doc + SKILL Link

**Files:**
- Create: `skills/e2e-dev-harness/references/phase-skill-capabilities.md`
- Modify: `skills/e2e-dev-harness/SKILL.md`
- Modify: `tests/test_skill_docs.py`

- [ ] **Step 1: Write the failing docs test**

Add to `tests/test_skill_docs.py`:

```python
def test_main_harness_skill_points_to_phase_capability_contract(self) -> None:
    skill = (ROOT / "skills" / "e2e-dev-harness" / "SKILL.md").read_text(encoding="utf-8")
    contract = ROOT / "skills" / "e2e-dev-harness" / "references" / "phase-skill-capabilities.md"

    self.assertTrue(contract.exists())
    self.assertIn("phase-skill-capabilities.md", skill)
    self.assertIn("control plane is the single source of truth", contract.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run and confirm failure**

```powershell
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: FAIL until the doc exists and is linked.

- [ ] **Step 3: Create the contract doc**

`skills/e2e-dev-harness/references/phase-skill-capabilities.md`:

```markdown
# Phase Skill Capabilities Contract

The control plane is the single source of truth for task capability metadata.

## Capability source
- `agent_roles.PHASE_SKILL_CAPABILITIES` maps phase -> (`required_skill`, `required_skill_path`, `skill_reference_set`).
- `engine/control_plane.py` injects these fields in `_normalize_task` and `task_contract`, so every task entering the control plane (planner expansion, legacy import, repair task) carries them.
- `_schedule_projection()` copies tasks verbatim; the projected `agent-schedule.json` therefore carries the fields without any schedule-only write path.

## Propagation
1. Control-plane task -> schedule projection.
2. `context_pack.build_pack()` -> `required_skill`, `required_skill_path`, `skill_reference_set`.
3. `dispatcher.task_prompt()` -> "Required worker skill" section naming the skill file and reference set.
4. `runtime_adapters.RuntimeAdapter.spawn()` -> top-level (and Codex `arguments`) skill metadata.
5. Generated role templates -> "Required Worker Skill" section.

## Backward compatibility and tiers
- Fields are additive and optional. Tasks whose phase is not in the map (coordination, minimal-tier bespoke phases) carry empty capability fields and are never blocked.
- Legacy schedules without these fields claim, dispatch, and complete unchanged.
- `agent_scheduler.capability_blockers()` validates fields only when present.

## Authority
- Gates and scripts remain authoritative. Worker skills describe stage-local behavior only and never replace `clarify`, `gate`, `dispatch-complete`, `handoff`, `ac-progress`, `guard`, or strict completion evidence.
```

- [ ] **Step 4: Link from the coordinator skill**

In `skills/e2e-dev-harness/SKILL.md`, under the hard rules, add one bullet:

```markdown
- Phase workers load stage-specific skills from each task's `required_skill` metadata (sourced from the control plane); the coordinator loads only the core harness skill, context-pack paths, and compact evidence summaries (`references/phase-skill-capabilities.md`).
```

- [ ] **Step 5: Run and confirm pass**

```powershell
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/e2e-dev-harness/references/phase-skill-capabilities.md skills/e2e-dev-harness/SKILL.md tests/test_skill_docs.py
git commit -m "docs(harness): add phase skill capability contract and coordinator link"
```

## Task 10: Packaging & Installer Coverage

**Files:**
- Modify: `pyproject.toml`
- Modify: `tools/install-e2e-dev-harness.mjs`
- Modify: `tests/test_unified_cli.py`
- Modify: `tests/test_skill_docs.py`

- [ ] **Step 1: Add packaging test coverage**

Add to `tests/test_skill_docs.py` (or `tests/test_unified_cli.py`, wherever installed-skill-set assertions live) a test asserting all phase worker skill directories are packaged:

```python
def test_phase_worker_skills_are_packaged(self) -> None:
    expected = {
        "e2e-dev-harness",
        "e2e-harness-clarification",
        "e2e-harness-planning",
        "e2e-harness-tdd-red",
        "e2e-harness-implementation",
        "e2e-harness-review",
        "e2e-harness-completion",
    }
    for skill in expected:
        self.assertTrue((ROOT / "skills" / skill / "SKILL.md").exists(), skill)
```

If `tests/test_unified_cli.py` enumerates the installer's skill copy list, extend that assertion to require the same set.

- [ ] **Step 2: Run and observe failures**

```powershell
python -m unittest discover -s tests -p test_unified_cli.py
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: FAIL if installer/packaging does not yet know the new directories.

- [ ] **Step 3: Update install/copy logic + packaging**

In `tools/install-e2e-dev-harness.mjs`, add the six new skill directory names wherever `e2e-dev-harness` is listed for copy/install, keeping the original `e2e-dev-harness` path unchanged. In `pyproject.toml`, add the new skill directories to whatever package-data / include globs currently capture `skills/e2e-dev-harness`.

- [ ] **Step 4: Run installer-related checks**

```powershell
node --check tools\install-e2e-dev-harness.mjs
python -m unittest discover -s tests -p test_unified_cli.py
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tools/install-e2e-dev-harness.mjs tests/test_unified_cli.py tests/test_skill_docs.py
git commit -m "build(install): package six phase worker skills"
```

## Task 11: Broad Verification + GitNexus Change Audit

**Files:**
- No planned source edits unless verification exposes a gap.

- [ ] **Step 1: Run focused suites**

```powershell
python -m unittest discover -s tests -p test_orchestration.py
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
python -m unittest discover -s tests -p test_skill_docs.py
python -m unittest discover -s tests -p test_unified_cli.py
```

Expected: PASS.

- [ ] **Step 2: Run the full suite**

```powershell
python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 3: GitNexus affected-flow audit before commit**

```text
gitnexus_detect_changes({scope: "unstaged"})
```

Expected: affected symbols limited to the capability map/accessors, control-plane normalization seam, context-pack propagation, dispatcher prompt, runtime spawn contract, role templates, scheduler validation, worker skill docs, installer packaging, and tests. Surface anything outside this set.

- [ ] **Step 4: Report residual risk**

Report:

1. Whether legacy schedules without capability fields still pass.
2. Whether `minimal`-tier single-pass runs still plan, claim, dispatch, and complete (capability either maps to implementation or is empty, never blocking).
3. Whether the capability metadata reaches the control plane, schedule projection, context pack, prompt, spawn request, and role template.
4. Whether each new worker skill stayed under 140 lines.
5. Whether the full `unittest` suite passed.
6. Whether GitNexus `detect-changes` reported only expected affected flows.

## Rollout Strategy

1. Land Tasks 1–3 first: capability map, control-plane seam injection, and end-to-end projection evidence. This delivers machine-readable metadata via SSOT with no worker behavior change.
2. Land Tasks 4–5: context-pack propagation and dispatch/spawn surfacing.
3. Land Task 6: additive validation and compatibility proofs.
4. Land Tasks 7–9: worker skills, role-template references, and the coordinator contract doc.
5. Land Task 10 after propagation is stable: installer/packaging.
6. Run Task 11 before any PR.

## Acceptance Criteria

1. Capability metadata is derived at the control-plane normalization seam, never written onto `agent-schedule.json` as an independent source.
2. The schedule projection, `context_pack.build_pack()`, worker prompts, runtime spawn requests (Claude Code + Codex), and role templates all carry `required_skill` / `required_skill_path` (and `skill_reference_set` where applicable).
3. Six compact phase worker skills exist and stay under 140 lines.
4. The main harness skill links `references/phase-skill-capabilities.md`.
5. Legacy schedules and `minimal`-tier single-pass runs remain valid and unblocked.
6. `agent_scheduler.capability_blockers()` blocks only present-but-malformed fields.
7. Focused and full test suites pass.
8. GitNexus `detect-changes` reports only expected affected surfaces before commit.

## Risk Controls

| Risk | Control |
| --- | --- |
| Reopening schedule-as-truth | Inject only at the control-plane seam; never persist capability fields as a schedule-only source. |
| Skill rule drift | Keep hard gates in scripts; keep worker skills short and descriptive. |
| Context bloat from many skills | Coordinator loads only metadata/paths; each worker loads one phase skill. |
| Legacy / minimal-tier breakage | Capability fields additive and optional; unmapped phases carry none and never block. |
| Runtime inconsistency | Test both Task-style and Codex spawn payloads. |
| Reference-set drift | `required_skill_path` validated to resolve in-repo; context-pack `validate` warns on missing skill file. |
| False sense of isolation | Prompts/invocation JSON continue to forbid inherited coordinator chat. |

## Self-Review

**Spec coverage:** Capability map (T1), control-plane SSOT seam (T2), end-to-end projection (T3), context packs (T4), prompt + spawn (T5), compatibility/validation incl. minimal tier (T6), worker skills (T7), role templates (T8), coordinator contract (T9), packaging (T10), verification + GitNexus audit (T11). The two deviations from the 2026-06-04 plan — no authoritative `orchestration_plan.py` schedule writes, and explicit `minimal`-tier degradation — are covered in T2/T3 and T6 respectively.

**Placeholder scan:** Each code step shows concrete code; each command shows expected output. Task 3 Step 3 and Task 8 Step 3 carry explicit conditional fallbacks rather than placeholders, because they depend on how `orchestration_plan.plan()` and `role_template_text()` assemble their output — the engineer is told exactly what to add and the constraint to honor.

**Type consistency:** Field names are uniform throughout: `required_skill`, `required_skill_path`, `skill_reference_set`. Accessors are `phase_required_skill`, `phase_required_skill_path`, `phase_skill_reference_set`. The validation helper is `capability_blockers` in every reference.
