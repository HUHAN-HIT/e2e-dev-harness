# Risk-Aware Tier Options Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `start --tier auto` produce explicit tier options, a recommended tier, and an auditable selected tier that accounts for text, scanner scope, and GitNexus impact evidence.

**Architecture:** Keep the existing keyword classifier as a pure leaf and add a small recommendation layer that builds option objects from classifier output plus structured evidence. `start` remains the only CLI integration point: auto adopts the recommendation for non-interactive runs, while explicit `--tier` is recorded as a user selection with downgrade metadata. GitNexus evidence is consumed from scanner scope when present and never becomes a hidden background side effect.

**Tech Stack:** Python 3.10+, pytest/unittest, existing e2e-harness CLI, GitNexus MCP/CLI for impact and change detection.

---

## Current Facts To Preserve

- `start --tier auto` is the default in `skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py`.
- `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py` only calls the classifier when `args.tier == "auto"`.
- `skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/classify.py` maps request text and optional scanner scope to one tier.
- Auto mode currently floors plain requests to `standard`; explicit `--tier minimal` remains an opt-down.
- Scanner scope currently raises the floor to `standard` for two or more services and `critical` for cross-service dependencies.
- Existing GitNexus evidence lives under scanner results, especially `gitnexus.verified`, `gitnexus.evidence`, `warnings`, and dependency evidence.

## Files

- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/recommend.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/__init__.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/scanner/_legacy/cross_service_dependency_scan.py`
- Test: `skills/e2e-dev-harness/tests/test_tier_recommend.py`
- Test: `skills/e2e-dev-harness/tests/test_tier_classify.py`
- Test: `skills/e2e-dev-harness/tests/test_cli_e2e.py`
- Test: `skills/e2e-dev-harness/tests/test_scanner.py`
- Optional docs: `skills/e2e-dev-harness/SKILL.md`

## Pre-Implementation GitNexus Gates

- [ ] Run `git status --short` and keep existing user changes separate from this slice.
- [ ] Run GitNexus impact before editing any symbol:

```text
impact(target="classify_tier", file_path="skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/classify.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
impact(target="run", file_path="skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
impact(target="gitnexus_evidence", file_path="skills/e2e-dev-harness/scripts/e2e_harness/adapters/scanner/_legacy/cross_service_dependency_scan.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
impact(target="scan", file_path="skills/e2e-dev-harness/scripts/e2e_harness/adapters/scanner/_legacy/cross_service_dependency_scan.py", kind="Function", direction="upstream", repo="e2e-dev-workflow")
```

- [ ] If any result is HIGH or CRITICAL, stop and report direct callers, affected processes, and risk before editing.

---

### Task 1: Add a Pure Tier Recommendation Model

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/recommend.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/__init__.py`
- Test: `skills/e2e-dev-harness/tests/test_tier_recommend.py`

- [ ] **Step 1: Write failing tests for option shape and auto recommendation**

Create `skills/e2e-dev-harness/tests/test_tier_recommend.py`:

```python
from e2e_harness.adapters.tier import recommend


def test_plain_auto_recommends_standard_with_options():
    result = recommend.recommend_tier("rename a helper function", scope=None, selected_tier="auto")

    assert result["recommended_tier"] == "standard"
    assert result["selected_tier"] == "standard"
    assert result["selection_source"] == "auto"
    assert [option["tier"] for option in result["options"]] == [
        "minimal",
        "standard",
        "critical",
        "audited",
    ]
    standard = next(option for option in result["options"] if option["tier"] == "standard")
    assert standard["recommended"] is True
    assert any("auto baseline floor" in reason for reason in standard["reasons"])


def test_explicit_lower_tier_records_downgrade_metadata():
    result = recommend.recommend_tier(
        "add refund settlement to the ledger",
        scope=None,
        selected_tier="standard",
    )

    assert result["recommended_tier"] == "critical"
    assert result["selected_tier"] == "standard"
    assert result["selection_source"] == "explicit"
    assert result["downgrade"]["requested_below_recommended"] is True
    assert result["downgrade"]["requires_provenance"] is True
    assert result["downgrade"]["blocked"] is False


def test_explicit_below_audited_records_downgrade_metadata():
    result = recommend.recommend_tier(
        "compliance audit of the incident response",
        scope=None,
        selected_tier="critical",
    )

    assert result["recommended_tier"] == "audited"
    assert result["selected_tier"] == "critical"
    assert result["downgrade"]["requested_below_recommended"] is True
    assert result["downgrade"]["requires_provenance"] is True
    assert result["downgrade"]["blocked"] is False
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_tier_recommend.py -q
```

Expected: FAIL with `ImportError` or `AttributeError` because `recommend` does not exist.

- [ ] **Step 3: Implement the pure recommendation module**

Create `skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/recommend.py`:

```python
"""Tier option and recommendation builder.

This module is intentionally pure: it consumes already-collected evidence and
does not invoke scanners, GitNexus, or subprocesses.
"""
from __future__ import annotations

from . import classify

ORDER = ["minimal", "standard", "critical", "audited"]

_COSTS = {
    "minimal": ["clarification", "red", "implementation", "verification"],
    "standard": ["planning", "single review", "verification"],
    "critical": ["planning", "R1/R2/R3 review fan-out", "verification"],
    "audited": ["planning", "R1/R2/R3 review fan-out", "audit replay"],
}


def _rank(tier: str) -> int:
    return ORDER.index(tier)


def _max_tier(*tiers: str) -> str:
    return max(tiers, key=_rank)


def _gitnexus_floor(scope: dict | None) -> tuple[str, list[str]]:
    if not scope:
        return "minimal", []
    gitnexus = scope.get("gitnexus") or {}
    summary = gitnexus.get("impact_summary") or {}
    risk = str(summary.get("risk") or "").upper()
    if risk in {"HIGH", "CRITICAL"}:
        return "critical", [f"GitNexus impact risk: {risk}"]
    if risk == "MEDIUM":
        return "standard", ["GitNexus impact risk: MEDIUM"]
    if (scope.get("dependencies") or []) and not gitnexus.get("verified", False):
        return "critical", [
            "cross-service dependencies found but GitNexus impact evidence is not verified"
        ]
    return "minimal", []


def _option(tier: str, recommended: str, reasons: list[str]) -> dict:
    return {
        "tier": tier,
        "recommended": tier == recommended,
        "reasons": reasons if tier == recommended else [],
        "costs": list(_COSTS[tier]),
    }


def recommend_tier(request_text: str, scope: dict | None = None, selected_tier: str = "auto") -> dict:
    auto = selected_tier == "auto"
    classified_tier, classify_reasons = classify.classify_tier(
        request_text,
        scope,
        auto=auto,
    )
    gitnexus_tier, gitnexus_reasons = _gitnexus_floor(scope)
    recommended = _max_tier(classified_tier, gitnexus_tier)
    reasons = classify_reasons + gitnexus_reasons

    requested = recommended if auto else selected_tier
    requested_below = _rank(requested) < _rank(recommended)
    blocked = False
    selected = requested

    return {
        "schema": "e2e-dev-harness.tier-recommendation.v1",
        "recommended_tier": recommended,
        "selected_tier": selected,
        "selection_source": "auto" if auto else "explicit",
        "reasons": reasons,
        "options": [_option(tier, recommended, reasons) for tier in ORDER],
        "downgrade": {
            "requested_below_recommended": requested_below,
            "requires_provenance": requested_below,
            "blocked": blocked,
        },
    }
```

- [ ] **Step 4: Export the module through the tier package**

Modify `skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/__init__.py`:

```python
from . import classify, recommend

__all__ = ["classify", "recommend"]
```

- [ ] **Step 5: Run the focused tests and verify they pass**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_tier_recommend.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit this task**

Run:

```powershell
git add skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/recommend.py skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/__init__.py skills/e2e-dev-harness/tests/test_tier_recommend.py
git commit -m "feat(e2e-harness): add tier recommendation model"
```

---

### Task 2: Wire Recommendations Into `start` Output Without Breaking Existing Consumers

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Test: `skills/e2e-dev-harness/tests/test_cli_e2e.py`

- [ ] **Step 1: Write a failing CLI test for `tier_recommendation`**

Add this test to `skills/e2e-dev-harness/tests/test_cli_e2e.py`:

```python
def test_start_auto_returns_tier_recommendation(tmp_path):
    result = run_cli(
        "start",
        "--repo",
        str(tmp_path),
        "--feature",
        "tier-options",
        "--request",
        "rename a helper function",
        cwd=tmp_path,
    )

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["tier"] == "standard"
    assert data["tier_recommendation"]["recommended_tier"] == "standard"
    assert data["tier_recommendation"]["selected_tier"] == "standard"
    assert len(data["tier_recommendation"]["options"]) == 4
    assert data["tier_reasons"] == data["tier_recommendation"]["reasons"]
```

- [ ] **Step 2: Write a failing CLI test for explicit downgrade metadata**

Add this test to the same file:

```python
def test_start_explicit_tier_records_downgrade_metadata(tmp_path):
    result = run_cli(
        "start",
        "--repo",
        str(tmp_path),
        "--feature",
        "explicit-downgrade",
        "--request",
        "add refund settlement to the ledger",
        "--tier",
        "standard",
        cwd=tmp_path,
    )

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["tier"] == "standard"
    assert data["tier_recommendation"]["recommended_tier"] == "critical"
    assert data["tier_recommendation"]["selection_source"] == "explicit"
    assert data["tier_recommendation"]["downgrade"]["requires_provenance"] is True
```

- [ ] **Step 3: Run the focused CLI tests and verify they fail**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_cli_e2e.py::test_start_auto_returns_tier_recommendation skills/e2e-dev-harness/tests/test_cli_e2e.py::test_start_explicit_tier_records_downgrade_metadata -q
```

Expected: FAIL because `tier_recommendation` is not returned.

- [ ] **Step 4: Replace start's direct classifier call with the recommendation layer**

Modify the tier selection block in `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`:

```python
    from e2e_harness.adapters.tier import recommend

    requested_tier = args.tier
    scope = adapter.scan(repo, request) if getattr(args, "scan", False) else None
    tier_recommendation = recommend.recommend_tier(
        request,
        scope,
        selected_tier=requested_tier,
    )
    tier = tier_recommendation["selected_tier"]
    reasons = tier_recommendation["reasons"]
```

Keep the existing `pipeline_ref`, `pipeline.load_spec`, and `run_state.new_run_state` flow unchanged.

- [ ] **Step 5: Add the recommendation to the command result**

Modify the return object in `start.py`:

```python
    return 0, {"schema": "e2e-dev-harness.start.v1", "run_id": run_id,
               "run_state": str(path), "current_phase": "CREATED",
               "tier": tier, "pipeline": pipeline_ref, "tier_reasons": reasons,
               "tier_recommendation": tier_recommendation,
               "domain": adapter.name}
```

- [ ] **Step 6: Run the focused CLI tests and verify they pass**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_cli_e2e.py::test_start_auto_returns_tier_recommendation skills/e2e-dev-harness/tests/test_cli_e2e.py::test_start_explicit_tier_records_downgrade_metadata -q
```

Expected: PASS.

- [ ] **Step 7: Commit this task**

Run:

```powershell
git add skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py skills/e2e-dev-harness/tests/test_cli_e2e.py
git commit -m "feat(e2e-harness): expose tier options at start"
```

---

### Task 3: Make GitNexus Impact Evidence a Structured Tier Input

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/scanner/_legacy/cross_service_dependency_scan.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/recommend.py`
- Test: `skills/e2e-dev-harness/tests/test_scanner.py`
- Test: `skills/e2e-dev-harness/tests/test_tier_recommend.py`

- [ ] **Step 1: Write a failing recommendation test for GitNexus HIGH/CRITICAL floors**

Add to `skills/e2e-dev-harness/tests/test_tier_recommend.py`:

```python
def test_gitnexus_high_risk_floors_to_critical():
    scope = {
        "schema": "e2e-dev-harness.scanner-scope.v1",
        "services": ["services/a"],
        "dependencies": [],
        "gitnexus": {
            "verified": True,
            "impact_summary": {"risk": "HIGH", "direct": 12, "processes_affected": 6},
        },
    }

    result = recommend.recommend_tier("rename a helper function", scope=scope, selected_tier="auto")

    assert result["recommended_tier"] == "critical"
    assert any("GitNexus impact risk: HIGH" in reason for reason in result["reasons"])
```

- [ ] **Step 2: Write a failing scanner test for structured impact summary extraction**

Add to `skills/e2e-dev-harness/tests/test_scanner.py`:

```python
def test_gitnexus_evidence_extracts_impact_summary(tmp_path):
    from e2e_harness.adapters.scanner._legacy import cross_service_dependency_scan as scan

    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        if "impact" in command:
            return {
                "exit_code": 0,
                "stdout": '{"risk":"HIGH","summary":{"direct":3,"processes_affected":2,"modules_affected":1}}',
                "stderr": "",
            }
        return {"exit_code": 0, "stdout": "{}", "stderr": ""}

    dependencies = [{
        "source_symbol": "com.example.Source.call",
        "target_symbol": "com.example.Target.handle",
        "source_service": "services/a",
        "target_service": "services/b",
    }]

    result, warnings = scan.gitnexus_evidence(
        tmp_path,
        dependencies,
        "strict",
        command_runner=fake_runner,
        gitnexus_available=True,
    )

    assert warnings == []
    assert result["verified"] is True
    assert result["impact_summary"]["risk"] == "HIGH"
    assert result["impact_summary"]["direct"] == 3
    assert result["impact_summary"]["processes_affected"] == 2
```

- [ ] **Step 3: Run the focused tests and verify they fail**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_tier_recommend.py::test_gitnexus_high_risk_floors_to_critical skills/e2e-dev-harness/tests/test_scanner.py::test_gitnexus_evidence_extracts_impact_summary -q
```

Expected: the recommendation test may pass after Task 1 if `impact_summary` support already exists; the scanner test should fail until extraction is added.

- [ ] **Step 4: Add impact summary extraction to scanner GitNexus evidence**

Modify `gitnexus_evidence` in `cross_service_dependency_scan.py`:

```python
def _impact_summary_from_evidence(evidence: list[dict]) -> dict:
    order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    summary = {"risk": None, "direct": 0, "processes_affected": 0, "modules_affected": 0}
    for item in evidence:
        stdout = item.get("stdout")
        if not isinstance(stdout, str) or "risk" not in stdout:
            continue
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            continue
        risk = str(data.get("risk") or "").upper()
        if risk in order and (summary["risk"] is None or order.index(risk) > order.index(summary["risk"])):
            summary["risk"] = risk
        raw_summary = data.get("summary") or {}
        summary["direct"] = max(summary["direct"], int(raw_summary.get("direct") or 0))
        summary["processes_affected"] = max(
            summary["processes_affected"],
            int(raw_summary.get("processes_affected") or 0),
        )
        summary["modules_affected"] = max(
            summary["modules_affected"],
            int(raw_summary.get("modules_affected") or 0),
        )
    return summary if summary["risk"] else {}
```

Add this key before assigning `result["evidence"]`:

```python
    result["impact_summary"] = _impact_summary_from_evidence(evidence)
```

- [ ] **Step 5: Run the focused tests and verify they pass**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_tier_recommend.py::test_gitnexus_high_risk_floors_to_critical skills/e2e-dev-harness/tests/test_scanner.py::test_gitnexus_evidence_extracts_impact_summary -q
```

Expected: PASS.

- [ ] **Step 6: Commit this task**

Run:

```powershell
git add skills/e2e-dev-harness/scripts/e2e_harness/adapters/scanner/_legacy/cross_service_dependency_scan.py skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/recommend.py skills/e2e-dev-harness/tests/test_scanner.py skills/e2e-dev-harness/tests/test_tier_recommend.py
git commit -m "feat(e2e-harness): use GitNexus impact in tier recommendation"
```

---

### Task 4: Persist Tier Decision Metadata In Run State

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Test: `skills/e2e-dev-harness/tests/test_cli_e2e.py`

- [ ] **Step 1: Write a failing test that run-state stores recommendation metadata**

Add to `skills/e2e-dev-harness/tests/test_cli_e2e.py`:

```python
def test_start_persists_tier_recommendation(tmp_path):
    result = run_cli(
        "start",
        "--repo",
        str(tmp_path),
        "--feature",
        "persist-tier-options",
        "--request",
        "add refund settlement to the ledger",
        cwd=tmp_path,
    )

    assert result.returncode == 0
    data = json.loads(result.stdout)
    state = json.loads(Path(data["run_state"]).read_text(encoding="utf-8"))
    assert state["tier"] == "critical"
    assert state["tier_recommendation"]["recommended_tier"] == "critical"
    assert state["tier_recommendation"]["selected_tier"] == "critical"
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_cli_e2e.py::test_start_persists_tier_recommendation -q
```

Expected: FAIL because run-state does not contain `tier_recommendation`.

- [ ] **Step 3: Persist the recommendation after creating the run-state**

Modify `start.py` immediately after `run_state.new_run_state(...)`:

```python
    st["tier_recommendation"] = tier_recommendation
```

This keeps `run_state.new_run_state` compatible and avoids changing core state construction for a CLI-only metadata field.

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_cli_e2e.py::test_start_persists_tier_recommendation -q
```

Expected: PASS.

- [ ] **Step 5: Commit this task**

Run:

```powershell
git add skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py skills/e2e-dev-harness/tests/test_cli_e2e.py
git commit -m "feat(e2e-harness): persist tier recommendation"
```

---

### Task 5: Document The Decision Contract

**Files:**
- Modify: `skills/e2e-dev-harness/SKILL.md`
- Test: `skills/e2e-dev-harness/tests/test_skill_md.py`

- [ ] **Step 1: Write a failing documentation test**

Add to `skills/e2e-dev-harness/tests/test_skill_md.py`:

```python
def test_skill_md_documents_tier_options_and_gitnexus_evidence():
    text = SKILL_MD.read_text(encoding="utf-8")

    assert "tier_recommendation" in text
    assert "recommended_tier" in text
    assert "selected_tier" in text
    assert "GitNexus impact" in text
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_skill_md.py::test_skill_md_documents_tier_options_and_gitnexus_evidence -q
```

Expected: FAIL because the skill docs do not describe the new contract.

- [ ] **Step 3: Add a short user-facing contract section**

Add this text near the existing tier documentation in `skills/e2e-dev-harness/SKILL.md`:

```markdown
### Tier recommendation contract

`start --tier auto` emits `tier_recommendation` with:

- `options`: minimal, standard, critical, and audited choices with cost/reason summaries.
- `recommended_tier`: the highest floor justified by request text, scanner scope, and GitNexus impact evidence.
- `selected_tier`: the tier actually used for the run.
- `downgrade`: metadata showing whether an explicit selection is below the recommendation. Under the current contract, explicit selections are preserved with `requires_provenance=true` and `blocked=false`.

GitNexus impact evidence raises the recommendation when structured impact risk is MEDIUM, HIGH, or CRITICAL. Missing GitNexus verification on cross-service dependencies is treated conservatively and must remain visible in `tier_recommendation.reasons`.
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_skill_md.py::test_skill_md_documents_tier_options_and_gitnexus_evidence -q
```

Expected: PASS.

- [ ] **Step 5: Commit this task**

Run:

```powershell
git add skills/e2e-dev-harness/SKILL.md skills/e2e-dev-harness/tests/test_skill_md.py
git commit -m "docs(e2e-harness): document tier recommendation contract"
```

---

## Verification

- [ ] Run the new focused tests:

```powershell
python -m pytest skills/e2e-dev-harness/tests/test_tier_recommend.py skills/e2e-dev-harness/tests/test_tier_classify.py -q
python -m pytest skills/e2e-dev-harness/tests/test_cli_e2e.py -q
python -m pytest skills/e2e-dev-harness/tests/test_scanner.py -q
python -m pytest skills/e2e-dev-harness/tests/test_skill_md.py -q
```

- [ ] Run the broader Python suite with repo-local temp paths if Windows temp permissions are noisy:

```powershell
$env:TMP = "$PWD\.test-tmp"
$env:TEMP = "$PWD\.test-tmp"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
python -m pytest skills/e2e-dev-harness/tests --basetemp .pytest-basetemp -q
```

- [ ] Run GitNexus change detection before commit or PR:

```text
detect_changes(scope="all", repo="e2e-dev-workflow")
```

- [ ] If GitNexus reports stale index state, run:

```powershell
npx gitnexus analyze
```

Then rerun `detect_changes`.

## Rollout Notes

- Keep `classify_tier` backward compatible so existing direct tests still pass.
- Keep `--tier minimal` as an explicit opt-down, but record downgrade metadata when it is below the recommendation.
- Do not make `start` invoke GitNexus directly in this slice; use scanner-provided evidence only.
- Treat GitNexus HIGH or CRITICAL as a recommendation floor of `critical`, not `audited`; reserve `audited` for audit/compliance language unless a later policy explicitly changes that.
- If compact output projection exists in the active branch, expose only stable summary keys there and keep the full `tier_recommendation` in run-state.

## Self-Review

- Spec coverage: the plan covers user-visible options, recommendation, explicit selection, GitNexus impact evidence, persistence, docs, and verification.
- Placeholder scan: no deferred implementation placeholders are present.
- Type consistency: `tier_recommendation`, `recommended_tier`, `selected_tier`, `selection_source`, `options`, and `downgrade` are used consistently across tests and implementation snippets.
