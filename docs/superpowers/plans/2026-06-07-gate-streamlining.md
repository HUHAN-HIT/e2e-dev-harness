# Gate Streamlining Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real lightweight `minimal` tier and make every gate scale with risk, so the harness spends effort on correct, tested implementation rather than re-polishing edge artifacts.

**Architecture:** Four phases mirror the approved spec (`docs/superpowers/specs/2026-06-07-gate-streamlining-design.md`). P1 tightens the classifier and adds the `minimal` floor in `task_tier.py` (self-contained). P2 threads `tier` into the clarification gate and inlines mechanical format-repairs. P3 makes ledger artifacts non-blocking + background hook generation. P4 lets `minimal` runs go single-worker-one-pass. A **golden regression suite** (`tests/test_task_tier_golden.py`) is the anti-regression contract every phase must keep green.

**Tech Stack:** Python 3, `unittest`, repo test harness under `tests/` (bootstrapped onto `skills/e2e-dev-harness/scripts`), GitNexus for impact analysis.

---

## ⚠️ Safety posture change (requires explicit go-ahead before P1 Task 4)

Spec §3.2 changes explicit-downgrade policy: **only `audited` blocks downgrade**; all other tiers may be downgraded by the user (with a new `downgrade_requires_provenance: true` flag). This **intentionally changes** the existing safety test `test_workflow_tier_explicit_basic_cannot_downgrade_critical_auto_minimum` (a payment/cross-service task explicitly requested as `basic` will now resolve to `basic`, not be force-upgraded to `critical`).

The **auto-classification safety net is preserved**: `classify_auto` still returns `critical` for double-hit (payment / cross-service / dependency) tasks, so `auto_recommended.tier` still surfaces `critical`. Only the *explicit user override* is honored. Confirm this is intended before executing P1 Task 4.

---

## Impact analysis (run before edits — CLAUDE.md mandate)

Already captured this session:
- `task_tier.classify_auto` — **HIGH** (8 upstream; feeds `evaluate`).
- `task_tier.evaluate` — **HIGH** (17 upstream: `workflow_tier_status`, `review_policy_for_start`, `evaluate_workflow_tier`, gate/start commands).
- `required_todo_list_for_lifecycle` — exists in 3 modules; **P4 edits `lifecycle_policy.py:87` only** (`coordinator_flow.py:183` and `phase_guard.py:395` delegate to it).

Re-run `gitnexus_impact` on `clarification_gate.validate`, `clarification_flow.run`, `dispatcher.coordinator_worker_only_action`, `preflight.clarification_dispatch_blockers` at the start of P2/P3/P4 respectively.

---

## File structure map

| File | Phase | Responsibility / change |
|---|---|---|
| `tests/test_task_tier_golden.py` | P1 | **New** golden regression contract (D4). The anti-放水 net. |
| `skills/e2e-dev-harness/scripts/task_tier.py` | P1 | Add `minimal` tier, `MINIMAL_GATES`, weak-signal demotion, minimal floor in `classify_auto`, downgrade policy + `downgrade_requires_provenance`. |
| `tests/test_e2e_dev_harness_scripts.py`, `tests/test_orchestration.py` | P1 | Update the one downgrade test to the new policy; add minimal-tier assertions. |
| `skills/e2e-dev-harness/scripts/clarification_gate.py` | P2 | `validate(..., tier="standard")`; low-tier skips evidence gaps + collapses readiness. |
| `skills/e2e-dev-harness/scripts/e2e_harness/engine/clarification_flow.py` | P2 | Read tier from run-state, pass to `validate`; inline pure-format repairs (no dispatch-beat). |
| `skills/e2e-dev-harness/scripts/dispatcher.py` | P2 | `coordinator_worker_only_action` format-class exemption branch. |
| `skills/e2e-dev-harness/scripts/run_state.py` | P2 | Persist + read `workflow_tier` on state. |
| `skills/e2e-dev-harness/scripts/harness_verify.py` (+ coverage/registry points) | P3 | Ledger artifacts: missing → `warn`, not blocking. |
| `skills/e2e-dev-harness/hooks/` (new hook) | P3 | Background Stop hook generates ledger artifacts. |
| `skills/e2e-dev-harness/scripts/lifecycle_policy.py` | P4 | `required_todo_list_for_lifecycle(lifecycle, state, tier)`: minimal → single-worker-one-pass. |
| `skills/e2e-dev-harness/scripts/preflight.py` | P4 | `clarification_dispatch_blockers` exemption for minimal. |

