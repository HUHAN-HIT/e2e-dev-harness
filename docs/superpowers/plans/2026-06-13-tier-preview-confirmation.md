# Tier Preview Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `start --preview-tier` path that computes tier options and recommendations without creating a run, so Codex/coordinators can ask the user to choose before normal `start --tier <choice>`.

**Architecture:** Keep `recommend_tier` pure and reuse the existing `start` preparation path for feature/request reading, adapter selection, optional scan evidence, recommendation, and pipeline validation. Add a JSON-only preview branch in `start.run` behind `--preview-tier`; normal `start` remains unchanged and continues to create `run-state.json`.

**Tech Stack:** Python 3.10+, argparse, existing e2e-harness CLI, pytest, GitNexus MCP/CLI for pre-edit impact and pre-commit change detection.

---

## Current Facts To Preserve

- `skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py` defines `start --tier` with default `auto`.
- `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py` currently creates `run-state.json` on every successful call.
- `skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/recommend.py` returns `recommended_tier`, `selected_tier`, `options`, `reasons`, and `downgrade`.
- Normal `start` output schema is `e2e-dev-harness.start.v1`.
- Preview mode must not write `docs/agent-runs/.../run-state.json`.
- The CLI must keep stdout as machine-readable JSON and must not prompt on stdin.

## Files

- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Modify: `skills/e2e-dev-harness/SKILL.md`
- Test: `skills/e2e-dev-harness/tests/test_cli_e2e.py`
- Test: `skills/e2e-dev-harness/tests/test_skill_md.py`

## Pre-Implementation GitNexus Gates

- [ ] Run `git status --short` and keep existing unrelated changes separate from this slice.
- [ ] Refresh GitNexus if stale:

```powershell
npx gitnexus analyze
```

- [ ] Run impact before editing symbols:

```text
impact(target="run", file_path="skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
impact(target="build_parser", file_path="skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
```

- [ ] If either result is HIGH or CRITICAL, stop and report direct callers, affected processes, and risk before editing.

---

### Task 1: Add Failing CLI Tests For Tier Preview

**Files:**
- Test: `skills/e2e-dev-harness/tests/test_cli_e2e.py`

- [ ] **Step 1: Add a test proving preview returns options without creating a run**

Append this test near the existing tier recommendation tests in `skills/e2e-dev-harness/tests/test_cli_e2e.py`:

```python
def test_start_preview_tier_returns_options_without_creating_run_state(tmp_path):
    code, res = _run(
        "start",
        "--preview-tier",
        "--repo",
        str(tmp_path),
        "--feature",
        "tier-preview",
        "--request",
        "rename a helper function",
        cwd=tmp_path,
    )

    assert code == 0
    assert res["schema"] == "e2e-dev-harness.tier-preview.v1"
    assert res["feature"] == "tier-preview"
    assert res["run_will_be_created"] is False
    assert "run_state" not in res
    assert "run_id" not in res
    assert "current_phase" not in res
    assert res["recommended_tier"] == "standard"
    assert res["selected_tier"] == "standard"
    assert [option["tier"] for option in res["tier_recommendation"]["options"]] == [
        "minimal",
        "standard",
        "critical",
        "audited",
    ]
    assert not (tmp_path / "docs" / "agent-runs").exists()
```

- [ ] **Step 2: Add a test proving explicit preview preserves downgrade metadata**

Append this test in the same file:

```python
def test_start_preview_explicit_lower_tier_reports_downgrade(tmp_path):
    code, res = _run(
        "start",
        "--preview-tier",
        "--repo",
        str(tmp_path),
        "--feature",
        "tier-preview-downgrade",
        "--request",
        "add refund settlement to the ledger",
        "--tier",
        "standard",
        cwd=tmp_path,
    )

    assert code == 0
    assert res["recommended_tier"] == "critical"
    assert res["selected_tier"] == "standard"
    assert res["tier_recommendation"]["selection_source"] == "explicit"
    assert res["tier_recommendation"]["downgrade"]["requested_below_recommended"] is True
    assert res["tier_recommendation"]["downgrade"]["requires_provenance"] is True
    assert res["tier_recommendation"]["downgrade"]["blocked"] is False
    assert not (tmp_path / "docs" / "agent-runs").exists()
```

