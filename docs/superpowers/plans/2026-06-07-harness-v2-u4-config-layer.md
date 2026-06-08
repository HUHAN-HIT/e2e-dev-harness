# Harness v2 — U4 M3 Config Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the four hardcoded `pipeline.PIPELINES` constants into shipped declarative `pipelines/*.yaml`, let users supply a custom pipeline by name or path, and gate every pipeline through I1 (termination) + I2 (gate-closure) before it can run.

**Architecture:** `pipeline.py` becomes a YAML loader + interpreter (hybrid schema: a phase entry is a bare catalog name or an override/inline mapping) while preserving its public API. A pure `core/pipeline_validate.validate_spec` enforces the two invariants. A 7th CLI verb `validate-pipeline` exposes preflight; `start` runs the same validation as a guard and embeds the resolved spec into run-state for custom pipelines so the run is hermetic.

**Tech Stack:** Python 3.13, PyYAML 6.0.3 (already installed), pytest. All work is inside `skills/e2e-dev-harness-v2/`; no legacy edits (design §15).

**Spec:** [2026-06-07-harness-v2-u4-config-layer-design.md](../specs/2026-06-07-harness-v2-u4-config-layer-design.md)

**Test command (run from `skills/e2e-dev-harness-v2/`):** `python -m pytest -q`

---

## Task 0: Preflight — refresh index + impact baseline

CLAUDE.md mandates `gitnexus_impact` before editing existing symbols and `gitnexus_detect_changes` before committing. This task edits existing symbols (`pipeline.build_spine`, `run_state.new_run_state`, the four CLI `run` functions).

- [ ] **Step 1: Refresh the stale GitNexus index**

Run (from repo root): `npx gitnexus analyze`
Expected: index rebuilt; no "stale" warnings on subsequent MCP calls.

- [ ] **Step 2: Confirm green baseline**

Run (from `skills/e2e-dev-harness-v2/`): `python -m pytest -q`
Expected: `136 passed`.

- [ ] **Step 3: Impact check the symbols this plan edits**

Run `gitnexus_impact({target: "build_spine", direction: "upstream"})` and `gitnexus_impact({target: "new_run_state", direction: "upstream"})`. Report blast radius. Expected: callers are the four CLI commands + `start`; risk LOW–MEDIUM (all v2-internal). If HIGH/CRITICAL, warn before proceeding.

---

## Task 1: Built-in YAML files + `pipeline.py` loader/interpreter

**Files:**
- Create: `skills/e2e-dev-harness-v2/pipelines/minimal.yaml`
- Create: `skills/e2e-dev-harness-v2/pipelines/standard.yaml`
- Create: `skills/e2e-dev-harness-v2/pipelines/critical.yaml`
- Create: `skills/e2e-dev-harness-v2/pipelines/audited.yaml`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/pipeline.py` (full rewrite)
- Test: `skills/e2e-dev-harness-v2/tests/test_pipeline_yaml_load.py`

- [ ] **Step 1: Write the four built-in YAML files**

`pipelines/minimal.yaml`:
```yaml
name: minimal
phases:
  - CREATED
  - CLARIFIED
  - RED
  - IMPLEMENTED
  - VERIFIED
```

`pipelines/standard.yaml`:
```yaml
name: standard
phases:
  - CREATED
  - CLARIFIED
  - PLANNED
  - RED
  - IMPLEMENTED
  - REVIEWED
  - VERIFIED
```

`pipelines/critical.yaml`:
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

`pipelines/audited.yaml`:
```yaml
name: audited
phases:
  - CREATED
  - CLARIFIED
  - PLANNED
  - RED
  - IMPLEMENTED
  - phase: REVIEWED
    produces: [r1_review, r2_review, r3_review]
    exit_gate: [r1_review, r2_review, r3_review]
  - phase: VERIFIED
    produces: [verification, audit_replay]
    exit_gate: [verification, audit_replay]
```

- [ ] **Step 2: Write the failing test**

`tests/test_pipeline_yaml_load.py`:
```python
import pytest

from harness_v2 import pipeline


def test_minimal_loads_from_yaml_and_skips_planned_reviewed():
    names = pipeline.active_phase_names("minimal")
    assert names == ["CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"]