---

# PHASE P1 — `minimal` tier + tightened classifier + golden net (Spec S1 + S2)

**Exit:** existing tier tests green + golden suite green + `gitnexus_detect_changes` shows only `task_tier.py` (+ test files) affected.

### Task 1: Golden regression suite (write first — RED)

**Files:**
- Create: `tests/test_task_tier_golden.py`

- [ ] **Step 1: Write the golden suite**

```python
"""Golden anti-regression contract for task tier classification (Spec D4)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import task_tier  # noqa: E402


class TaskTierGoldenTests(unittest.TestCase):
    def _auto(self, text, facts=None, deps=None):
        return task_tier.evaluate("auto", text, facts or {}, deps or {})

    def test_payment_cross_service_is_critical(self):
        result = self._auto(
            "Rework the payment refund callback settlement across services.",
            {"service_candidates": ["services/pay", "services/ledger"], "multi_service": True},
            {"dependencies": [{"kind": "http"}]},
        )
        self.assertEqual("critical", result["tier"])
        self.assertIn("contracts", result["required_gates"])
        self.assertIn("strict-guard", result["required_gates"])

    def test_mq_multi_service_is_critical(self):
        result = self._auto(
            "Publish a RocketMQ notification with topic and payload.",
            {"service_candidates": ["services/a", "services/b"], "multi_service": True},
            {"dependencies": [{"kind": "rocketmq"}]},
        )
        self.assertEqual("critical", result["tier"])

    def test_single_table_repository_change_is_minimal(self):
        result = self._auto(
            "Adjust one repository query in order-service for a single table read.",
            {"service_candidates": ["services/order"], "multi_service": False},
            {"dependencies": []},
        )
        self.assertEqual("minimal", result["tier"])
        self.assertEqual(
            ["clarification", "test-evidence", "task-alignment", "run-state"],
            result["required_gates"],
        )

    def test_util_function_change_is_minimal(self):
        result = self._auto(
            "Fix an off-by-one in a small utility helper function.",
            {"service_candidates": ["services/order"], "multi_service": False},
            {"dependencies": []},
        )
        self.assertEqual("minimal", result["tier"])

    def test_single_service_rest_endpoint_locked_standard(self):
        # Locked per spec table: single-service API surface stays `standard`.
        result = self._auto(
            "Add one REST API endpoint in order-service for an admin lookup screen.",
            {"service_candidates": ["services/order"], "multi_service": False},
            {"dependencies": []},
        )
        self.assertEqual("standard", result["tier"])

    def test_compliance_audit_task_is_audited(self):
        result = self._auto(
            "Run a compliance audit of the regulatory incident handling path.",
            {"service_candidates": ["services/order"], "multi_service": False},
            {"dependencies": []},
        )
        self.assertEqual("audited", result["tier"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `python -m pytest tests/test_task_tier_golden.py -v`
Expected: FAIL — `minimal` cases currently classify as `standard`/`basic`, and `gates_for("minimal")` returns `BASE_GATES`.

- [ ] **Step 3: Commit the red contract**

```bash
git add tests/test_task_tier_golden.py
git commit -m "test(tier): add golden regression suite for tier classification (red)"
```

### Task 2: Add `minimal` tier + gate set

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/task_tier.py:12-14` (TIERS/ENFORCED_TIERS), add `MINIMAL_GATES`, `gates_for`.

- [ ] **Step 1: Add tier + gate constants** — replace lines 12-14:

```python
TIERS = ("auto", "minimal", "basic", "standard", "critical", "audited")
ENFORCED_TIERS = ("minimal", "basic", "standard", "critical", "audited")
TIER_RANK = {tier: index for index, tier in enumerate(ENFORCED_TIERS)}
MINIMAL_GATES = [
    "clarification",
    "test-evidence",
    "task-alignment",
    "run-state",
]
```

