# Loop Engineering Control Plane Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Loop Engineering hardening gaps that block honest productization: verification replay coverage, grounded delivery status, safe module fan-out, read-only run diagnosis, and tamper-evident event truth.

**Architecture:** Keep `run-state.json` as the compatibility projection while tightening the evidence and scheduling contracts around it. Add small, testable seams: replay allow-list branches in evidence validation, module grounding in scope validation, conflict-group filtering in multitrack scheduling, namespace ownership checks in evidence submission, a separate `doctor --state` diagnosis path, and a chained event log before any branding or UI work.

**Tech Stack:** Python stdlib, existing `e2e_harness` modules, pytest/unittest tests under `skills/e2e-dev-harness/tests`, GitNexus impact analysis for symbol edits.

**Out of scope (deferred):** Phase 3 `recover` (approval-gated recovery) is intentionally NOT in this plan. Per the design's recommended sequence (`docs/loop-engineering-control-plane-design.md:467-474`), recovery is sequenced with/after tamper-evident event projection; this plan lands fidelity, fan-out safety, read-only diagnosis, and the event-log seam first, and leaves `recover` to a follow-up.

---

## Preconditions

- Before modifying any function, class, or method, run GitNexus impact analysis for that symbol and record the risk in the worker handoff.
- Keep existing CLI JSON shapes stable unless the task explicitly introduces a new `--state` schema.
- Do not edit worker-owned artifacts or generated run outputs as part of these implementation tasks.
- Use repo-local temp settings for Windows test runs when broad tests are needed: `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `TMP=.test-tmp`, `TEMP=.test-tmp`, and `--basetemp=.test-tmp/<slice>`.

## File Structure

- Modify `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/validate.py`: extend replay command allow-list while preserving strict test-command checks.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/scope.py`: ground delivered module ids in `label_delivery` against trusted engine-owned run-state (`REVIEWED#<id>` chain completion). The gate-time validator stays tables-only (it has no run-state) — a documented weakening.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/core/module_plan.py`: accept optional `conflict_groups` as named shared resources and expose them to scheduling.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/core/multitrack.py`: filter module fan-out by declared conflict groups without repo I/O; add `completed_modules(spine, state)` (cheap exit-gate-presence check, no repo I/O) for scope phase-grounding (Task 2).
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/core/engine.py`: add module namespace ownership validation for evidence submission when worker identity is supplied.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/submit.py`: pass worker identity to `submit_evidence` when invocation metadata is available.
- Modify `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/doctor.py`: keep default installer readiness behavior and add `--state` run diagnosis dispatch.
- Create `skills/e2e-dev-harness/scripts/e2e_harness/core/state_diagnosis.py`: compute first blocking run fact without mutation or replay.
- Create `skills/e2e-dev-harness/scripts/e2e_harness/core/event_log.py`: append canonical chained events and verify event chains.
- Create `skills/e2e-dev-harness/scripts/e2e_harness/core/state_store.py`: replay event chains into compatibility projections.
- Add or extend tests in `skills/e2e-dev-harness/tests/test_evidence_validation.py`, `test_scope_evidence.py`, `test_module_plan.py`, `test_multitrack.py`, `test_submit_evidence.py`, `test_cli_doctor.py`, and `test_event_log.py`.

### Task 1: Verification Replay Allow-List

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/validate.py:95`
- Test: `skills/e2e-dev-harness/tests/test_evidence_validation.py`

- [ ] **Step 1: Run impact analysis**

Run:

```powershell
gitnexus_impact target="_replay_command_allowed" direction="upstream" repo="e2e-dev-workflow"
```

Expected: risk is reviewed before editing. If risk is HIGH or CRITICAL, stop and report the blast radius before changing code.

- [ ] **Step 2: Write failing allow-list tests**

Add tests that assert these commands are allowed:

```python
def test_replay_allows_first_class_test_commands():
    allowed = [
        "go test ./...",
        "cargo test --all",
        "pnpm test",
        "pnpm run test",
        "yarn test",
        "yarn run test",
        "npx jest --runInBand",
        "npx jest test",
    ]
    for command in allowed:
        assert validate._replay_command_allowed(command), command
```

Add tests that assert non-test commands stay blocked:

```python
def test_replay_rejects_non_test_commands_for_new_runners():
    rejected = [
        "go build ./...",
        "cargo build",
        "pnpm install",
        "yarn add lodash",
        "npx jest --init",
    ]
    for command in rejected:
        assert not validate._replay_command_allowed(command), command