def test_standard_is_full_spine_single_reviewer():
    spine = pipeline.build_spine("standard")
    assert [p.name for p in spine] == [
        "CREATED", "CLARIFIED", "PLANNED", "RED", "IMPLEMENTED", "REVIEWED", "VERIFIED"]
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    assert reviewed.exit_gate == ("review",)
    assert reviewed.worker_skill == "e2e-harness-review"  # inherited from catalog


def test_critical_reviewed_overrides_to_three_reviews():
    spine = pipeline.build_spine("critical")
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    assert reviewed.produces == ("r1_review", "r2_review", "r3_review")
    assert reviewed.exit_gate == ("r1_review", "r2_review", "r3_review")
    assert reviewed.worker_skill == "e2e-harness-review"  # non-overridden field inherited


def test_audited_overrides_verified_and_reviewed():
    spine = pipeline.build_spine("audited")
    verified = next(p for p in spine if p.name == "VERIFIED")
    assert verified.exit_gate == ("verification", "audit_replay")
    assert verified.next_phase is None


def test_next_phase_wired_linearly():
    spine = pipeline.build_spine("standard")
    for a, b in zip(spine, spine[1:]):
        assert a.next_phase == b.name
    assert spine[-1].next_phase is None


def test_unknown_builtin_name_raises_keyerror():
    with pytest.raises(KeyError):
        pipeline.active_phase_names("nope")


def test_load_spec_from_path(tmp_path):
    f = tmp_path / "custom.yaml"
    f.write_text("name: c\nphases: [CREATED, CLARIFIED, VERIFIED]\n", encoding="utf-8")
    spine = pipeline.spec_to_spine(pipeline.load_spec(str(f)))
    assert [p.name for p in spine] == ["CREATED", "CLARIFIED", "VERIFIED"]


def test_is_path_distinguishes_names_from_paths():
    assert pipeline.is_path("foo.yaml") is True
    assert pipeline.is_path("dir/foo.yml") is True
    assert pipeline.is_path("critical") is False


def test_spine_for_state_prefers_embedded_spec():
    spec = {"name": "x", "phases": ["CREATED", "VERIFIED"]}
    spine = pipeline.spine_for_state({"pipeline": "standard", "pipeline_spec": spec})
    assert [p.name for p in spine] == ["CREATED", "VERIFIED"]