- [ ] **Step 2: Teach `gates_for` the minimal branch**

```python
def gates_for(tier: str) -> list[str]:
    if tier == "audited":
        return AUDITED_GATES
    if tier == "critical":
        return CRITICAL_GATES
    if tier == "standard":
        return STANDARD_GATES
    if tier == "minimal":
        return MINIMAL_GATES
    return BASE_GATES
```

- [ ] **Step 3: Smoke check**

Run: `python -c "import sys; sys.path.insert(0,'skills/e2e-dev-harness/scripts'); import task_tier; print(task_tier.gates_for('minimal'))"`
Expected: `['clarification', 'test-evidence', 'task-alignment', 'run-state']`

### Task 3: Weak-signal demotion + `minimal` floor in `classify_auto`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/task_tier.py` keyword sets + `classify_auto` + `automatic_minimum`.

- [ ] **Step 1: Demote weak signals out of strong sets**

Remove `"repository"`, `"mapper"` from `DATA_KEYWORDS`; remove `"tag"`, `"group"` from `MESSAGING_KEYWORDS`; remove `"schema"` from `CONTRACT_KEYWORDS`. After `WEAK_CONTRACT_KEYWORDS` add:

```python
WEAK_SIGNAL_KEYWORDS = {
    "repository",
    "mapper",
    "tag",
    "group",
    "schema",
}
```

- [ ] **Step 2: Rework `classify_auto` fallback to a `minimal` floor** — replace lines ~173-181 (`risk_reasons.extend(... DATA_KEYWORDS ...)` through the final `return "basic", [...]`) with:

```python
    risk_reasons.extend(keyword_reasons(design_text, DATA_KEYWORDS, "data"))
    risk_reasons.extend(keyword_reasons(design_text, MESSAGING_KEYWORDS, "messaging"))
    weak_signal_reasons = keyword_reasons(design_text, WEAK_SIGNAL_KEYWORDS, "weak-signal")
    if weak_signal_reasons and (multi_service or kinds):
        risk_reasons.extend(weak_signal_reasons)
    if kinds or reasons or risk_reasons:
        return "critical", reasons + risk_reasons
    if weak_contract_reasons:
        return "standard", ["single-service API surface detected"] + weak_contract_reasons
    return "minimal", ["no risk keyword, dependency, or multi-service evidence detected"]
```

- [ ] **Step 3: Simplify `automatic_minimum`** (the standard→basic shim keyed on `"design-backed requirement detected"` is now dead):

```python
def automatic_minimum(tier: str, reasons: list[str]) -> tuple[str, list[str]]:
    return tier, reasons
```

- [ ] **Step 4: Run golden + smoke**

Run: `python -m pytest tests/test_task_tier_golden.py -v`
Expected: minimal + critical + standard + audited PASS (downgrade test handled in Task 4).

### Task 4: Downgrade policy + `downgrade_requires_provenance` (⚠️ see safety callout)

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/task_tier.py:evaluate` (lines ~184-224).

- [ ] **Step 1: Replace downgrade computation in `evaluate`** — replace the `else` branch (lines ~195-201):

```python
    if requested == "auto":
        tier = auto_tier
        reasons = auto_reasons
        downgrade_blocked = False
        downgrade_requires_provenance = False
    else:
        below_minimum = TIER_RANK[requested] < TIER_RANK[minimum_tier]
        downgrade_blocked = below_minimum and minimum_tier == "audited"
        downgrade_requires_provenance = below_minimum and not downgrade_blocked
        tier = minimum_tier if downgrade_blocked else requested
        reasons = [f"workflow tier explicitly set to {requested}"]
        if downgrade_blocked:
            reasons.append(f"requested tier below audited safety minimum; using {tier}")
            reasons.extend(minimum_reasons)
        elif downgrade_requires_provenance:
            reasons.append(
                f"requested tier below automatic recommendation {minimum_tier}; "
                "record confirmed-by: user @<date/session/artifact> provenance"
            )
```

Add to the returned dict after `"downgrade_blocked": downgrade_blocked,`:

```python
        "downgrade_requires_provenance": downgrade_requires_provenance,