```

- [ ] **Step 3: Run the focused failing tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_evidence_validation.py -q
```

Expected: new allowed-command cases fail with `AssertionError`.

- [ ] **Step 4: Implement strict branches**

First add a module-level deny-list near the other runner sets (`validate.py:66-68`):

```python
# jest sub-commands/flags that are NOT a test run. A bare `npx jest` and flag-only
# runs (e.g. `npx jest --runInBand`) ARE full test runs, so we cannot require a
# "test" token; instead we reject jest's known non-test entry points.
_JEST_NON_TEST_ARGS = {"--init", "--help", "-h", "--version", "-v"}
```

Then **replace the existing single-line `npx` branch** (`validate.py:110-111`) with the version below and add the `go`/`cargo`/`pnpm`/`yarn` branches. Removing the old `npx` one-liner is required — leaving both makes the new branch unreachable and re-introduces the `npx jest --init` leak:

```python
    if name == "npx":
        if not args:
            return False
        runner = _command_name(args[0])
        rest = args[1:]
        if runner in _NODE_TEST_COMMANDS:        # vitest / playwright: unchanged, strict
            return "test" in rest
        if runner == "jest":                      # bare/flag jest = full test run; deny non-test subcommands
            return not (rest and rest[0] in _JEST_NON_TEST_ARGS)
        return False
    if name == "go":                              # first subcommand must be `test`
        return args[:1] == ["test"]
    if name == "cargo":                           # must invoke the `test` subcommand (stricter than `"test" in args`)
        return args[:1] == ["test"]
    if name in {"pnpm", "yarn"}:                  # mirror the npm rule
        return args[:1] == ["test"] or args[:2] == ["run", "test"]
```

Keep the existing Python, npm, node, Maven and Gradle behavior unchanged. Do NOT add `jest` to `_NODE_TEST_COMMANDS`: that set requires a literal `test` token and would wrongly reject the required positive case `npx jest --runInBand`. Per-case trace confirming Step 2's tests pass:

| Command | branch | result |
| --- | --- | --- |
| `go test ./...` | go → `args[:1]==["test"]` | ALLOW ✓ |
| `cargo test --all` | cargo → `args[:1]==["test"]` | ALLOW ✓ |
| `pnpm test` / `pnpm run test` | pnpm/yarn | ALLOW ✓ |
| `yarn test` / `yarn run test` | pnpm/yarn | ALLOW ✓ |
| `npx jest --runInBand` | npx→jest, `--runInBand` ∉ deny-list | ALLOW ✓ |
| `npx jest test` | npx→jest, `test` ∉ deny-list | ALLOW ✓ |
| `go build ./...` | go → `["build"]!=["test"]` | REJECT ✓ |
| `cargo build` | cargo → `["build"]!=["test"]` | REJECT ✓ |
| `pnpm install` / `yarn add lodash` | pnpm/yarn | REJECT ✓ |
| `npx jest --init` | npx→jest, `--init` ∈ deny-list | REJECT ✓ |

- [ ] **Step 5: Verify focused tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_evidence_validation.py -q
```

Expected: all tests in the file pass.

### Task 2: Ground Delivered Modules In Scope Manifest

> **Correction (2026-06-13):** an earlier draft grounded `phases` by reading run-state from `obj.get("state")` inside the gate validator. That is circular — `obj` is the worker-produced manifest, so the worker would ground its own delivery — and it keyed completion off `VERIFIED#<id>` records that never exist (`MODULE_SCOPED=(RED,IMPLEMENTED,REVIEWED)`; `VERIFIED` is a whole-run singleton). The gate validator `validate_scope_manifest(obj, repo_root)` is invoked with **no run-state** (`validate.py:147` `STRUCTURED_KEYS['scope_manifest'](obj, repo_root)`; `gates.py` passes only a single phase-record), so gate-time module grounding is infeasible without a new cross-cutting seam. This task instead grounds `phases` at **completion time** in `label_delivery` (which already holds trusted engine-owned state) and leaves the gate validator tables-only.
>
> **Signature note (verified 2026-06-13):** `label_delivery(state, repo_root)` ALREADY has this exact signature (`adapters/evidence/scope.py:66`); its current body is `return _effective(obj, repo_root)` where `_effective` = `assess(obj["expected"], _ground(obj["delivered"], repo_root))`. So Step 4 is an **in-body INSERT** (filter `delivered["phases"]` against `completed_modules` before assessing), NOT a signature change. Inlining `_ground`+`assess` as shown reproduces `_effective` exactly — do not drop the existing grounding path, and keep `validate_scope_manifest`/`_effective` (gate-time) untouched.

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/scope.py:66` (`label_delivery`)
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/multitrack.py` (add `completed_modules`)
- Test: `skills/e2e-dev-harness/tests/test_scope_evidence.py`