def test_spine_for_state_falls_back_to_named_builtin():
    spine = pipeline.spine_for_state({"pipeline": "minimal"})
    assert [p.name for p in spine] == ["CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_pipeline_yaml_load.py -q`
Expected: FAIL — `AttributeError: module 'harness_v2.pipeline' has no attribute 'load_spec'` (and `spec_to_spine`/`is_path`/`spine_for_state`).

- [ ] **Step 4: Rewrite `pipeline.py`**

Replace the entire contents of `scripts/harness_v2/pipeline.py` with:
```python
"""Pipeline config: declarative pipelines loaded from `pipelines/*.yaml`.

Hybrid schema — each `phases` entry is either a bare catalog phase name
(inherits `lifecycle._CATALOG` defaults) or a mapping `{phase, ...overrides}`.
Public API (`build_spine`, `active_phase_names`) is preserved; built-in tier
names resolve to shipped yaml with no special privilege.
"""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import yaml

from harness_v2.core import lifecycle
from harness_v2.core.lifecycle import Phase

_PIPELINES_DIR = Path(__file__).resolve().parents[2] / "pipelines"
_OVERRIDE_FIELDS = ("worker_role", "worker_skill", "produces", "exit_gate")


def is_path(name_or_path: str) -> bool:
    """A custom pipeline reference is a path (vs a built-in name)."""
    return name_or_path.endswith((".yaml", ".yml")) or os.sep in name_or_path or "/" in name_or_path


def load_spec(name_or_path: str) -> dict:
    """Resolve a built-in name to `pipelines/<name>.yaml`, or read a file path."""
    if is_path(name_or_path):
        p = Path(name_or_path)
        if not p.is_file():
            raise FileNotFoundError(f"pipeline file not found: {name_or_path}")
    else:
        p = _PIPELINES_DIR / f"{name_or_path}.yaml"
        if not p.is_file():
            raise KeyError(f"unknown pipeline: {name_or_path}")
    spec = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError(f"pipeline spec must be a mapping: {name_or_path}")
    return spec


def _entry_name_and_overrides(entry) -> tuple[str, dict]:
    if isinstance(entry, str):
        return entry, {}
    if not isinstance(entry, dict) or "phase" not in entry:
        raise ValueError(f"invalid phase entry: {entry!r}")
    overrides = {}
    for k in _OVERRIDE_FIELDS:
        if k in entry:
            overrides[k] = tuple(entry[k]) if k in ("produces", "exit_gate") else entry[k]
    return entry["phase"], overrides


def spec_to_spine(spec: dict) -> list[Phase]:
    catalog = lifecycle.catalog()
    parsed = [_entry_name_and_overrides(e) for e in spec["phases"]]
    names = [n for n, _ in parsed]
    spine: list[Phase] = []
    for i, (name, overrides) in enumerate(parsed):
        nxt = names[i + 1] if i + 1 < len(names) else None
        if name in catalog:
            spine.append(replace(catalog[name], next_phase=nxt, **overrides))
        else:  # non-catalog phase: must be fully specified (validation enforces)
            spine.append(Phase(
                name=name,
                worker_role=overrides["worker_role"],
                worker_skill=overrides["worker_skill"],
                produces=overrides["produces"],
                exit_gate=overrides["exit_gate"],
                next_phase=nxt,
            ))
    return spine


def active_phase_names(pipeline: str) -> list[str]:
    return [n for n, _ in (_entry_name_and_overrides(e) for e in load_spec(pipeline)["phases"])]


def build_spine(pipeline: str) -> list[Phase]:
    return spec_to_spine(load_spec(pipeline))


def spine_for_state(state: dict) -> list[Phase]:
    """Single seam for the CLI: embedded spec (hermetic custom run) else named built-in."""
    spec = state.get("pipeline_spec")
    if spec:
        return spec_to_spine(spec)
    return build_spine(state.get("pipeline", "minimal"))
```

- [ ] **Step 5: Run the new test to verify it passes**

Run: `python -m pytest tests/test_pipeline_yaml_load.py -q`
Expected: PASS (10 tests).

- [ ] **Step 6: Run the back-compat suites**

Run: `python -m pytest tests/test_pipeline_tiers.py tests/test_gate_closure.py -q`
Expected: PASS (existing tier/closure tests unchanged and green — parity).

- [ ] **Step 7: Commit**

```bash
git add skills/e2e-dev-harness-v2/pipelines skills/e2e-dev-harness-v2/scripts/harness_v2/pipeline.py skills/e2e-dev-harness-v2/tests/test_pipeline_yaml_load.py
git commit -m "feat(harness-v2): U4 pipelines-as-config — built-in tiers as yaml + loader/interpreter

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `validate_spec` — schema + I1 + I2

**Files:**
- Create: `skills/e2e-dev-harness-v2/scripts/harness_v2/core/pipeline_validate.py`
- Test: `skills/e2e-dev-harness-v2/tests/test_pipeline_validate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline_validate.py`:
```python
from harness_v2.core import pipeline_validate as pv


def test_builtin_specs_are_valid():
    from harness_v2 import pipeline
    for name in ("minimal", "standard", "critical", "audited"):
        ok, errors = pv.validate_spec(pipeline.load_spec(name))
        assert ok is True, f"{name}: {errors}"


def test_valid_custom_spec_passes():
    spec = {"name": "c", "phases": ["CREATED", "CLARIFIED", "VERIFIED"]}
    ok, errors = pv.validate_spec(spec)
    assert ok is True and errors == []


def test_i2_unsatisfiable_evidence_rejected():
    spec = {"name": "c", "phases": [
        "CREATED",
        {"phase": "CLARIFIED", "exit_gate": ["clarification", "ghost"]},
        "VERIFIED",
    ]}
    ok, errors = pv.validate_spec(spec)
    assert ok is False
    assert any("ghost" in e and "I2" in e for e in errors)


def test_i1_duplicate_phase_name_rejected():
    spec = {"name": "c", "phases": ["CREATED", "CLARIFIED", "CLARIFIED", "VERIFIED"]}
    ok, errors = pv.validate_spec(spec)
    assert ok is False
    assert any("duplicate" in e.lower() for e in errors)


def test_empty_phases_rejected():
    ok, errors = pv.validate_spec({"name": "c", "phases": []})
    assert ok is False
    assert any("phases" in e for e in errors)


def test_missing_name_rejected():
    ok, errors = pv.validate_spec({"phases": ["CREATED", "VERIFIED"]})
    assert ok is False
    assert any("name" in e for e in errors)


def test_noncatalog_phase_missing_fields_rejected():
    spec = {"name": "c", "phases": [
        "CREATED",
        {"phase": "AUDIT"},  # not in catalog, missing required fields
        "VERIFIED",
    ]}
    ok, errors = pv.validate_spec(spec)
    assert ok is False
    assert any("AUDIT" in e and "missing" in e for e in errors)


def test_noncatalog_phase_fully_specified_passes():
    spec = {"name": "c", "phases": [
        "CREATED",
        {"phase": "AUDIT", "worker_role": "auditor", "worker_skill": "e2e-harness-completion",
         "produces": ["audit"], "exit_gate": ["audit"]},
        {"phase": "VERIFIED", "produces": ["verification", "audit"], "exit_gate": ["verification", "audit"]},
    ]}
    ok, errors = pv.validate_spec(spec)
    assert ok is True, errors


def test_invalid_entry_type_rejected():
    ok, errors = pv.validate_spec({"name": "c", "phases": [123, "VERIFIED"]})
    assert ok is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_pipeline_validate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness_v2.core.pipeline_validate'`.

- [ ] **Step 3: Write `core/pipeline_validate.py`**

```python
"""Pipeline spec validation: schema + I1 termination + I2 gate-closure.

Pure (no I/O). Built-in and custom specs alike must pass before they may run.
"""
from __future__ import annotations

from harness_v2 import pipeline
from harness_v2.core import lifecycle, gates

_REQUIRED_FOR_CUSTOM = ("worker_role", "worker_skill", "produces", "exit_gate")


def validate_spec(spec) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(spec, dict):
        return False, ["spec must be a mapping"]

    name = spec.get("name")
    if not name or not isinstance(name, str):
        errors.append("missing or empty 'name'")

    phases = spec.get("phases")
    if not isinstance(phases, list) or not phases:
        errors.append("'phases' must be a non-empty list")
        return False, errors

    catalog = lifecycle.catalog()
    seen: set[str] = set()
    for entry in phases:
        if isinstance(entry, str):
            pname = entry
            if pname not in catalog:
                errors.append(
                    f"unknown catalog phase '{pname}' (string entries must name a catalog phase)")
        elif isinstance(entry, dict) and "phase" in entry:
            pname = entry["phase"]
            if not isinstance(pname, str) or not pname:
                errors.append(f"phase entry has empty 'phase': {entry!r}")
                continue
            if pname not in catalog:
                missing = [f for f in _REQUIRED_FOR_CUSTOM if f not in entry]
                if missing:
                    errors.append(f"custom phase '{pname}' missing required fields: {missing}")
            for k in ("produces", "exit_gate"):
                if k in entry and (not isinstance(entry[k], list)
                                   or any(not isinstance(x, str) or not x for x in entry[k])):
                    errors.append(f"phase '{pname}' field '{k}' must be a list of non-empty strings")
        else:
            errors.append(
                f"invalid phase entry (name string or mapping with 'phase'): {entry!r}")
            continue
        if pname in seen:
            errors.append(f"duplicate phase '{pname}'")
        seen.add(pname)

    if errors:
        return False, errors

    try:
        spine = pipeline.spec_to_spine(spec)
    except Exception as exc:  # noqa: BLE001 — surface as a validation error
        return False, [f"spec not buildable: {exc}"]

    # I1 termination: linear chain with a single terminal, every next resolvable.
    spine_names = {p.name for p in spine}
    terminals = [p for p in spine if p.next_phase is None]
    if len(terminals) != 1 or spine[-1].next_phase is not None:
        errors.append("I1 termination: spine must have exactly one terminal phase")
    for p in spine:
        if p.next_phase is not None and p.next_phase not in spine_names:
            errors.append(f"I1 termination: phase '{p.name}' points to unknown next '{p.next_phase}'")

    # I2 gate-closure: every required evidence has a producer.
    ok, unmet = gates.gate_closure_ok(spine)
    if not ok:
        errors.append(f"I2 gate-closure: required evidence with no producing phase: {unmet}")

    return (not errors, errors)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_pipeline_validate.py -q`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness-v2/scripts/harness_v2/core/pipeline_validate.py skills/e2e-dev-harness-v2/tests/test_pipeline_validate.py
git commit -m "feat(harness-v2): U4 validate_spec — schema + I1 termination + I2 gate-closure

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `validate-pipeline` CLI verb

**Files:**
- Create: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/validate_pipeline.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/main.py`
- Test: `skills/e2e-dev-harness-v2/tests/test_cli_validate_pipeline.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli_validate_pipeline.py`:
```python
import json
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness_v2.py"


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def test_validate_builtin_is_ok(tmp_path):
    code, res = _run("validate-pipeline", "--pipeline", "critical", cwd=tmp_path)
    assert code == 0
    assert res["ok"] is True and res["errors"] == []
    assert res["pipeline"] == "critical"


def test_validate_valid_custom_path_is_ok(tmp_path):
    f = tmp_path / "good.yaml"
    f.write_text("name: g\nphases: [CREATED, CLARIFIED, VERIFIED]\n", encoding="utf-8")
    code, res = _run("validate-pipeline", "--pipeline", str(f), cwd=tmp_path)
    assert code == 0 and res["ok"] is True


def test_validate_unsatisfiable_custom_path_is_rejected(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text(
        "name: b\nphases:\n  - CREATED\n  - phase: CLARIFIED\n    exit_gate: [clarification, ghost]\n  - VERIFIED\n",
        encoding="utf-8")
    code, res = _run("validate-pipeline", "--pipeline", str(f), cwd=tmp_path)
    assert code == 1
    assert res["ok"] is False
    assert any("ghost" in e for e in res["errors"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_cli_validate_pipeline.py -q`
Expected: FAIL — argparse error (`invalid choice: 'validate-pipeline'`) → non-JSON stderr → `json.loads("{}")` then `KeyError`/assert fails.

- [ ] **Step 3: Write the command**

`scripts/harness_v2/cli/commands/validate_pipeline.py`:
```python
"""validate-pipeline: preflight I1/I2 check on a pipeline (name or path)."""
from __future__ import annotations

from harness_v2 import pipeline
from harness_v2.core import pipeline_validate


def run(args) -> tuple[int, dict]:
    spec = pipeline.load_spec(args.pipeline)  # load/parse error -> main.py emits error JSON (exit 2)
    ok, errors = pipeline_validate.validate_spec(spec)
    return (0 if ok else 1), {
        "schema": "e2e-dev-harness-v2.validate-pipeline.v1",
        "ok": ok,
        "pipeline": args.pipeline,
        "errors": errors,
    }
```

- [ ] **Step 4: Wire it into `main.py`**

In `scripts/harness_v2/cli/main.py`, update the import line to add `validate_pipeline`:
```python
from harness_v2.cli.commands import start, next as next_cmd, dispatch, submit, gate, status, validate_pipeline
```

Add to the `_COMMANDS` dict (note: comment marks the deliberate §6 exception):
```python
_COMMANDS = {
    "start": start.run, "next": next_cmd.run, "dispatch": dispatch.run,
    "submit": submit.run, "gate": gate.run, "status": status.run,
    # 7th verb — deliberate design §6 exception for the M3 config layer (U4).
    "validate-pipeline": validate_pipeline.run,
}
```

In `build_parser`, before `return p`, register the subparser:
```python
    vp = sub.add_parser("validate-pipeline"); vp.add_argument("--pipeline", required=True)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_cli_validate_pipeline.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/validate_pipeline.py skills/e2e-dev-harness-v2/scripts/harness_v2/cli/main.py skills/e2e-dev-harness-v2/tests/test_cli_validate_pipeline.py
git commit -m "feat(harness-v2): U4 validate-pipeline CLI verb (7th verb, M3 exception)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `start` guard + `--pipeline` + run-state embed + `spine_for_state` wiring

**Files:**
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/core/run_state.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/start.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/main.py` (add `start --pipeline`)
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/next.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/dispatch.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/gate.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/status.py`
- Test: `skills/e2e-dev-harness-v2/tests/test_cli_custom_pipeline_e2e.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli_custom_pipeline_e2e.py`:
```python
import json
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness_v2.py"


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def _make_artifact(repo: Path, phase: str, key: str) -> str:
    from harness_v2.adapters.evidence import command_evidence as ce
    base = repo / "docs" / "agent-runs" / "art"
    base.mkdir(parents=True, exist_ok=True)
    if key in ("failing_tests", "passing_tests"):
        code = 1 if key == "failing_tests" else 0
        ev = ce.record_command(repo, f'"{sys.executable}" -c "import sys; sys.exit({code})"')
        f = base / f"{phase}-{key}.json"
        f.write_text(json.dumps(ev), encoding="utf-8")
    else:
        f = base / f"{phase}-{key}.md"
        f.write_text(f"# {phase} {key}\nreal\n", encoding="utf-8")
    return str(f.relative_to(repo))


def test_custom_pipeline_drives_to_verified(tmp_path):
    custom = tmp_path / "custom.yaml"
    custom.write_text("name: c\nphases: [CREATED, CLARIFIED, VERIFIED]\n", encoding="utf-8")
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", "--pipeline", str(custom), cwd=tmp_path)
    assert code == 0
    state_path = res["run_state"]
    # run-state is hermetic: it embedded the resolved spec
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    assert state["pipeline_spec"]["phases"] == ["CREATED", "CLARIFIED", "VERIFIED"]

    steps = 0
    nres = {"complete": False}
    while steps < 10:
        steps += 1
        code, nres = _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
        if nres["complete"]:
            break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            rel = _make_artifact(tmp_path, phase, key)
            _run("submit", "--state", state_path, "--phase", phase,
                 "--key", key, "--path", rel, "--repo", str(tmp_path), cwd=tmp_path)
    assert nres["complete"] is True
    assert nres["navigation_map"]["you_are_here"] == "VERIFIED"


def test_unsatisfiable_custom_pipeline_rejected_at_start_no_run_state(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: b\nphases:\n  - CREATED\n  - phase: CLARIFIED\n    exit_gate: [clarification, ghost]\n  - VERIFIED\n",
        encoding="utf-8")
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", "--pipeline", str(bad), cwd=tmp_path)
    assert code != 0
    assert res.get("error") == "invalid pipeline"
    assert any("ghost" in e for e in res["errors"])
    # no run-state was written
    assert not list((tmp_path / "docs" / "agent-runs").glob("*/run-state.json"))


def test_builtin_start_records_name_not_spec(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", "--tier", "standard", cwd=tmp_path)
    assert code == 0
    state = json.loads(Path(res["run_state"]).read_text(encoding="utf-8"))
    assert state["pipeline"] == "standard"
    assert "pipeline_spec" not in state  # built-ins stay lean
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_cli_custom_pipeline_e2e.py -q`
Expected: FAIL — argparse rejects unknown `--pipeline` on `start` (no JSON) → assertion failure.

- [ ] **Step 3: Add the optional `pipeline_spec` field to `run_state.new_run_state`**

In `scripts/harness_v2/core/run_state.py`, replace the `new_run_state` function with:
```python
def new_run_state(run_id: str, feature: str, request: str,
                  tier: str = "minimal", pipeline: str = "minimal",
                  pipeline_spec: dict | None = None,
                  now: str | None = None) -> dict:
    ts = _stamp(now)
    state = {
        "schema": SCHEMA,
        "run_id": run_id,
        "feature": feature,
        "request": request,
        "tier": tier,
        "pipeline": pipeline,
        "current_phase": "CREATED",
        "phases": {},
        "created_at": ts,
        "updated_at": ts,
    }
    if pipeline_spec is not None:
        state["pipeline_spec"] = pipeline_spec
    return state
```

- [ ] **Step 4: Add `start --pipeline` to `main.py`**

In `scripts/harness_v2/cli/main.py`, in the `start` subparser block, add the optional argument after the `--tier` line:
```python
    s.add_argument("--pipeline", default=None,
                   help="built-in name or path to a custom pipeline yaml (overrides --tier's spine)")
```

- [ ] **Step 5: Rewrite `start.py` with the resolution + validation guard + embed**

Replace the entire body of `scripts/harness_v2/cli/commands/start.py` with:
```python
"""start: create the one run-state (after validating its pipeline)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from harness_v2.core import run_state, pipeline_validate
from harness_v2 import pipeline


def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.feature
    tier = args.tier
    reasons: list[str] = []
    if tier == "auto":
        from harness_v2.adapters.tier import classify
        tier, reasons = classify.classify_tier(args.request)

    pipeline_ref = getattr(args, "pipeline", None) or tier
    spec = pipeline.load_spec(pipeline_ref)  # load/parse error -> main.py emits error JSON (exit 2)
    ok, errors = pipeline_validate.validate_spec(spec)
    if not ok:
        return 2, {"error": "invalid pipeline", "pipeline": pipeline_ref, "errors": errors}

    custom = pipeline.is_path(pipeline_ref)
    rel = Path("docs/agent-runs") / run_id / "run-state.json"
    path = repo / rel
    st = run_state.new_run_state(
        run_id, args.feature, args.request, tier=tier, pipeline=pipeline_ref,
        pipeline_spec=spec if custom else None)
    run_state.save(path, st)
    return 0, {"schema": "e2e-dev-harness-v2.start.v1", "run_id": run_id,
               "run_state": str(path), "current_phase": "CREATED",
               "tier": tier, "pipeline": pipeline_ref, "tier_reasons": reasons}
```

- [ ] **Step 6: Switch the four CLI consumers to `spine_for_state`**

In each of `next.py`, `dispatch.py`, `gate.py`, `status.py`, replace the line
`spine = pipeline.build_spine(state.get("pipeline", "minimal"))`
with:
`spine = pipeline.spine_for_state(state)`

(`next.py` line 14, `dispatch.py` line 11, `gate.py` line 12, `status.py` line 12 — all identical text.)

- [ ] **Step 7: Run the new e2e test to verify it passes**

Run: `python -m pytest tests/test_cli_custom_pipeline_e2e.py -q`
Expected: PASS (3 tests).

- [ ] **Step 8: Run the existing CLI e2e suite (back-compat)**

Run: `python -m pytest tests/test_cli_e2e.py tests/test_cli_error_json.py -q`
Expected: PASS (default-tier start, drive-to-VERIFIED, dispatch, gate all unchanged).

- [ ] **Step 9: Commit**

```bash
git add skills/e2e-dev-harness-v2/scripts/harness_v2/core/run_state.py skills/e2e-dev-harness-v2/scripts/harness_v2/cli
git add skills/e2e-dev-harness-v2/tests/test_cli_custom_pipeline_e2e.py
git commit -m "feat(harness-v2): U4 start validates+embeds pipeline; CLI rebuilds spine via spine_for_state

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Full-suite verification + change scope

- [ ] **Step 1: Run the full v2 suite**

Run (from `skills/e2e-dev-harness-v2/`): `python -m pytest -q`
Expected: all green — `136` prior + new tests (10 + 10 + 3 + 3 = 26) ≈ `162 passed`. No failures, no skips.

- [ ] **Step 2: Confirm change scope**

Run `gitnexus_detect_changes()`. Expected: only U4 symbols/files affected (pipeline, pipeline_validate, run_state.new_run_state, the start/next/dispatch/gate/status commands, validate_pipeline). No legacy (`skills/e2e-dev-harness/`) files touched. If anything unexpected appears, stop and investigate.

- [ ] **Step 3: Confirm no legacy edits**

Run (from repo root): `git diff --name-only ce3a7a7..HEAD -- skills/e2e-dev-harness/`
Expected: empty output (design §15 — legacy frozen until M5).

- [ ] **Step 4: Update the roadmap status**

In `docs/superpowers/plans/2026-06-07-harness-v2-remaining-work-roadmap.md`, add a bullet to the "Done so far" section: "**M3 config layer (U4)**: pipelines-as-config + validate-pipeline + custom pipelines. ✅". Commit:
```bash
git add docs/superpowers/plans/2026-06-07-harness-v2-remaining-work-roadmap.md
git commit -m "docs(harness-v2): mark U4 (M3 config layer) done in roadmap

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** §3 schema → Task 1 yaml + `_entry_name_and_overrides`/`spec_to_spine`. §4 loader → Task 1. §5 validation → Task 2. §6 verb → Task 3. §7 start guard + embed + run_state field → Task 4. §8 tests → all four test files across Tasks 1–4. §9 affected files → all covered. §10 YAGNI → no inheritance/interpolation/auto-discovery/DAG in any task.
- **Placeholder scan:** none — every code step shows full content.
- **Type consistency:** `load_spec`/`spec_to_spine`/`is_path`/`spine_for_state` signatures used identically in Tasks 1–4; `validate_spec(spec)->(bool, list[str])` consistent across Tasks 2–4; `new_run_state(..., pipeline_spec=None)` matches its caller in `start.py`; run-state key `pipeline_spec` consistent in builder, `spine_for_state`, and the e2e test.
- **I1 note:** with a linear builder, termination is structural; the testable I1 rejection is the duplicate-phase-name hazard (corrupts the engine's name-keyed walk) — covered by `test_i1_duplicate_phase_name_rejected`.
