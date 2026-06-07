# Agent Scheduling Strategy Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auditable scheduling strategy layer that decides when to keep single-service work serial, when to split complex single-service work into task-item lanes, when to parallelize multi-service workers, and how reviewer waves aggregate by service.

**Architecture:** Keep the harness as a deterministic control plane. Add a focused `scheduling_strategy.py` module that produces a read-only scheduling decision, thread that decision into orchestration schedule generation, then let `dispatcher.py` consume explicit wave metadata without owning high-level policy. Existing phase locks, worker ownership, context-pack budgets, dispatch ack/complete, and reviewer independence remain authoritative.

**Tech Stack:** Python stdlib, existing e2e-dev-harness scripts, `unittest`, GitNexus impact checks, existing JSON schedule contracts.

---

## Scope And Boundaries

This plan is intentionally staged. It does not start by allowing arbitrary concurrent code agents inside one service. The first behavior change is auditability: the harness explains the scheduling strategy in machine-readable JSON. Later tasks allow more parallelism only when the strategy can prove service or task-item boundaries.

Keep these constraints:

- `dispatcher.dispatch_beat` remains the mechanical executor: ready checks, context pack, claim, spawn request, dispatch event.
- `orchestration_plan.agent_schedule` remains the schedule factory.
- `agent_scheduler.py` remains the task claim, lease, completion, and role-conflict authority.
- `phase_guard.py` remains the write authorization authority.
- Single-service code parallelism is gated by explicit task-item lanes and non-overlapping edit scopes. If scopes are unknown, generate the lanes for audit/review, but keep code execution serial.
- Review workers may parallelize more aggressively than code workers, but every review still closes through `dispatch-complete` and `reviewer_gate.py`.

## Files

- Create: `skills/e2e-dev-harness/scripts/scheduling_strategy.py`
  - Owns deterministic scheduling decisions and lane metadata.
- Create: `tests/test_scheduling_strategy.py`
  - Pins strategy decisions without touching dispatcher runtime behavior.
- Modify: `skills/e2e-dev-harness/scripts/orchestration_plan.py`
  - Calls the strategy module and threads the result into `multi_agent_decision` and `agent_schedule`.
- Modify: `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`
  - Includes `scheduling_decision` in the `plan` result and generated schedule.
- Modify: `skills/e2e-dev-harness/scripts/dispatcher.py`
  - Later task only: uses schedule wave metadata when selecting ready tasks, while preserving current `distinct_parallel_group` default.
- Modify: `skills/e2e-dev-harness/references/agent-orchestration.md`
  - Documents scheduling strategy, single-service split rules, and reviewer aggregation.
- Test: `tests/test_orchestration.py`
- Test: `tests/test_e2e_dev_harness_scripts.py`
- Test: `tests/test_enterprise_harness_architecture.py`
- Test: `tests/test_skill_docs.py`

## Required GitNexus Safety

Before editing symbols, run impact analysis and record the risk in the implementation notes:

```powershell
# before modifying orchestration_plan.agent_schedule
# use GitNexus MCP:
# impact({ repo: "e2e-dev-workflow", target: "agent_schedule", direction: "upstream" })

# before modifying orchestration_plan.multi_agent_decision
# impact({ repo: "e2e-dev-workflow", target: "multi_agent_decision", direction: "upstream" })

# before modifying dispatcher.ready_tasks or dispatcher.dispatch_beat
# impact({ repo: "e2e-dev-workflow", target: "ready_tasks", direction: "upstream" })
# impact({ repo: "e2e-dev-workflow", target: "dispatch_beat", direction: "upstream" })
```

If any impact result is HIGH or CRITICAL, pause and report the blast radius before editing that symbol.

---

### Task 1: Add Read-Only Scheduling Strategy

**Files:**
- Create: `skills/e2e-dev-harness/scripts/scheduling_strategy.py`
- Create: `tests/test_scheduling_strategy.py`

- [ ] **Step 1: Write failing tests for the strategy decision**

Create `tests/test_scheduling_strategy.py`:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import scheduling_strategy  # noqa: E402