- [ ] **Step 1: Run impact analysis**

Run:

```powershell
gitnexus_impact target="label_delivery" direction="upstream" repo="e2e-dev-workflow"
gitnexus_impact target="module_chains" direction="upstream" repo="e2e-dev-workflow"
```

Expected: blast radius is recorded before editing. `label_delivery`'s only production caller is `next.py` on `res['complete']`, with the engine-mutated (trusted) state (`next.py:23-24`) — confirm before editing. (`completed_modules` is new code in `multitrack.py`, so it has no upstream callers yet.)

- [ ] **Step 2: Write failing module-grounding test**

Ground `phases` against trusted run-state via `label_delivery`. Two constraints drive the fixture, both verified against the code:

1. `label_delivery` rebuilds the spine internally via `pipeline.spine_for_state(state, repo_root)` (`pipeline.py:115`), which only expands into per-module tracks when `state["phases"]["PLANNED"]["evidence"]["module_plan"]` resolves to a **valid on-disk module plan with ≥2 modules**. So the fixture MUST write a real `module-plan.json` and reference it — otherwise the spine stays unexpanded, `module_chains` is empty, and grounding is a no-op.
2. `completed_modules` uses a **cheap exit-gate-presence check** (no `validate_evidence`), so `{"path": "x"}` placeholder evidence is sufficient — no genuine command-evidence needed. This is sound because `label_delivery` is only called once the run is `complete` (every gate already validated).

Because the join barrier means a `complete` run has every planned module finished, the honest PARTIAL case is a manifest that **overclaims a phase that was never a module** (here `reporting`):

```python
def test_label_delivery_grounds_phases_against_completed_modules(tmp_path):
    import json
    from e2e_harness import pipeline
    from e2e_harness.core import multitrack, module_plan
    from e2e_harness.core import scope as scope_core
    from e2e_harness.adapters.evidence import scope

    # 2-module plan on disk so spine_for_state expands into per-module tracks.
    mplan = {"schema": module_plan.SCHEMA, "modules": [
        {"id": "auth", "name": "auth", "depends_on": [], "acceptance_ids": ["AC-001"]},
        {"id": "billing", "name": "billing", "depends_on": [], "acceptance_ids": ["AC-002"]},
    ]}
    (tmp_path / "module-plan.json").write_text(json.dumps(mplan), encoding="utf-8")

    spine = multitrack.expand(pipeline.build_spine("standard"), mplan)
    by = {p.name: p for p in spine}
    state = {"phases": {"PLANNED": {"evidence": {"module_plan": {"path": "module-plan.json"}}}}}

    def _complete(*names):  # mark every exit_gate key of each module phase as present
        for n in names:
            state["phases"][n] = {"evidence": {k: {"path": "x"} for k in by[n].exit_gate}}

    # Both real modules finished (the only state in which a run is `complete`).
    _complete("RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth",
              "RED#billing", "IMPLEMENTED#billing", "REVIEWED#billing")

    # Manifest overclaims a third phase `reporting` that was never a module.
    man = {"schema": scope_core.SCHEMA, "status": "PARTIAL",
           "expected":  {"services": [], "tables": [], "phases": ["auth", "billing", "reporting"]},
           "delivered": {"services": [], "tables": [], "phases": ["auth", "billing", "reporting"]}}
    (tmp_path / "scope.json").write_text(json.dumps(man), encoding="utf-8")
    state["phases"]["VERIFIED"] = {"evidence": {"scope_manifest": {"path": "scope.json"}}}

    status, undelivered = scope.label_delivery(state, tmp_path)

    assert status == "PARTIAL"
    assert undelivered["phases"] == ["reporting"]   # ungrounded: never a completed module
```

Completion is asserted via the `exit_gate` keys of each `REVIEWED#<id>` (e.g. `review#auth`), exactly as the engine marks a track complete — there is NO `VERIFIED#<id>` key anywhere.

