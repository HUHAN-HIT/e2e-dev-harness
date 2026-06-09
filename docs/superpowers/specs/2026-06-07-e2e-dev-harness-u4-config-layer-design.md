# Harness e2e-dev-harness �?U4: M3 Config Layer (pipelines-as-config + `validate-pipeline`) �?Design

- **Status:** Approved �?ready for `superpowers:writing-plans`
- **Date:** 2026-06-07
- **Branch:** `e2e-dev-harness-m2`
- **Unit:** U4 of [e2e-dev-harness remaining-work roadmap](../plans/2026-06-07-e2e-dev-harness-remaining-work-roadmap.md)
- **Design source:** [e2e-dev-harness redesign](2026-06-07-e2e-dev-harness-redesign-design.md) §11 (adaptive pruning), §12 (pipelines-as-config), §15 (invariants I1/I2), §16 (YAGNI).

## 1. Goal

Make the orchestration spine **configuration, not hardcode** (design §12). Today the four tiers
(`minimal`/`standard`/`critical`/`audited`) live as Python dict constants in
`scripts/e2e_harness/pipeline.py`. U4:

1. Moves them into shipped declarative `pipelines/*.yaml` interpreted by the state machine �?   built-in tiers become factory config with no special privilege.
2. Lets a user/project supply a **custom** pipeline (phase order, per-phase worker-skill binding,
   per-phase gate/evidence set, tier overrides) by **name or path**.
3. Gates every pipeline (built-in or custom) through the two architecture invariants **before it
   can run**, so a misconfigured pipeline is rejected rather than deadlocking at runtime:
   - **I1 termination** �?the spine reaches a single terminal in finite steps.
   - **I2 gate-closure** �?every required exit-gate evidence is produced by some phase.

**Hard back-compat requirement:** all existing tier / pruning / fan-out / gate-closure tests stay
green (behavior parity). Built-in tier names and their resulting spines are unchanged.

## 2. Decisions (locked in brainstorming)

| # | Decision | Choice |
|---|---|---|
| Q1 | YAML schema scope | **Hybrid** �?a phase entry is either a bare catalog name (inherits defaults) or a mapping that overrides/adds fields. |
| Q2 | `validate-pipeline` surface | **CLI verb + `start` guard** �?explicit preflight verb AND auto-validation inside `start` (architecture refuses to run an invalid pipeline). 7th verb is a deliberate §6 exception. |
| Q3 | Custom-pipeline source | **Name or path** �?`start --pipeline` accepts a built-in name or a filesystem `.yaml` path. No repo-local auto-discovery. |

## 3. YAML schema (hybrid)

Built-in files: `skills/e2e-dev-harness/pipelines/{minimal,standard,critical,audited}.yaml`.

Top level:
- `name: str` �?pipeline identifier.
- `phases: list` �?ordered; each entry is **one of**:
  - a **string** = a phase name present in `lifecycle._CATALOG`; inherits all catalog defaults
    (`worker_role`, `worker_skill`, `produces`, `exit_gate`).
  - a **mapping** with required `phase: <name>` plus any of `worker_role`, `worker_skill`,
    `produces: [..]`, `exit_gate: [..]`:
    - if `<name>` is a **catalog** phase �?mapping overrides only the named fields (mirrors today's
      `overrides` block).
    - if `<name>` is **not** in the catalog (brand-new custom phase) �?the mapping MUST fully specify
      `worker_role`, `worker_skill`, `produces`, `exit_gate` (validation enforces this).

Example (`critical.yaml`):

```yaml
name: critical
phases:
  - CREATED
  - CLARIFIED
  - PLANNED
  - RED
  - IMPLEMENTED
  - phase: REVIEWED
    produces: [r1_review, r2_review, r3_review]
    exit_gate: [r1_review, r2_review, r3_review]
  - VERIFIED
```

`minimal` and `standard` are pure name lists. `audited` additionally overrides `VERIFIED`
(`produces`/`exit_gate` = `[verification, audit_replay]`). These reproduce the current
`pipeline.PIPELINES` constants exactly.

## 4. Loader / interpreter (`pipeline.py` rewrite, public API preserved)

`pipeline.py` stops holding constants and becomes a loader + interpreter:

- `load_spec(name_or_path) -> dict` �?resolves a built-in **name** to `pipelines/<name>.yaml`;
  a value ending in `.yaml`/`.yml` or containing a path separator is read as a file path.
  Raises a clear error for an unknown name / unreadable path.
- `spec_to_spine(spec) -> list[lifecycle.Phase]` �?interprets `phases`: string �?catalog lookup;
  mapping �?catalog base with field overrides, or fully-inline `Phase` for a non-catalog name;
  wires `next_phase` linearly (each entry points to the next; last is `None`).
- `build_spine(name) -> list[Phase]` and `active_phase_names(name) -> list[str]` �?kept for
  back-compat; now implemented as `name �?load_spec �?spec_to_spine`. Every existing call
  (`pipeline.build_spine("critical")`, `pipeline.active_phase_names("minimal")`, the
  `test_unknown_pipeline_raises` KeyError contract) keeps working.
- `spine_for_state(state: dict) -> list[Phase]` �?single seam used by the CLI: returns
  `spec_to_spine(state["pipeline_spec"])` when an embedded spec is present, else
  `build_spine(state.get("pipeline", "minimal"))`.

The four CLI commands that currently call `pipeline.build_spine(state.get("pipeline", "minimal"))`
(`next`, `dispatch`, `gate`, `status`) switch to `pipeline.spine_for_state(state)`.

## 5. Validation (`core/pipeline_validate.py`)