class SchedulingStrategyTests(unittest.TestCase):
    def test_low_risk_single_service_stays_single_worker(self) -> None:
        result = scheduling_strategy.decide(
            selected_mode="single",
            services=["services/order-service"],
            reasons=[],
            design_text="## Acceptance Criteria\n- AC-1: Return an order quote.\n",
        )

        self.assertEqual("e2e-dev-harness.scheduling-decision.v1", result["schema"])
        self.assertEqual("single-worker", result["execution_model"])
        self.assertEqual(1, result["max_workers"])
        self.assertEqual("single", result["task_split"]["strategy"])
        self.assertEqual("serial", result["parallelism"]["code"])
        self.assertEqual(["services/order-service"], result["review_strategy"]["service_reviewers"])

    def test_complex_single_service_creates_task_item_lanes_but_gates_code_parallelism(self) -> None:
        result = scheduling_strategy.decide(
            selected_mode="single-review",
            services=["services/order-service"],
            reasons=["large or design-heavy implementation context"],
            design_text=(
                "## Acceptance Criteria\n"
                "- AC-1: Validate quote inputs.\n"
                "- AC-2: Persist quote audit trail.\n"
                "- AC-3: Publish quote created event.\n"
            ),
        )

        self.assertEqual("split-single", result["execution_model"])
        self.assertEqual("acceptance-criteria", result["task_split"]["strategy"])
        self.assertEqual(["AC-1", "AC-2", "AC-3"], [lane["acceptance_id"] for lane in result["implementation_lanes"]])
        self.assertEqual("gated-by-edit-scope", result["parallelism"]["code"])
        self.assertIn("single service code lanes need non-overlapping edit scopes", result["blocked_parallelism"][0])

    def test_multi_service_parallelizes_by_service_and_keeps_global_review(self) -> None:
        result = scheduling_strategy.decide(
            selected_mode="multi",
            services=["services/order-service", "services/payment-service"],
            reasons=["multiple affected services/modules"],
            design_text="## Acceptance Criteria\n- AC-1: Order requests payment authorization.\n",
        )

        self.assertEqual("service-parallel", result["execution_model"])
        self.assertEqual(2, result["max_workers"])
        self.assertEqual("service", result["task_split"]["strategy"])
        self.assertEqual("service-parallel", result["parallelism"]["code"])
        self.assertEqual(
            ["services/order-service", "services/payment-service"],
            result["review_strategy"]["service_reviewers"],
        )
        self.assertTrue(result["review_strategy"]["global_review"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused red test**

Run:

```powershell
python -m unittest discover -s tests -p test_scheduling_strategy.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scheduling_strategy'`.

- [ ] **Step 3: Add the minimal strategy module**

Create `skills/e2e-dev-harness/scripts/scheduling_strategy.py`:

```python
#!/usr/bin/env python3
"""Auditable scheduling strategy for harness agent runs."""

from __future__ import annotations

import re


SCHEMA = "e2e-dev-harness.scheduling-decision.v1"
MAX_PARALLEL_WORKERS = 4
COMPLEX_REASON_MARKERS = (
    "large",
    "design-heavy",
    "contract",
    "schema",
    "database",
    "security",
    "payment",
    "refund",
    "multi-step",
)
AC_RE = re.compile(r"\bAC-?(\d+)\b", re.IGNORECASE)


def acceptance_ids(design_text: str) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for match in AC_RE.finditer(design_text or ""):
        ac_id = f"AC-{int(match.group(1))}"
        if ac_id not in seen:
            seen.add(ac_id)
            ids.append(ac_id)
    return ids


def complex_single_service(reasons: list[str], ac_ids: list[str]) -> bool:
    reason_text = " ".join(str(reason).lower() for reason in reasons)
    return len(ac_ids) > 1 or any(marker in reason_text for marker in COMPLEX_REASON_MARKERS)


def _lanes_for_acceptance(ac_ids: list[str], service: str) -> list[dict]:
    return [
        {
            "id": f"lane-{ac_id.lower()}",
            "acceptance_id": ac_id,
            "service": service,
            "parallel_group": f"task-item:{service}:{ac_id}",
            "requires_disjoint_edit_scope": True,
        }
        for ac_id in ac_ids
    ]


def decide(
    selected_mode: str,
    services: list[str] | None = None,
    reasons: list[str] | None = None,
    design_text: str = "",
) -> dict:
    service_list = list(services or [])
    reason_list = list(reasons or [])
    ac_ids = acceptance_ids(design_text)
    primary_service = service_list[0] if service_list else ""

    if selected_mode == "multi" or len(service_list) > 1:
        worker_count = min(MAX_PARALLEL_WORKERS, max(2, len(service_list)))
        return {
            "schema": SCHEMA,
            "selected_mode": selected_mode,
            "execution_model": "service-parallel",
            "max_workers": worker_count,
            "task_split": {"strategy": "service", "acceptance_ids": ac_ids},
            "implementation_lanes": [
                {
                    "id": f"service-{index + 1}",
                    "service": service,
                    "parallel_group": f"service:{service}",
                    "requires_disjoint_edit_scope": True,
                }
                for index, service in enumerate(service_list)
            ],
            "parallelism": {"design": "service-parallel", "test": "service-parallel", "code": "service-parallel", "review": "service-parallel"},
            "review_strategy": {"service_reviewers": service_list, "global_review": True},
            "blocked_parallelism": [],
            "reasons": reason_list,
        }

    if selected_mode == "single-review" and complex_single_service(reason_list, ac_ids):
        lanes = _lanes_for_acceptance(ac_ids or ["AC-1"], primary_service)
        return {
            "schema": SCHEMA,
            "selected_mode": selected_mode,
            "execution_model": "split-single",
            "max_workers": min(2, max(1, len(lanes))),
            "task_split": {"strategy": "acceptance-criteria", "acceptance_ids": ac_ids},
            "implementation_lanes": lanes,
            "parallelism": {"design": "serial", "test": "task-item-parallel", "code": "gated-by-edit-scope", "review": "task-item-parallel"},
            "review_strategy": {"service_reviewers": service_list, "global_review": True},
            "blocked_parallelism": ["single service code lanes need non-overlapping edit scopes before concurrent code dispatch"],
            "reasons": reason_list,
        }

    return {
        "schema": SCHEMA,
        "selected_mode": selected_mode,
        "execution_model": "single-worker",
        "max_workers": 1,
        "task_split": {"strategy": "single", "acceptance_ids": ac_ids},
        "implementation_lanes": [],
        "parallelism": {"design": "serial", "test": "serial", "code": "serial", "review": "serial"},
        "review_strategy": {"service_reviewers": service_list, "global_review": selected_mode == "single-review"},
        "blocked_parallelism": [],
        "reasons": reason_list,
    }
```

- [ ] **Step 4: Run the focused green test**

Run:

```powershell
python -m unittest discover -s tests -p test_scheduling_strategy.py
```

Expected: PASS.

---

### Task 2: Thread Strategy Into Plan Output And Schedule Metadata

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/orchestration_plan.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`
- Test: `tests/test_orchestration.py`
- Test: `tests/test_e2e_dev_harness_scripts.py`

- [ ] **Step 1: Run impact checks before symbol edits**

Use GitNexus MCP:

```text
impact({ repo: "e2e-dev-workflow", target: "agent_schedule", direction: "upstream" })
impact({ repo: "e2e-dev-workflow", target: "multi_agent_decision", direction: "upstream" })
```

Expected: Record risk, direct callers, and affected processes in implementation notes. If HIGH or CRITICAL, stop and report before editing.

- [ ] **Step 2: Add failing tests for schedule metadata**

Add to `tests/test_orchestration.py`:

```python
class SchedulingDecisionProjectionTests(unittest.TestCase):
    def test_agent_schedule_includes_scheduling_decision_when_supplied(self) -> None:
        artifacts = orchestration_plan.artifacts("feature", None, "2026-06-06", ["services/order-service"])
        agents = orchestration_plan.agent_plan("single-review", artifacts, ["services/order-service"])
        decision = {
            "schema": "e2e-dev-harness.scheduling-decision.v1",
            "execution_model": "split-single",
            "max_workers": 2,
            "parallelism": {"code": "gated-by-edit-scope"},
        }

        schedule = orchestration_plan.agent_schedule(
            "single-review",
            ["services/order-service"],
            agents,
            scheduling_decision=decision,
        )

        self.assertEqual(decision, schedule["scheduling_decision"])
        self.assertEqual(2, schedule["max_workers"])
        self.assertEqual("split-single", schedule["execution_model"])
```

Add to `tests/test_e2e_dev_harness_scripts.py`:

```python
class PlanSchedulingDecisionTests(unittest.TestCase):
    def test_plan_result_contains_scheduling_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True, exist_ok=True)
            design.write_text(
                "\n".join(
                    [
                        "# Feature",
                        "",
                        "## Scope",
                        "- services/order-service",
                        "",
                        "## Acceptance Criteria",
                        "- AC-1: Validate order.",
                        "- AC-2: Persist audit.",
                    ]
                ),
                encoding="utf-8",
            )
            (repo / "services" / "order-service").mkdir(parents=True)

            result = e2e_dev_harness.plan(
                repo,
                mode="single-review",
                design_doc=design,
                service_scope="affected",
                services_requested=["services/order-service"],
            )

        self.assertEqual("split-single", result["scheduling_decision"]["execution_model"])
        self.assertEqual(result["scheduling_decision"], result["agent_schedule"]["scheduling_decision"])
```

- [ ] **Step 3: Run red tests**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py -k SchedulingDecisionProjectionTests
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py -k PlanSchedulingDecisionTests
```

Expected: FAIL because `agent_schedule` does not accept `scheduling_decision` and `plan` does not return it.

- [ ] **Step 4: Import and call scheduling strategy**

Modify imports in `skills/e2e-dev-harness/scripts/orchestration_plan.py`:

```python
import scheduling_strategy  # noqa: E402
```

Change `multi_agent_decision` to accept optional strategy metadata:

```python
def multi_agent_decision(
    selected_mode: str,
    services: list[str],
    reasons: list[str],
    scheduling_decision: dict | None = None,
) -> dict:
    criteria = [
        "multiple affected services/modules",
        "HTTP/DMQ/shared contract boundary",
        "database/schema/config/security/payment/refund risk",
        "large or design-heavy implementation context",
        "user explicitly requested split agents",
    ]
    evidence = list(reasons)
    if services:
        evidence.append("selected services/modules: " + ", ".join(services))
    result = {
        "use_multi_agent": selected_mode == "multi",
        "selected_mode": selected_mode,
        "criteria": criteria,
        "evidence": evidence,
        "required_when_multi": [
            "one service-plans/<service>/implementation-plan.md per affected service/module",
            "one service-plans/<service>/code-agent.md handoff per code agent",
            "service-local implementation manifest, tests, coverage, business review",
            "service-local R2/R3 reviews plus global R1/R2/R3 review requests",
            "completion gate passes --require-handoffs for multi-service/split-agent runs",
        ],
    }
    if scheduling_decision:
        result["scheduling_decision"] = scheduling_decision
    return result
```

Change `agent_schedule` signature and body:

```python
def agent_schedule(
    selected_mode: str,
    services: list[str],
    agents: list[dict],
    scheduling_decision: dict | None = None,
) -> dict:
    tasks: list[dict] = []
    team_preset_key = agent_roles.team_preset_key(selected_mode)
    team_preset = agent_roles.team_preset_for_mode(selected_mode)
    decision = scheduling_decision or scheduling_strategy.decide(selected_mode, services, [])
    for index, agent in enumerate(agents, start=1):
        name = str(agent.get("name", f"agent-{index}"))
        phase = phase_for_agent(name)
        service = ""
        for candidate in services:
            if service_slug(candidate) in name:
                service = candidate
                break
        tasks.append(
            control_plane.task_contract(
                task_id=f"T{index:02d}",
                agent=name,
                phase=phase,
                role_group=role_group_for_phase(phase),
                role_template=agent.get("role_template", ""),
                role_template_key=agent.get("role_template_key", ""),
                service=service,
                parallel_group=f"service:{service}" if service and phase in {"tdd-red", "implement", "r3-review"} else phase,
                depends_on_phases=depends_on_for_phase(phase),
                inputs=agent.get("inputs", []),
                outputs=agent.get("outputs", []),
                runtime_subagent_type=runtime_subagent_type_for_phase(phase),
            )
        )
    return {
        "schema": "e2e-dev-harness.agent-schedule.v1",
        "selected_mode": selected_mode,
        "team_preset": team_preset_key,
        "completion_mode": team_preset.get("completion_mode", DEFAULT_COMPLETION_MODE),
        "execution_model": decision.get("execution_model") or team_preset.get("execution_model", DEFAULT_EXECUTION_MODEL),
        "max_workers": int(decision.get("max_workers") or team_preset.get("max_workers", 1)),
        "scheduling_decision": decision,
        "require_role_templates": True,
        "services": services,
        "coordination": "machine-readable task board; agents update task status and artifact hashes instead of exchanging long free-form chat.",
        "tasks": tasks,
    }
```

Modify `skills/e2e-dev-harness/scripts/e2e_dev_harness.py` inside `plan(...)`:

```python
    scheduling_decision = orchestration_plan.scheduling_strategy.decide(
        selected,
        artifact_services,
        reasons,
        design_text,
    )
    agents = orchestration_plan.agent_plan(selected, artifacts, artifact_services)
    schedule = orchestration_plan.agent_schedule(
        selected,
        artifact_services,
        agents,
        scheduling_decision=scheduling_decision,
    )
    return {
        ...
        "scheduling_decision": scheduling_decision,
        "multi_agent_decision": orchestration_plan.multi_agent_decision(
            selected,
            services,
            reasons,
            scheduling_decision=scheduling_decision,
        ),
        "agents": agents,
        "agent_schedule": schedule,
    }
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest discover -s tests -p test_scheduling_strategy.py
python -m unittest discover -s tests -p test_orchestration.py -k SchedulingDecisionProjectionTests
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py -k PlanSchedulingDecisionTests
```

Expected: PASS.

---

### Task 3: Generate Auditable Single-Service Task-Item Lanes

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/orchestration_plan.py`
- Modify: `skills/e2e-dev-harness/scripts/scheduling_strategy.py`
- Test: `tests/test_orchestration.py`

- [ ] **Step 1: Run impact check**

Use GitNexus MCP:

```text
impact({ repo: "e2e-dev-workflow", target: "agent_plan", direction: "upstream" })
impact({ repo: "e2e-dev-workflow", target: "agent_schedule", direction: "upstream" })
```

Expected: Record risk, direct callers, and affected processes. Stop if HIGH or CRITICAL.

- [ ] **Step 2: Add failing test for task-item metadata**

Add to `tests/test_orchestration.py`:

```python
class SplitSingleServiceLaneTests(unittest.TestCase):
    def test_split_single_schedule_marks_code_task_as_scope_gated(self) -> None:
        artifacts = orchestration_plan.artifacts("feature", None, "2026-06-06", ["services/order-service"])
        agents = orchestration_plan.agent_plan("single-review", artifacts, ["services/order-service"])
        decision = scheduling_strategy.decide(
            "single-review",
            ["services/order-service"],
            ["large or design-heavy implementation context"],
            "## Acceptance Criteria\n- AC-1: Validate.\n- AC-2: Persist.\n",
        )

        schedule = orchestration_plan.agent_schedule(
            "single-review",
            ["services/order-service"],
            agents,
            scheduling_decision=decision,
        )
        code_tasks = [task for task in schedule["tasks"] if task["phase"] == "implement"]

        self.assertEqual(1, len(code_tasks))
        self.assertEqual("gated-by-edit-scope", code_tasks[0]["scheduling"]["code_parallelism"])
        self.assertEqual(["AC-1", "AC-2"], code_tasks[0]["scheduling"]["acceptance_ids"])
        self.assertTrue(code_tasks[0]["scheduling"]["requires_scope_partition"])
```

- [ ] **Step 3: Run red test**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py -k SplitSingleServiceLaneTests
```

Expected: FAIL because task-level `scheduling` metadata is missing.

- [ ] **Step 4: Add task-level scheduling projection without adding code concurrency**

Add helper to `orchestration_plan.py`:

```python
def task_scheduling_metadata(task: dict, decision: dict) -> dict:
    phase = str(task.get("phase", "")).strip()
    parallelism = decision.get("parallelism", {}) if isinstance(decision, dict) else {}
    task_split = decision.get("task_split", {}) if isinstance(decision, dict) else {}
    if phase == "implement" and decision.get("execution_model") == "split-single":
        return {
            "execution_model": decision.get("execution_model", ""),
            "task_split": task_split.get("strategy", ""),
            "acceptance_ids": task_split.get("acceptance_ids", []),
            "code_parallelism": parallelism.get("code", "serial"),
            "requires_scope_partition": parallelism.get("code") == "gated-by-edit-scope",
        }
    return {
        "execution_model": decision.get("execution_model", ""),
        "task_split": task_split.get("strategy", ""),
        "code_parallelism": parallelism.get("code", "serial"),
        "requires_scope_partition": False,
    }
```

Inside `agent_schedule`, create the task first, then attach metadata:

```python
        task = control_plane.task_contract(
            task_id=f"T{index:02d}",
            agent=name,
            phase=phase,
            role_group=role_group_for_phase(phase),
            role_template=agent.get("role_template", ""),
            role_template_key=agent.get("role_template_key", ""),
            service=service,
            parallel_group=f"service:{service}" if service and phase in {"tdd-red", "implement", "r3-review"} else phase,
            depends_on_phases=depends_on_for_phase(phase),
            inputs=agent.get("inputs", []),
            outputs=agent.get("outputs", []),
            runtime_subagent_type=runtime_subagent_type_for_phase(phase),
        )
        task["scheduling"] = task_scheduling_metadata(task, decision)
        tasks.append(task)
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py -k SplitSingleServiceLaneTests
python -m unittest discover -s tests -p test_orchestration.py -k SchedulingDecisionProjectionTests
```

Expected: PASS.

---

### Task 4: Let Dispatcher Respect Explicit Wave Metadata

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/dispatcher.py`
- Test: `tests/test_enterprise_harness_architecture.py`
- Test: `tests/test_orchestration.py`

- [ ] **Step 1: Run impact checks**

Use GitNexus MCP:

```text
impact({ repo: "e2e-dev-workflow", target: "ready_tasks", direction: "upstream" })
impact({ repo: "e2e-dev-workflow", target: "dispatch_beat", direction: "upstream" })
```

Expected: Record risk, direct callers, and affected processes. Stop if HIGH or CRITICAL.

- [ ] **Step 2: Add failing test for conservative single-service code gating**

Add to `tests/test_enterprise_harness_architecture.py`:

```python
class DispatcherSchedulingPolicyTests(unittest.TestCase):
    def test_ready_tasks_blocks_scope_gated_single_service_code_parallelism(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            schedule = {
                "schema": "e2e-dev-harness.agent-schedule.v1",
                "scheduling_decision": {
                    "execution_model": "split-single",
                    "parallelism": {"code": "gated-by-edit-scope"},
                },
                "tasks": [
                    {
                        "id": "T01",
                        "agent": "code-developer-order-service-a",
                        "phase": "implement",
                        "role_group": "code",
                        "service": "services/order-service",
                        "parallel_group": "task-item:services/order-service:AC-1",
                        "inputs": [],
                        "outputs": ["docs/agent-runs/run/service-plans/order-service/code-agent-a.md"],
                        "scheduling": {"requires_scope_partition": True},
                        "status": "planned",
                    },
                    {
                        "id": "T02",
                        "agent": "code-developer-order-service-b",
                        "phase": "implement",
                        "role_group": "code",
                        "service": "services/order-service",
                        "parallel_group": "task-item:services/order-service:AC-2",
                        "inputs": [],
                        "outputs": ["docs/agent-runs/run/service-plans/order-service/code-agent-b.md"],
                        "scheduling": {"requires_scope_partition": True},
                        "status": "planned",
                    },
                ],
            }

            selected, blocked = dispatcher.ready_tasks(repo, schedule, max_workers=2, state=state)

        self.assertEqual(["T01"], [task["id"] for task in selected])
        self.assertTrue(any(item["task_id"] == "T02" for item in blocked))
        self.assertTrue(any("scope partition" in reason for item in blocked for reason in item["blocked_reasons"]))
```

- [ ] **Step 3: Run red test**

Run:

```powershell
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py -k DispatcherSchedulingPolicyTests
```

Expected: FAIL because `ready_tasks` does not inspect task scheduling metadata.

- [ ] **Step 4: Add conservative dispatcher blocker**

Add helper to `dispatcher.py`:

```python
def scheduling_policy_blockers(task: dict, selected: list[dict]) -> list[str]:
    scheduling = task.get("scheduling") if isinstance(task.get("scheduling"), dict) else {}
    if not scheduling.get("requires_scope_partition"):
        return []
    phase = str(task.get("phase", "")).strip()
    service = str(task.get("service", "")).strip()
    if phase != "implement" or not service:
        return []
    for prior in selected:
        prior_scheduling = prior.get("scheduling") if isinstance(prior.get("scheduling"), dict) else {}
        if (
            prior_scheduling.get("requires_scope_partition")
            and str(prior.get("phase", "")).strip() == "implement"
            and str(prior.get("service", "")).strip() == service
        ):
            return [
                f"Task requires explicit scope partition before concurrent code dispatch in {service}."
            ]
    return []
```

Inside `ready_tasks`, before selecting the task:

```python
        if not blockers:
            blockers.extend(scheduling_policy_blockers(task, selected))
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py -k DispatcherSchedulingPolicyTests
python -m unittest discover -s tests -p test_orchestration.py -k SplitSingleServiceLaneTests
```

Expected: PASS.

---

### Task 5: Add Reviewer Aggregation Metadata

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/scheduling_strategy.py`
- Modify: `skills/e2e-dev-harness/scripts/orchestration_plan.py`
- Test: `tests/test_scheduling_strategy.py`
- Test: `tests/test_orchestration.py`

- [ ] **Step 1: Add failing test for reviewer aggregation**

Add to `tests/test_scheduling_strategy.py`:

```python
    def test_review_strategy_names_service_and_global_aggregation(self) -> None:
        result = scheduling_strategy.decide(
            selected_mode="multi",
            services=["services/order-service", "services/payment-service"],
            reasons=["multiple affected services/modules"],
            design_text="## Acceptance Criteria\n- AC-1: Cross-service flow.\n",
        )

        self.assertEqual(
            {
                "service_reviewers": ["services/order-service", "services/payment-service"],
                "global_review": True,
                "aggregation": "service-reviews-then-global-r3",
            },
            result["review_strategy"],
        )
```

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m unittest discover -s tests -p test_scheduling_strategy.py -k review_strategy
```

Expected: FAIL because `aggregation` is missing.

- [ ] **Step 3: Add aggregation field**

In `scheduling_strategy.decide`, update `review_strategy` values:

```python
"review_strategy": {
    "service_reviewers": service_list,
    "global_review": True,
    "aggregation": "service-reviews-then-global-r3",
},
```

For `single-worker`, use:

```python
"review_strategy": {
    "service_reviewers": service_list,
    "global_review": selected_mode == "single-review",
    "aggregation": "single-reviewer-chain" if selected_mode == "single-review" else "minimal",
},
```

For `split-single`, use:

```python
"review_strategy": {
    "service_reviewers": service_list,
    "global_review": True,
    "aggregation": "task-item-reviews-then-service-r3",
},
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m unittest discover -s tests -p test_scheduling_strategy.py
python -m unittest discover -s tests -p test_orchestration.py -k SchedulingDecisionProjectionTests
```

Expected: PASS.

---

### Task 6: Document Strategy And Preserve Operator Guidance

**Files:**
- Modify: `skills/e2e-dev-harness/references/agent-orchestration.md`
- Modify: `skills/e2e-dev-harness/SKILL.md`
- Test: `tests/test_skill_docs.py`

- [ ] **Step 1: Add failing docs assertion**

Add to `tests/test_skill_docs.py`:

```python
class AgentSchedulingStrategyDocsTests(unittest.TestCase):
    def test_agent_orchestration_documents_scheduling_strategy_layer(self) -> None:
        text = (ROOT / "skills" / "e2e-dev-harness" / "references" / "agent-orchestration.md").read_text(encoding="utf-8")

        self.assertIn("Scheduling Strategy Layer", text)
        self.assertIn("single service code lanes need non-overlapping edit scopes", text)
        self.assertIn("service-reviews-then-global-r3", text)
```

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m unittest discover -s tests -p test_skill_docs.py -k AgentSchedulingStrategyDocsTests
```

Expected: FAIL because the docs section is missing.

- [ ] **Step 3: Update docs**

Add this section to `skills/e2e-dev-harness/references/agent-orchestration.md` near the L1 dispatch section:

```markdown
## Scheduling Strategy Layer

The scheduling strategy layer decides how a run should be split before the
dispatcher claims workers. It emits `scheduling_decision` into the plan result
and `agent-schedule.json`.

- `single-worker`: small, low-risk single-service work. Code remains serial.
- `split-single`: complex single-service work. The schedule records
  acceptance-criterion lanes and reviewer lanes, but single service code lanes
  need non-overlapping edit scopes before concurrent code dispatch.
- `service-parallel`: multi-service work. Service-local design, test, code, and
  R3 review tasks may run in parallel across distinct service groups after their
  gates and handoffs are ready.

Reviewer aggregation is explicit:

- `single-reviewer-chain`: single-service role-separated review chain.
- `task-item-reviews-then-service-r3`: task-item review evidence rolls up into
  the service implementation review.
- `service-reviews-then-global-r3`: service-local implementation reviews finish
  before the global R3/completion review closes cross-service contracts.

The dispatcher remains a mechanical executor. Strategy decides the intended
split and concurrency policy; `dispatch-beat`, `agent_scheduler`, `phase_guard`,
and reviewer gates still enforce readiness, ownership, leases, write scope, and
completion evidence.
```

- [ ] **Step 4: Run docs test**

Run:

```powershell
python -m unittest discover -s tests -p test_skill_docs.py -k AgentSchedulingStrategyDocsTests
```

Expected: PASS.

---

### Task 7: Regression, Change Detection, And Installed-Copy Sync

**Files:**
- Modify only if needed: installed copies under `.codex`, `.agents`, `.claude` through the existing installer/sync path.

- [ ] **Step 1: Run focused regression**

Run:

```powershell
python -m unittest discover -s tests -p test_scheduling_strategy.py
python -m unittest discover -s tests -p test_orchestration.py -k "SchedulingDecisionProjectionTests or SplitSingleServiceLaneTests"
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py -k DispatcherSchedulingPolicyTests
python -m unittest discover -s tests -p test_skill_docs.py -k AgentSchedulingStrategyDocsTests
```

Expected: PASS.

- [ ] **Step 2: Run broader harness regression**

Run:

```powershell
python -m unittest discover -s tests -p test_orchestration.py
python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py
python -m unittest discover -s tests -p test_enterprise_harness_architecture.py
python -m unittest discover -s tests -p test_skill_docs.py
```

Expected: PASS. If runtime exceeds the local budget, capture the first failing command and continue with the smallest reproducer.

- [ ] **Step 3: Run GitNexus change detection before commit**

Use GitNexus MCP:

```text
detect_changes({ repo: "e2e-dev-workflow", scope: "all" })
```

Expected: Changed symbols are limited to scheduling strategy, orchestration schedule projection, dispatcher scheduling policy, docs, and tests.

- [ ] **Step 4: Sync installed runtime copies**

Run:

```powershell
node tools\install-e2e-dev-harness.mjs --sync --yes --json
```

Expected: JSON reports installed copies updated or already in sync.

- [ ] **Step 5: Verify command surface**

Run:

```powershell
e2e-harness --help
```

Expected: Existing command surface remains available; no new command is required for the strategy layer.

## Self-Review

- Spec coverage: The plan covers the requested scheduling layer, complex single-service split decision, multi-service split decision, and service/global reviewer aggregation.
- Placeholder scan: No task uses TBD, TODO, or "similar to previous"; every code-editing task includes concrete code snippets and test commands.
- Type consistency: `scheduling_decision`, `execution_model`, `task_split`, `parallelism`, `review_strategy`, and task-level `scheduling` are consistently named across tests and snippets.
- Risk control: The plan requires GitNexus impact before editing existing symbols and `detect_changes` before commit.