- [ ] **Step 3: Run the focused failing test**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_scope_evidence.py -q
```

Expected: the grounding test fails because `label_delivery` currently passes `phases` through self-declared.

- [ ] **Step 4: Implement completion-time grounding**

Add `completed_modules` to `multitrack.py` (a module counts as delivered iff every phase in its chain — `RED#<id>`/`IMPLEMENTED#<id>`/`REVIEWED#<id>` — has all its `exit_gate` keys present in run-state evidence). This is a **cheap presence check, NOT** `gate_passes`: it does no `validate_evidence`/replay, because `label_delivery` only runs once the whole run is `complete` (every gate already validated). It mirrors the `_satisfied` idiom already used in `ready_frontier` (`multitrack.py:109-110`) and keys off `REVIEWED#<id>` chain completion, never `VERIFIED#<id>`:

```python
def completed_modules(spine: list[Phase], state: dict) -> set[str]:
    def _evidence(name: str) -> dict:
        return state.get("phases", {}).get(name, {}).get("evidence", {})
    out: set[str] = set()
    for mid, chain in module_chains(spine).items():
        if all(all(k in _evidence(p.name) for k in p.exit_gate) for p in chain):
            out.add(mid)
    return out
```

In `label_delivery` (`scope.py:66-81`), after loading `obj`, rebuild the spine for the trusted state and intersect delivered `phases` with the completed set before assessing — importing `pipeline`/`multitrack` locally to avoid an import cycle (mirroring `engine.py:212`):

```python
def label_delivery(state: dict, repo_root) -> tuple[str | None, dict]:
    entry = (state.get("phases", {}).get("VERIFIED", {})
             .get("evidence", {}).get("scope_manifest"))
    if not entry:
        return None, {}
    rel = entry["path"] if isinstance(entry, dict) else entry
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel
    try:
        obj = json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, {}
    from e2e_harness import pipeline                 # local imports: avoid import cycle
    from e2e_harness.core import multitrack
    spine = pipeline.spine_for_state(state, repo_root)
    completed = multitrack.completed_modules(spine, state)
    delivered = dict(obj.get("delivered", {}))
    phases = delivered.get("phases") or []
    if phases:
        delivered["phases"] = [p for p in phases if p in completed]
    return scope_core.assess(obj.get("expected", {}), _ground(delivered, repo_root))
```

Leave the gate-time validator (`validate_scope_manifest` / `_ground`, `scope.py:34-63`) UNCHANGED except a comment that `phases`/`services` are taken as declared at gate time (no run-state available). **Documented weakening:** a `phases` overclaim passes the VERIFIED submit gate; it is downgraded to PARTIAL here at completion, against trusted state — never against the worker's own `obj`. Gate-time phase grounding would require threading the whole `state` through `validate_evidence -> STRUCTURED_KEYS`, a larger change deferred to the follow-up that also grounds `services`.

Why presence (not `gate_passes`) is correct here: `label_delivery` is reached only on `res["complete"]` (`next.py:23`), i.e. after `all_gates_pass` validated every key — so presence ⟹ validated at this point, and re-validating/replaying would be redundant and would make the unit test require genuine command-evidence. `pipeline.spine_for_state(state, repo_root)` only expands when PLANNED carries a valid ≥2-module plan resolvable under `repo_root`; absent that it returns the unexpanded spine, `module_chains` is empty, and grounding is a safe no-op.

- [ ] **Step 5: Verify focused tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_scope_evidence.py -q
```

Expected: scope evidence tests pass.

### Task 3: Module Fan-Out Safety Floor

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/module_plan.py:35`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/multitrack.py:92`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/engine.py:15`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/submit.py`
- Test: `skills/e2e-dev-harness/tests/test_module_plan.py`
- Test: `skills/e2e-dev-harness/tests/test_multitrack.py`
- Test: `skills/e2e-dev-harness/tests/test_submit_evidence.py`

- [ ] **Step 1: Run impact analysis**

Run:

```powershell
gitnexus_impact target="validate_module_plan" direction="upstream" repo="e2e-dev-workflow"
gitnexus_impact target="ready_frontier" direction="upstream" repo="e2e-dev-workflow"
gitnexus_impact target="submit_evidence" direction="upstream" repo="e2e-dev-workflow"
```

Expected: blast radius is reviewed before editing. If any result is HIGH or CRITICAL, report before edits.

- [ ] **Step 2: Write failing conflict-group tests**

Add module-plan validation tests:

```python
def test_module_plan_accepts_conflict_groups():
    obj = {
        "schema": module_plan.SCHEMA,
        "modules": [
            {
                "id": "auth",
                "name": "Auth",
                "depends_on": [],
                "acceptance_ids": ["AC-001"],
                "conflict_groups": ["db:migrations", "npm:lockfile"],
            }
        ],
    }
    assert module_plan.validate_module_plan(obj) == (True, None)