- [ ] **Step 3: Add a test proving custom pipeline override is visible**

Append this test in the same file:

```python
def test_start_preview_with_pipeline_marks_pipeline_override(tmp_path):
    custom = tmp_path / "custom-pipeline.yaml"
    custom.write_text(
        "name: custom\n"
        "phases:\n"
        "  - CREATED\n"
        "  - CLARIFIED\n"
        "  - RED\n"
        "  - phase: IMPLEMENTED\n"
        "    allows_code_write: true\n"
        "  - VERIFIED\n",
        encoding="utf-8",
    )

    code, res = _run(
        "start",
        "--preview-tier",
        "--repo",
        str(tmp_path),
        "--feature",
        "tier-preview-pipeline",
        "--request",
        "rename a helper function",
        "--pipeline",
        str(custom),
        cwd=tmp_path,
    )

    assert code == 0
    assert res["schema"] == "e2e-dev-harness.tier-preview.v1"
    assert res["pipeline"] == str(custom)
    assert res["pipeline_override"] is True
    assert res["tier_controls_pipeline"] is False
    assert res["recommended_tier"] == "standard"
    assert not (tmp_path / "docs" / "agent-runs").exists()
```

- [ ] **Step 4: Run the focused tests and verify they fail**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_cli_e2e.py::test_start_preview_tier_returns_options_without_creating_run_state skills/e2e-dev-harness/tests/test_cli_e2e.py::test_start_preview_explicit_lower_tier_reports_downgrade skills/e2e-dev-harness/tests/test_cli_e2e.py::test_start_preview_with_pipeline_marks_pipeline_override -q
```

Expected: FAIL because `--preview-tier` is not recognized by argparse.

- [ ] **Step 5: Commit the failing tests**

Run:

```powershell
git add skills/e2e-dev-harness/tests/test_cli_e2e.py
git commit -m "test(e2e-harness): define tier preview cli contract"
```

---

### Task 2: Implement `start --preview-tier`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Test: `skills/e2e-dev-harness/tests/test_cli_e2e.py`

- [ ] **Step 1: Add the parser flag**

Modify the `start` parser in `skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py` by adding this argument after `--scan`:

```python
    s.add_argument("--preview-tier", action="store_true",
                   help="compute tier recommendation/options without creating a run")
```

- [ ] **Step 2: Add a preview response helper**

In `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`, add this helper above `run`:

```python
def _preview_result(*, feature: str, adapter_name: str, tier_recommendation: dict,
                    pipeline_ref: str, pipeline_override: bool) -> dict:
    return {
        "schema": "e2e-dev-harness.tier-preview.v1",
        "feature": feature,
        "domain": adapter_name,
        "run_will_be_created": False,
        "recommended_tier": tier_recommendation["recommended_tier"],
        "selected_tier": tier_recommendation["selected_tier"],
        "selection_source": tier_recommendation["selection_source"],
        "tier_reasons": tier_recommendation["reasons"],
        "tier_recommendation": tier_recommendation,
        "pipeline": pipeline_ref,
        "pipeline_override": pipeline_override,
        "tier_controls_pipeline": not pipeline_override,
        "confirmation": {
            "recommended_start_args": [
                "start",
                "--tier",
                tier_recommendation["recommended_tier"],
            ],
            "choice_arg": "--tier <minimal|standard|critical|audited>",
        },
    }
```

- [ ] **Step 3: Return preview before run-state creation**

In `run(args)`, keep the current order through pipeline validation, then insert this branch after `ok, errors = pipeline_validate.validate_spec(merged)` succeeds and before `run_state.new_run_state(...)`:

```python
    if getattr(args, "preview_tier", False):
        return 0, _preview_result(
            feature=feature,
            adapter_name=adapter.name,
            tier_recommendation=tier_recommendation,
            pipeline_ref=str(pipeline_ref),
            pipeline_override=custom,
        )
```

The surrounding code must still compute:

```python
    custom = pipeline.is_path(pipeline_ref)