```

- [ ] **Step 2: Update the existing downgrade test** — in `tests/test_e2e_dev_harness_scripts.py` (~9961) and `tests/test_orchestration.py` if duplicated, replace `test_workflow_tier_explicit_basic_cannot_downgrade_critical_auto_minimum` with:

```python
    def test_workflow_tier_explicit_basic_downgrade_from_critical_allowed_with_provenance(self) -> None:
        design_text = "Publish a DMQ refund callback with topic, tag, group, and payload contract."
        facts = {"service_candidates": ["services/refund-service", "services/ledger-service"], "multi_service": True}
        dependency_report = {"dependencies": [{"kind": "dmq"}], "unresolved_questions": []}

        result = task_tier.evaluate("basic", design_text, facts, dependency_report)

        self.assertEqual("basic", result["user_requested"])
        self.assertEqual("critical", result["auto_recommended"]["tier"])  # safety net still visible
        self.assertEqual("basic", result["effective"]["tier"])            # explicit override honored
        self.assertEqual("basic", result["tier"])
        self.assertFalse(result["downgrade_blocked"])
        self.assertTrue(result["downgrade_requires_provenance"])
```

- [ ] **Step 3: Add audited-still-blocks coverage to the golden suite** — append to `tests/test_task_tier_golden.py`:

```python
    def test_audited_downgrade_still_blocked(self):
        result = task_tier.evaluate(
            "basic",
            "Run a compliance audit of the regulatory incident path.",
            {"service_candidates": ["services/order"]},
            {"dependencies": []},
        )
        self.assertEqual("audited", result["tier"])
        self.assertTrue(result["downgrade_blocked"])
```

### Task 5: Full regression + detect_changes + commit

- [ ] **Step 1:** `python -m pytest tests/test_task_tier_golden.py tests/test_e2e_dev_harness_scripts.py tests/test_orchestration.py -q` — all PASS. Confirm `test_workflow_tier_basic_still_keeps_harness_record` still PASS (`evaluate("basic",...)` stays `basic`: minimal < basic, no block).
- [ ] **Step 2:** GitNexus `detect_changes` (unstaged). Expected: only `task_tier.*` + test modules. Report anything unexpected.
- [ ] **Step 3: Commit**

```bash
git add skills/e2e-dev-harness/scripts/task_tier.py tests/test_task_tier_golden.py tests/test_e2e_dev_harness_scripts.py tests/test_orchestration.py
git commit -m "feat(tier): add minimal floor tier, demote weak signals, scale downgrade policy"
```

---

# PHASE P2 — clarification gate honors tier + inline format repairs (Spec S3)

**Exit:** low-tier (`minimal`/`basic`) clarification skips impact/change-logic/integration evidence gaps; pure-format repairs no longer force dispatch-beat; regression green.

### Task 6: Persist + read `workflow_tier` on run-state

**Files:** Modify `skills/e2e-dev-harness/scripts/run_state.py`; Test `tests/test_orchestration.py`.

- [ ] **Step 1: Failing test**

```python
    def test_run_state_workflow_tier_round_trip(self) -> None:
        state = run_state.build_state("docs/agent-runs/run", "single", [], "docs/agent-runs/run/artifact-registry.json")
        self.assertEqual("standard", run_state.workflow_tier(state))  # default
        run_state.set_workflow_tier(state, "minimal")
        self.assertEqual("minimal", run_state.workflow_tier(state))
```

- [ ] **Step 2: Run — FAIL** (`module 'run_state' has no attribute 'workflow_tier'`).
- [ ] **Step 3: Implement in `run_state.py`**

```python
def workflow_tier(state: dict | None) -> str:
    if not isinstance(state, dict):
        return "standard"
    tier = str(state.get("workflow_tier", "")).strip()
    return tier or "standard"


def set_workflow_tier(state: dict, tier: str) -> dict:
    state["workflow_tier"] = str(tier or "standard").strip() or "standard"
    return state