```

Add a scheduler test:

```python
def test_ready_frontier_withholds_shared_conflict_group():
    mplan = {
        "modules": [
            {"id": "auth", "name": "Auth", "depends_on": [], "acceptance_ids": ["AC-001"], "conflict_groups": ["db:migrations"]},
            {"id": "billing", "name": "Billing", "depends_on": [], "acceptance_ids": ["AC-002"], "conflict_groups": ["db:migrations"]},
        ]
    }
    frontier = multitrack.ready_frontier(spine, {"phases": {}}, mplan)
    assert [p.name for p in frontier] == ["RED#auth"]
```

- [ ] **Step 3: Write failing ownership tests**

Add a direct engine-level test:

```python
def test_submit_evidence_rejects_cross_module_worker_claim():
    state = {}
    with pytest.raises(ValueError, match="worker-module-mismatch"):
        engine.submit_evidence(
            state,
            "IMPLEMENTED#billing",
            "passing_tests#billing",
            "handoffs/IMPLEMENTED-passing_tests.json",
            worker_id="IMPLEMENTED#auth",
        )
```

- [ ] **Step 4: Run focused failing tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_module_plan.py skills/e2e-dev-harness/tests/test_multitrack.py skills/e2e-dev-harness/tests/test_submit_evidence.py -q
```

Expected: new conflict-group and ownership tests fail.

- [ ] **Step 5: Implement conflict-group validation**

In `module_plan._validate_module`, accept optional string lists:

```python
    groups = mod.get("conflict_groups", [])
    if not isinstance(groups, list) or not all(isinstance(g, str) and g.strip() for g in groups):
        return mid, f"bad-conflict-groups:{mid}"
```

Add a helper:

```python
def conflict_groups(obj) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    for mod in obj.get("modules", []):
        if isinstance(mod, dict) and "id" in mod:
            groups[mod["id"]] = set(mod.get("conflict_groups", []) or [])
    return groups
```

- [ ] **Step 6: Implement cheap frontier filtering**

In `ready_frontier`, after computing candidate phases, keep deterministic order and withhold later modules that share a conflict group with an already selected module:

```python
    groups = {
        m["id"]: set(m.get("conflict_groups", []) or [])
        for m in mplan.get("modules", [])
        if isinstance(m, dict) and "id" in m
    }
    selected: list[Phase] = []
    active_groups: set[str] = set()
    for phase in frontier:
        mid = module_of(phase.name)
        phase_groups = groups.get(mid or "", set())
        if active_groups.intersection(phase_groups):
            continue
        selected.append(phase)
        active_groups.update(phase_groups)
    return selected
```

- [ ] **Step 7: Implement namespace ownership guard**

Extend `submit_evidence` with optional `worker_id`:

```python
def _module_suffix(value: str) -> str | None:
    return value.split("#", 1)[1] if "#" in value else None
```

```python
    phase_module = _module_suffix(phase_name)
    key_module = _module_suffix(key)
    worker_module = _module_suffix(worker_id or "")
    if phase_module and key_module and phase_module != key_module:
        raise ValueError("phase-key-module-mismatch")
    if phase_module and worker_module and phase_module != worker_module:
        raise ValueError("worker-module-mismatch")
```

**Residual-risk wording (be honest about what this guard does and does not do):**

No trusted, harness-controlled identity reaches the submit path today. `e2e-dev-harness submit` accepts only `--phase/--key/--path/--status/--reason` (`cli/main.py:60-63`); `engine.submit_evidence(...)` records `evidence[key] = {path, sha256, bytes}` keyed solely by phase+key, with no producer/owner dimension (`engine.py:15-36`). To pass a `worker_id` at all, `submit.py` would need a NEW `--worker-id` argument — which the worker itself supplies. A harness-derived worker id DOES exist at dispatch time (`dispatch` writes `{phase}-default` / `producer_ids` into the `dispatch-invocation.v1` / `agent-team-plan.json` artifacts, `cli/commands/dispatch.py`), but `submit` never reads it and `submit_evidence` never validates against it, so there is currently no binding from a submitted evidence key back to a dispatched worker.