```

before the preview branch, because the preview response reports `pipeline_override`.

- [ ] **Step 4: Run the focused preview tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_cli_e2e.py::test_start_preview_tier_returns_options_without_creating_run_state skills/e2e-dev-harness/tests/test_cli_e2e.py::test_start_preview_explicit_lower_tier_reports_downgrade skills/e2e-dev-harness/tests/test_cli_e2e.py::test_start_preview_with_pipeline_marks_pipeline_override -q
```

Expected: all three tests PASS.

- [ ] **Step 5: Run existing start-tier regression tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_tier_recommend.py skills/e2e-dev-harness/tests/test_cli_e2e.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit the implementation**

Run:

```powershell
git add skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py
git commit -m "feat(e2e-harness): add tier preview start mode"
```

---

### Task 3: Document The Coordinator Confirmation Contract

**Files:**
- Modify: `skills/e2e-dev-harness/SKILL.md`
- Test: `skills/e2e-dev-harness/tests/test_skill_md.py`

- [ ] **Step 1: Add a documentation test**

Append this test to `skills/e2e-dev-harness/tests/test_skill_md.py`:

```python
def test_skill_md_documents_tier_preview_confirmation():
    text = SKILL.read_text(encoding="utf-8")

    assert "--preview-tier" in text
    assert "tier-preview.v1" in text
    assert "does not create" in text
    assert "run-state.json" in text
    assert "Codex" in text
    assert "start --tier <choice>" in text
```

- [ ] **Step 2: Run the doc test and verify it fails**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_skill_md.py::test_skill_md_documents_tier_preview_confirmation -q
```

Expected: FAIL because the new preview contract is not documented.

- [ ] **Step 3: Update `SKILL.md`**

In `skills/e2e-dev-harness/SKILL.md`, add this subsection under the existing tier recommendation contract:

```markdown
### Tier preview confirmation

Use `start --preview-tier` when Codex should show the user the recommended
workflow before creating a run. The command emits `tier-preview.v1`, includes
the same `tier_recommendation` options as normal `start`, and does not create
`run-state.json`.

Codex should present the recommendation, tier costs, and GitNexus/scanner
reasons to the user. After the user chooses, create the real run with
`start --tier <choice>` using the same repo, feature, request, adapter, scan,
and pipeline inputs.

Do not implement this as a stdin prompt. The CLI remains JSON-only and
non-interactive; the user choice happens in the coordinator conversation.
```

- [ ] **Step 4: Run the doc test**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_skill_md.py::test_skill_md_documents_tier_preview_confirmation -q
```

Expected: PASS.

- [ ] **Step 5: Run tier and docs regression tests**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_skill_md.py skills/e2e-dev-harness/tests/test_tier_recommend.py skills/e2e-dev-harness/tests/test_cli_e2e.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit the docs**

Run:

```powershell
git add skills/e2e-dev-harness/SKILL.md skills/e2e-dev-harness/tests/test_skill_md.py
git commit -m "docs(e2e-harness): document tier preview confirmation"
```

---

### Task 4: Final Verification And Change Detection

**Files:**
- No source edits.

- [ ] **Step 1: Run focused verification**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_tier_recommend.py skills/e2e-dev-harness/tests/test_cli_e2e.py skills/e2e-dev-harness/tests/test_skill_md.py -q -p no:cacheprovider --basetemp C:\tmp\e2e-tier-preview-pytest
```

Expected: all tests PASS.

- [ ] **Step 2: Refresh GitNexus index**

Run:

```powershell
npx gitnexus analyze
```

Expected: repository indexed successfully.

- [ ] **Step 3: Run GitNexus change detection before final commit or merge**

If changes are staged:

```text
detect_changes(scope="staged", repo="e2e-dev-workflow")
```

If the implementation was committed task-by-task:

```text
detect_changes(scope="compare", base_ref="<base-before-task-1>", repo="e2e-dev-workflow")
```

Expected: changed symbols and affected flows align with `start.run`, `build_parser`, CLI tests, and docs. If unrelated dirty files appear, report them separately and do not stage or revert them.

- [ ] **Step 4: Summarize final behavior**

Record these facts in the final handoff:

```text
start --preview-tier returns tier-preview.v1 and creates no run-state.
normal start remains unchanged.
explicit lower tier still records downgrade metadata.
custom --pipeline marks pipeline_override=true and tier_controls_pipeline=false.
CLI remains JSON-only and non-interactive.
```