```

- [ ] **Step 4: Run — PASS. Commit.**

```bash
git add skills/e2e-dev-harness/scripts/run_state.py tests/test_orchestration.py
git commit -m "feat(run-state): persist and read workflow_tier"
```

### Task 7: `clarification_gate.validate` accepts `tier` and scales evidence

**Files:** Modify `skills/e2e-dev-harness/scripts/clarification_gate.py:758` (`validate`); Test `tests/test_e2e_dev_harness_scripts.py`.

- [ ] **Step 1: Failing test**

```python
    def test_clarification_validate_low_tier_skips_evidence_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "design.md"
            doc.write_text(
                "# Feature\n\n## Restated Intent\nDo X. confirmed-by: user @2026-06-07\n\n"
                "## Open Questions\nNone.\n\n## Goal\nX\n\n## Scope\norder-service\n\n"
                "## Use Cases\n- U1\n\n## Acceptance Criteria\n- AC1\n\n## Test Design\n- T1\n\n"
                "## Integration Touchpoints\nAdd a payment refund API across services.\n",
                encoding="utf-8",
            )
            high = clarification_gate.validate(doc, require_intent=True, require_user_confirmation=True, tier="critical")
            low = clarification_gate.validate(doc, require_intent=True, require_user_confirmation=True, tier="minimal")
        self.assertTrue(high.get("impact_gaps") or high.get("change_logic_gaps") or high.get("integration_gaps"))
        self.assertEqual([], low["impact_gaps"])
        self.assertEqual([], low["change_logic_gaps"])
        self.assertEqual([], low["integration_gaps"])
        self.assertTrue(low["implementation_evidence_ready"])
```

- [ ] **Step 2: Run — FAIL** (`unexpected keyword argument 'tier'`).
- [ ] **Step 3: Add `tier` param + short-circuit.** Add module constant near top: `LOW_EVIDENCE_TIERS = {"minimal", "basic"}`. Change signature (line 758) to `def validate(path: Path, require_intent: bool = False, require_user_confirmation: bool = False, tier: str = "standard") -> dict:`. After `logic_gaps = change_logic_gaps(markdown)` (line 776) add:

```python
    if str(tier).strip().lower() in LOW_EVIDENCE_TIERS:
        gaps = []
        impact_gaps = []
        logic_gaps = []
```

Add `"tier": str(tier).strip().lower() or "standard",` to the `result` dict.

- [ ] **Step 4: Run — PASS. Commit.**

### Task 8: Thread tier from `clarification_flow.run` into `validate`

**Files:** Modify `skills/e2e-dev-harness/scripts/e2e_harness/engine/clarification_flow.py:320` (`run`) + call at `:344`; Test `tests/test_orchestration.py`.

- [ ] **Step 1: Failing test** — CREATED run-state with `workflow_tier="minimal"`, design doc missing Impact Summary; assert `run(...)` result has empty `impact_gaps`. (Mirror existing clarification_flow fixtures in the test file.)
- [ ] **Step 2: Read tier + pass through.** In `run`, after resolving `design_path`, add:

```python
    tier = "standard"
    if run_state:
        _state_path = _resolve_repo_path(repo, run_state)
        if _state_path and _state_path.exists():
            tier = run_state_module.workflow_tier(read_json_object(_state_path))
```

Change the `validate` call (line 344) to pass `tier=tier`.

- [ ] **Step 3: Run — PASS. Commit.**

### Task 9: Inline pure-format mechanical repairs (no dispatch-beat)

**Files:** Modify `clarification_gate.py:mechanical_remediation_tasks`, `clarification_flow.py:_ensure_mechanical_repair_tasks`, `dispatcher.py:coordinator_worker_only_action`; Test `tests/test_e2e_dev_harness_scripts.py`.

- [ ] **Step 1: Failing test**

```python
    def test_format_repairs_are_inline_allowed(self) -> None:
        path = Path("docs/design/x.md")
        too_long = clarification_gate.mechanical_remediation_tasks(path, {"impact_gaps": ["Impact Summary must stay bounded"]})
        incomplete = clarification_gate.mechanical_remediation_tasks(path, {"impact_gaps": ["affected interfaces table missing columns"]})
        self.assertTrue(all(t["inline_allowed"] for t in too_long))
        self.assertEqual({"format"}, {t["repair_class"] for t in too_long})
        self.assertFalse(any(t["inline_allowed"] for t in incomplete))