`validate_spec(spec: dict) -> tuple[bool, list[str]]` �?pure, no I/O:

- **Schema checks:** `name` present and non-empty; `phases` is a non-empty list; each entry is a
  string or a mapping with a `phase` key; a non-catalog phase mapping supplies all of
  `worker_role`, `worker_skill`, `produces`, `exit_gate`; evidence keys are non-empty strings.
- **I1 termination:** phase names unique; the built spine is a single linear chain with exactly one
  terminal (`next_phase is None`) and no dangling or cyclic `next_phase`. (Structurally guaranteed
  by the linear builder; validation asserts the spec can't violate it.)
- **I2 gate-closure:** build the spine, run `gates.gate_closure_ok(spine)`; every required
  `exit_gate` evidence key must be in some phase's `produces`.

Returns `(True, [])` when valid, else `(False, [<clear error strings>])`. Errors are plain strings
suitable for direct JSON emission.

## 6. `validate-pipeline` CLI verb (7th verb �?deliberate §6 exception)

`e2e-dev-harness validate-pipeline --pipeline <name-or-path>`:
- loads the spec, runs `validate_spec`, emits JSON `{"ok": bool, "pipeline": <name-or-path>, "errors": [...]}`.
- exit `0` when valid, `1` when invalid, `2` on load/parse error (consistent with `main.py`'s
  existing exception-to-JSON contract).
- `main.py` documents this as the explicit M3 exception to the "35 �?6 verbs" rule (§6).

## 7. `start` guard + custom source

- `start` gains optional `--pipeline <name-or-path>`. Effective pipeline = `--pipeline` if supplied,
  else the resolved `--tier` name (back-compat: `--tier critical` still maps to the `critical`
  pipeline; `--tier auto` still classifies first).
- `start` resolves the spec �?runs `validate_spec`:
  - **invalid** �?emit `{"error": "invalid pipeline", "errors": [...]}`, exit non-zero, and write
    **no** run-state (architecture refuses to run an unsatisfiable pipeline, §12).
  - **valid** �?write run-state. For a **built-in name**, store `pipeline: <name>` only (shipped &
    stable �?no spec embed needed). For a **custom path**, embed the resolved spec into
    `state["pipeline_spec"]` so the run is hermetic (SSOT per §1; robust to the file changing
    mid-run). `tier` is still recorded as today.
- `run_state.new_run_state` gains an optional `pipeline_spec` parameter (default `None`, omitted
  from the JSON when absent) �?additive, no schema-version bump; old run-states (no `pipeline_spec`)
  still load and resolve via the named fallback in `spine_for_state`.

## 8. Tests (TDD order)

1. `test_pipeline_yaml_load.py` �?each built-in loads from yaml; hybrid string/mapping parsing;
   resulting spines are equal to the pre-U4 constant-built spines (parity).
2. `test_pipeline_validate.py` �?a valid custom spec passes; an unsatisfiable one (required evidence
   with no producing phase �?I2) is rejected with an I2 error; a non-terminating / dangling-`next`
   spec (I1) is rejected; a non-catalog phase missing required fields is rejected.
3. `test_cli_validate_pipeline.py` �?verb returns correct JSON + exit code for a valid built-in, a
   valid custom path, and an invalid custom path.
4. `test_cli_custom_pipeline_e2e.py` �?a user custom `.yaml` drives `start �?VERIFIED`
   (hermetic via embedded `pipeline_spec`); an unsatisfiable custom `.yaml` is rejected at `start`
   with no run-state written.

Existing suites (`test_pipeline_tiers.py`, `test_gate_closure.py`, `test_tier_classify.py`,
`test_tier_escalation.py`, `test_cli_e2e.py`, �? stay unchanged and green.

## 9. Affected files

**New:**
- `skills/e2e-dev-harness/pipelines/{minimal,standard,critical,audited}.yaml`
- `skills/e2e-dev-harness/scripts/e2e_harness/core/pipeline_validate.py`
- `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/validate_pipeline.py`
- 4 test files (§8).

**Edited (e2e-dev-harness-internal only �?no legacy edits per §15):**
- `scripts/e2e_harness/pipeline.py` �?constants �?loader/interpreter + `spine_for_state`.
- `scripts/e2e_harness/core/run_state.py` �?optional `pipeline_spec` field.
- `scripts/e2e_harness/cli/main.py` �?register `validate-pipeline`; add `start --pipeline`.
- `scripts/e2e_harness/cli/commands/start.py` �?pipeline resolution + validation guard + embed.
- `scripts/e2e_harness/cli/commands/{next,dispatch,gate,status}.py` �?use `spine_for_state`.

## 10. Out of scope (YAGNI, §16)

- Pipeline inheritance / `includes` / mixins.
- Env-var or template interpolation inside yaml.
- A JSON-Schema validation dependency (hand-rolled checks are enough for this schema).
- Repo-local `pipelines/` auto-discovery (path is explicit �?the "name OR path" decision).
- Branching / DAG spines �?spines remain a single linear chain.
- Per-phase entry-contract config (not modeled in the current `Phase`; add only if a real flow needs it).

## 11. Risk / invariants note

- Per CLAUDE.md, run `gitnexus_impact` before editing existing e2e-dev-harness symbols (`pipeline.build_spine`,
  `run_state.new_run_state`, the four CLI command `run` functions) and `gitnexus_detect_changes`
  before committing. The GitNexus index may be stale �?refresh with `npx gitnexus analyze` if any
  tool warns.
- No legacy edits before M5 (§15): all changes are new e2e-dev-harness files or e2e-dev-harness-internal edits.