Therefore frame the guard precisely:

- With a self-supplied `worker_id`, the guard only prevents **accidental** mislabeling (a worker writing under the wrong namespace by mistake). It is **defense-in-depth, not an authorization boundary**: an adversarial worker can pass any `worker_id` (including another module's) and write into any namespace.
- To make it *enforce* a trusted binding, a later task must cross-check the submitted namespace against the dispatch-time `producer_ids` (harness-controlled), not against the value the worker hands to `submit`.
- **Explicit residual risk — manual / identity-less runtime:** for non-auto-spawn runtimes, `dispatch` records a `blocked` entry and a human runs `submit` with no descriptor/worker_id binding at all; even a future `producer_ids` cross-check degrades to accidental-mislabel protection there. Do not invent a fake worker id to paper over this.

- [ ] **Step 8: Verify focused tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_module_plan.py skills/e2e-dev-harness/tests/test_multitrack.py skills/e2e-dev-harness/tests/test_submit_evidence.py -q
```

Expected: all focused tests pass.

### Task 4: Read-Only `doctor --state`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/doctor.py:8` (branch on `args.state`; import `run_state` + `state_diagnosis`)
- No change needed: `skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py` already defines `doctor --state <path>` (`main.py:72`)
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/state_diagnosis.py`
- Test: `skills/e2e-dev-harness/tests/test_cli_doctor.py`

- [ ] **Step 1: Run impact analysis**

Run:

```powershell
gitnexus_impact target="run" file_path="skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/doctor.py" direction="upstream" repo="e2e-dev-workflow"
```

Expected: blast radius is reviewed before editing.

- [ ] **Step 2: Write compatibility tests**

The real `doctor` parser already has `--state` as the **run-state path** (`cli/main.py:72` `doc.add_argument("--state", default=None, ...)`), so `args.state is None` selects installer mode and `args.state == <path>` selects run diagnosis. There is no boolean `state` and no separate `--run-state`; the tests must match that.

Add a test that default `doctor` (no `--state`) remains installer readiness:

```python
def test_doctor_default_schema_remains_installer_readiness(tmp_path):
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False, state=None)
    code, payload = doctor.run(args)
    assert code == 0
    assert payload["schema"] == "e2e-dev-harness.doctor.v1"
    assert "checks" in payload
```

Add a test for `doctor --state <path>` (singleton phase):

```python
def test_doctor_state_reports_first_missing_evidence(tmp_path):
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED",
        "phases": {"IMPLEMENTED": {"evidence": {}}},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False, state=str(run_state), repo=".")
    code, payload = doctor.run(args)
    assert code == 2
    assert payload["schema"] == "e2e-dev-harness.doctor-state.v1"
    assert payload["diagnosis_ready"] is True
    assert payload["run_blocked"] is True
    assert payload["first_fault"]["kind"] == "missing_evidence"
    assert payload["missing_evidence"] == ["passing_tests", "test_substance"]
    assert payload["next_legal_command"].startswith("e2e-dev-harness dispatch --state")
```

Add a test for a **namespaced module-band phase** — the case where diagnosis matters most (a stuck multi-module run). `current_phase` is namespaced and required keys must be derived by base-naming the phase, then re-namespacing:

```python
def test_doctor_state_handles_namespaced_module_phase(tmp_path):
    run_state = tmp_path / "run-state.json"
    run_state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "current_phase": "IMPLEMENTED#auth",
        "phases": {"IMPLEMENTED#auth": {"evidence": {}}},
    }), encoding="utf-8")
    args = SimpleNamespace(project_root=str(tmp_path), runtime="claude", strict=False, state=str(run_state), repo=".")
    code, payload = doctor.run(args)
    assert code == 2
    assert payload["blocked_phase"] == "IMPLEMENTED#auth"
    assert payload["missing_evidence"] == ["passing_tests#auth", "test_substance#auth"]
```

- [ ] **Step 3: Run focused failing tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_cli_doctor.py -q
```

Expected: `--state` test fails because no state diagnosis path exists.

- [ ] **Step 4: Implement `state_diagnosis.py`**

Derive required keys from the lifecycle catalog and **handle namespaced module-band phases**: a `current_phase` like `IMPLEMENTED#auth` must be base-named to look up the catalog `exit_gate`, then the keys re-namespaced with the module suffix.