```

- [ ] **Step 2: Tag tasks.** In `mechanical_remediation_tasks`, add `"repair_class": "format", "inline_allowed": True,` to the `impact_summary_too_long` and `impact_summary_table_too_large` dicts; add `"repair_class": "judgment", "inline_allowed": False,` to the `impact_summary_table_incomplete` dict.
- [ ] **Step 3: Split inline vs dispatched in `_ensure_mechanical_repair_tasks`**

```python
def _ensure_mechanical_repair_tasks(repo: Path, run_state: Path | None, design_path: Path, result: dict) -> dict:
    all_specs = [item for item in result.get("mechanical_remediation_tasks", []) or [] if isinstance(item, dict)]
    inline_specs = [s for s in all_specs if s.get("inline_allowed")]
    dispatch_specs = [s for s in all_specs if not s.get("inline_allowed")]
    dispatch = _ensure_artifact_repair_tasks(repo, run_state, design_path, dispatch_specs)
    if inline_specs:
        dispatch = dict(dispatch)
        dispatch["inline_tasks"] = [
            {"code": s.get("code"), "section": s.get("section"), "target": str(design_path), "objective": s.get("objective")}
            for s in inline_specs
        ]
    return dispatch
```

- [ ] **Step 4: Format exemption in `coordinator_worker_only_action`.** Add optional param `repair_class: str | None = None`; when `repair_class == "format"`, return an action dict with `code_writes_allowed: True`, `required_action: "inline_edit"`, `next_required.phase: "inline_edit"`. Default `None` preserves all current call sites (`:1022`, `:1744`, `clarification_flow.py:236`, `dispatch_engine.py:133`).
- [ ] **Step 5: Run gate + clarification regressions — PASS. Commit.**

### Task 10: P2 exit

- [ ] `python -m pytest tests/ -q -k "clarification or tier or dispatch or orchestration"` — all PASS.
- [ ] `detect_changes`: only clarification/tier/dispatch/run_state symbols. Golden suite green.

---

# PHASE P3 — ledger artifacts non-blocking + background hook (Spec S4)

**Exit:** missing coverage-matrix / artifact-registry / run-summary → `warn` not block; a Stop hook regenerates them; high-tier (`audited`) audit evidence preserved; regression green.

### Task 11: Recon (read-only — confirm exact blocking lines)

- [ ] Read `skills/e2e-dev-harness/scripts/harness_verify.py` `validate` + `write_summary_outputs`; grep `coverage-matrix`, `artifact-registry`, `run-summary` for the branches that append to `blocked_reasons` / return non-zero for a *missing* artifact. Record exact file:line for each. Re-run `gitnexus_impact` on `harness_verify.validate`.

### Task 12: Make ledger artifacts warn, not block

**Files:** Modify the blocking branches found in Task 11; Test `tests/test_e2e_dev_harness_scripts.py`.

- [ ] **Step 1: Failing test** — a `VERIFIED` run-state with coverage-matrix/run-summary artifacts absent yields `ready=True` with those reasons under a new `warnings` key (not `blocked_reasons`) for `tier != "audited"`; for `audited` they stay in `blocked_reasons`.
- [ ] **Step 2: Implement** — thread `tier` (via `run_state.workflow_tier`) into `harness_verify.validate`; when `tier != "audited"`, route ledger-missing reasons into `result["warnings"]` instead of `blocked_reasons`.
- [ ] **Step 3: Run — PASS. Commit.**

### Task 13: Background ledger-generation hook

**Files:** Create `skills/e2e-dev-harness/hooks/generate_ledger.py` + register in `install_hooks.py`; Test `tests/test_e2e_dev_harness_scripts.py`.

- [ ] **Step 1: Failing test** — invoking the hook entrypoint on a run dir generates missing `artifact-registry.json` / `run-summary.json` / coverage-matrix; a forced write error produces `evidence/ledger-hook-degradation.json` and returns 0 (never raises).
- [ ] **Step 2: Implement** reusing `artifact_registry.build_registry` / `harness_verify.write_summary_outputs`; wrap in try/except writing degradation evidence; always exit 0.
- [ ] **Step 3: Register** in `install_hooks.py` Stop hooks. Run hook + install tests — PASS. Commit.

### Task 14: P3 exit — regression + golden + detect_changes.

---

# PHASE P4 — `minimal` single-worker-one-pass lifecycle (Spec S5, D1+D5)

**Exit:** `minimal` runs CREATED→VERIFIED with one serial worker, no per-state spawn/dispatch-ack ceremony, no independent review; basic+ unchanged; regression green.

### Task 15: `required_todo_list_for_lifecycle` accepts tier; minimal single-pass

**Files:** Modify `skills/e2e-dev-harness/scripts/lifecycle_policy.py:87` + `:180`; delegators `coordinator_flow.py:183`, `phase_guard.py:395`; Test `tests/test_orchestration.py`.

- [ ] **Step 1: Failing test**

```python
    def test_minimal_lifecycle_is_single_worker_one_pass(self) -> None:
        todo = lifecycle_policy.required_todo_list_for_lifecycle("CREATED", None, tier="minimal")
        self.assertTrue(any("single worker" in t.lower() or "one pass" in t.lower() for t in todo))
        self.assertNotIn("dispatch-ack", " ".join(todo).lower())
        self.assertFalse(any("r1" in t.lower() or "review worker" in t.lower() for t in todo))
        std = lifecycle_policy.required_todo_list_for_lifecycle("CREATED", None, tier="standard")
        self.assertEqual(std, lifecycle_policy.required_todo_list_for_lifecycle("CREATED", None))
```

- [ ] **Step 2: Add `tier` param + minimal branch**

```python
def required_todo_list_for_lifecycle(lifecycle: str, state: dict | None = None, tier: str = "standard") -> list[str]:
    if str(tier).strip().lower() == "minimal":
        return _minimal_todo_list_for_lifecycle(lifecycle)
    # existing body unchanged below
```

Add `_minimal_todo_list_for_lifecycle(lifecycle)` returning a single-worker-one-pass list: one serial worker performs clarify→plan→implement→test; coordinator runs only control-plane finish + the load-bearing 4 gates (`clarification`, `test-evidence`, `task-alignment`, `run-state`) at exit; no R1/R2/R3; no per-state dispatch-ack/complete cycle.

- [ ] **Step 3: Thread tier through delegators** — `todo_policy_for_lifecycle(lifecycle, state)` reads `run_state.workflow_tier(state)` and forwards it; update `coordinator_flow.required_todo_list_for_lifecycle` and `phase_guard.required_todo_list_for_lifecycle` to accept/forward `tier` (default preserves current behavior).
- [ ] **Step 4: Run — PASS. Commit.**

### Task 16: Exempt minimal from clarification dispatch blockers

**Files:** Modify `skills/e2e-dev-harness/scripts/preflight.py:85`; Test `tests/test_e2e_dev_harness_scripts.py`.

- [ ] **Step 1: Failing test** — CREATED run-state with `workflow_tier="minimal"` and no `agent-schedule.json` returns `[]`; `standard` still returns the missing-schedule blocker.
- [ ] **Step 2: Implement** — after reading `state_data`, if `run_state.workflow_tier(state_data) == "minimal"`, return `[]` before the schedule checks. (Import `run_state` in `preflight.py` if not already.)
- [ ] **Step 3: Run — PASS. Commit.**

### Task 17: P4 exit

- [ ] `python -m pytest tests/ -q` — all PASS. Golden green; `detect_changes` only expected symbols.
- [ ] Manual smoke: drive a `minimal` run CREATED→VERIFIED — single worker, 4 gates at exit, no review dispatch.

---

## Self-review notes

- **Spec coverage:** S1→Tasks 2-3; S2→Tasks 1,3,4 + golden; S3→Tasks 6-9; S4→Tasks 11-13; S5→Tasks 15-16. Non-goals (§9) respected: basic/standard/critical/audited gate sets untouched; no reviewer-consumed artifact deleted; no new config dimension; GitNexus/audited replay untouched.
- **Type consistency:** `workflow_tier(state)` / `set_workflow_tier` used identically in P2/P3/P4; `tier` default `"standard"` everywhere preserves current behavior when unset; `MINIMAL_GATES` order matches the golden assertion exactly.
- **Open confirmation:** P1 Task 4 safety-posture change — explicit go-ahead required before execution.