```python
from pathlib import Path
from e2e_harness.core import lifecycle, multitrack


def _required_keys_for_phase(phase_name: str | None) -> list[str]:
    """exit_gate keys for a phase, namespaced when the phase is module-scoped.
    'IMPLEMENTED#auth' -> ['passing_tests#auth', 'test_substance#auth'];
    'IMPLEMENTED'      -> ['passing_tests', 'test_substance']."""
    if not phase_name:
        return []
    base = multitrack.base_phase_name(phase_name)   # 'IMPLEMENTED#auth' -> 'IMPLEMENTED'
    mod = multitrack.module_of(phase_name)          # 'IMPLEMENTED#auth' -> 'auth' (None if singleton)
    phase = lifecycle.catalog().get(base)
    if phase is None:
        return []
    return list(phase.exit_gate) if mod is None else [f"{k}#{mod}" for k in phase.exit_gate]


def diagnose_run(state: dict, state_path: str, repo: str = ".") -> dict:
    current = state.get("current_phase")
    rec = (state.get("phases") or {}).get(current or "", {})
    evidence = rec.get("evidence") or {}
    required = _required_keys_for_phase(current)
    missing = [key for key in required if key not in evidence]
    first = None
    if missing:
        first = {
            "kind": "missing_evidence",
            "phase": current,
            "task_id": None,
            "message": f"{missing[0]} evidence is missing",
        }
    # next_legal_command is derived from the REAL CLI verb set — prog `e2e-dev-harness`,
    # commands start/next/dispatch/submit/gate/status/doctor/migrate, flags
    # `--state <run-state-path>` / `--repo` (see cli/main.py). It is NOT a target-lifecycle
    # fiction: there is no `dispatch-beat` command and no `--run-dir` flag. A missing-evidence
    # block is cleared by dispatching the blocked phase's worker, i.e. `dispatch`.
    next_cmd = (f"e2e-dev-harness dispatch --state {state_path} --repo {repo}"
                if first else None)
    return {
        "schema": "e2e-dev-harness.doctor-state.v1",
        "diagnosis_ready": True,
        "run_blocked": bool(first),
        "run_dir": str(Path(state_path).parent),
        "first_fault": first,
        "blocked_phase": current if first else None,
        "blocked_task": None,
        "missing_evidence": missing,
        "next_legal_command": next_cmd,
        "coordinator_may_write_worker_outputs": False,
    }
```

This reuses `lifecycle.catalog()` + `multitrack.base_phase_name`/`module_of` rather than duplicating phase constants, and works for both singleton and module-band phases.

- [ ] **Step 5: Wire the existing `--state` flag (no new parser field)**

`cli/main.py:72` already defines `doctor --state <path>` as the run-state path (`default=None`). Do NOT add a `--run-state` flag and do NOT introduce a boolean `state`. Branch at the top of `doctor.run(args)` on whether a path was supplied:

```python
    # --state carries the run-state path (cli/main.py:72); None => installer readiness.
    state_path = getattr(args, "state", None)
    if state_path:
        return _run_state_diagnosis(args, state_path)
```

```python
def _run_state_diagnosis(args, state_path):
    state = run_state.load(state_path)
    payload = state_diagnosis.diagnose_run(state, state_path, getattr(args, "repo", "."))
    return (2 if payload["run_blocked"] else 0), payload
```

Default `doctor` behavior (when `args.state is None`) must remain byte-compatible for installer tests — the existing installer-readiness body is untouched.

- [ ] **Step 6: Verify focused tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_cli_doctor.py -q
```

Expected: doctor tests pass.

### Task 5: Tamper-Evident Event Log

> **Scope note:** this task ships `event_log.py` and `state_store.py` as an UNWIRED, independently-tested seam. It is NOT wired into the run-state write path — `run_state.mutate` is deliberately left untouched. Per the control-plane design, events are the authoritative source and `run-state.json` is the *output* of event replay, not a co-write target (design Phase 4, `docs/loop-engineering-control-plane-design.md:408-429`: "replay events into run-state.json projection"; Non-Goal "keep run-state.json as a compatibility projection"). Coupling `append_event` into `mutate` requires an event-type-derivation layer (`mutate` sees only an opaque post-mutation dict, not the semantic event type `state_store.replay_events` switches on) and is a separate projection task, sequenced last in the design's recommended order (`design:467-474`). Tracked for that follow-up, not this task. (This removes the earlier phantom `run_state.py` edit target.)

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/event_log.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/state_store.py`
- Test: `skills/e2e-dev-harness/tests/test_event_log.py`

- [ ] **Step 1: Confirm scope (no existing-symbol edit)**

This task only creates new modules, so there is no existing symbol to run GitNexus impact analysis on, and `run_state.py` is intentionally NOT modified. Proceed to the event-chain tests.

- [ ] **Step 2: Write event-chain tests**

Add tests for append and verify:

```python
def test_event_log_detects_modified_event(tmp_path):
    path = tmp_path / "events.jsonl"
    first = event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    second = event_log.append_event(path, {"type": "gate.passed", "run_id": "r1", "phase": "CLARIFIED"})
    assert first["event_hash"]
    assert second["prev_event_hash"] == first["event_hash"]
    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = lines[1].replace("gate.passed", "gate.failed")
    path.write_text(lines[0] + "\n" + tampered + "\n", encoding="utf-8")
    ok, reason = event_log.verify_chain(path)
    assert not ok
    assert reason == "event-hash-mismatch:2"
```

Add tests for deletion/reordering:

```python
def test_event_log_detects_reordered_event(tmp_path):
    path = tmp_path / "events.jsonl"
    event_log.append_event(path, {"type": "run.started", "run_id": "r1"})
    event_log.append_event(path, {"type": "phase.submitted", "run_id": "r1", "phase": "CLARIFIED"})
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[1] + "\n" + lines[0] + "\n", encoding="utf-8")
    ok, reason = event_log.verify_chain(path)
    assert not ok
    assert reason.startswith("event-chain-broken")
```

- [ ] **Step 3: Run focused failing tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_event_log.py -q
```

Expected: import or function-not-found failure.

- [ ] **Step 4: Implement canonical event log**

Create canonical serialization:

```python
def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

Create event hashing:

```python
def _hash_event(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
```

Append events with sequence and previous hash:

```python
def append_event(path: Path, payload: dict) -> dict:
    events = read_events(path)
    prev = events[-1]["event_hash"] if events else None
    event = dict(payload)
    event["schema"] = "e2e-dev-harness.event.v1"
    event["sequence"] = len(events) + 1
    event["prev_event_hash"] = prev
    event["event_hash"] = _hash_event({k: v for k, v in event.items() if k != "event_hash"})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(_canonical(event) + "\n")
    return event
```

Verify chains by recomputing `sequence`, `prev_event_hash`, and `event_hash`.

- [ ] **Step 5: Implement projection replay shell**

In `state_store.py`, add a narrow replay function for the first event set:

```python
def replay_events(events: list[dict]) -> dict:
    state = {"phases": {}}
    for event in events:
        etype = event.get("type")
        phase = event.get("phase")
        if etype == "run.started":
            state["run_id"] = event.get("run_id")
        elif etype == "phase.submitted" and phase:
            state["current_phase"] = phase
        elif etype == "gate.passed" and phase:
            state.setdefault("phases", {}).setdefault(phase, {})["dispatch"] = "done"
        elif etype == "gate.failed" and phase:
            rec = state.setdefault("phases", {}).setdefault(phase, {})
            rec["dispatch"] = "failed"
            rec["blocker"] = event.get("reason")
    return state
```

- [ ] **Step 6: Verify focused tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_event_log.py -q
```

Expected: event log tests pass.

### Final Verification

- [ ] **Step 1: Run affected Python tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_evidence_validation.py skills/e2e-dev-harness/tests/test_scope_evidence.py skills/e2e-dev-harness/tests/test_module_plan.py skills/e2e-dev-harness/tests/test_multitrack.py skills/e2e-dev-harness/tests/test_submit_evidence.py skills/e2e-dev-harness/tests/test_cli_doctor.py skills/e2e-dev-harness/tests/test_event_log.py -q
```

Expected: all affected tests pass.

- [ ] **Step 2: Run GitNexus change detection**

Run:

```powershell
gitnexus_detect_changes scope="all" repo="e2e-dev-workflow"
```

Expected: affected symbols match this plan: evidence validation, scope validation, multitrack scheduling, submit evidence, doctor diagnosis, event log/state store.

- [ ] **Step 3: Run package-surface checks when ready to ship**

Run:

```powershell
npm pack --dry-run
```

Expected: new source/test/docs files intended for package or repo review appear as expected; generated temp files do not appear.
