# Handoff: e2e-dev-harness coordinator context optimization

## Goal
Stop the coordinator (main agent) from abandoning the harness on large `multi`
runs (the 5-service x 4-role ~= 29-task case). Reduce real coordination load and
make session handoffs feel routine, without breaking documented hard rules.

## Done in prior session (in working tree, NOT yet git-committed)
- P0 #3 (handoff normalization) DONE.
  - session_checkpoint.py: added open_task_count(), estimate_expected_handoffs();
    context_budget() now returns planned_tasks + expected_handoffs
    (~ open_tasks * 3 tool-calls / max_tool_calls). Flows to coordinator via
    coordinator_context_budget in `next` stdout (output_contract.compact_payload).
  - SKILL.md Agent Orchestration: added one line:
    "Large `multi` schedules are normal: `expected_handoffs` predicts sessions; never downgrade to manual coding."
    (body must stay <= 2200 words; test_skill_docs enforces this; currently ~2200, tight).
  - Test: tests/test_orchestration.py::...test_context_budget_estimates_expected_handoffs_from_schedule (TDD red->green).
  - Full suite: 836 passed (one time-based flake test_agent_scheduler_lease::test_reclaim_requires_force_on_active_claim passes in isolation).
- P0 #1 (max-workers) already handled by in-flight diff. coordinator_flow.py:334-377
  already emits --max-workers 2/4 in recommended dispatch commands. Bare CLI default
  stays 1 (e2e_dev_harness.py:2801); left intentionally (redundant + test-heavy).

## Key finding that blocked original P1 #2
"Prune low-risk services' design/review roles" CONFLICTS with hard rules:
- SKILL.md:113 multi requires one global design + service-local design slice per service.
- SKILL.md:159 service-local R2/R3 review required for EVERY generated service plan.
Once a service slice exists, its design+test+code+review roles are all mandatory.
Per-service role pruning is OFF the table.

## Where the explosion comes from
orchestration_plan.py:
- agents builder, lines 706-787: per-service loop appends 4 agents
  (service-designer-*, test-case-developer-*, code-developer-*, implementation-reviewer-*).
- Gated by has_service_slices / service_plans (built from detected service candidates).
- agent_schedule() at line 894 maps agents -> tasks.

## CHOSEN DIRECTION: Option A (invariant-safe) tier-gated slice CREATION
Reduce the NUMBER of services that get an independent slice (not roles per slice).
Create an independent slice only when the service has real isolation need:
explicit --service/--path, cross-service dependency evidence, or design-declared
contract/data/event risk. Co-owned low-risk modules fold into the global plan or a
merged slice. Every generated slice keeps the full 4-role set -> all hard rules intact.
Expected effect: 5 services -> ~2-3 slices -> ~29 -> ~15 tasks.

## Concrete tasks for next session
1. Clean baseline: python -m pytest tests/ -q (expect 836 passed + 1 flake).
2. Inspect service_plans construction in orchestration_plan.py (resolve_service_scope,
   services_from_design, services_from_dependency_report, lines ~129-249, 382-498) and
   how has_service_slices is set. Find where "all detected candidates" becomes "slices".
3. Add a risk filter: a service earns an independent slice only if it has
   (a) dependency evidence (HTTP/MQ/contract) targeting it, OR
   (b) design-declared contract/data/event risk, OR
   (c) explicit user --service/--path selection.
   Otherwise fold into global plan (single combined code task).
4. TDD: write failing test first in tests/test_orchestration.py, e.g.
   "5 candidates but only 2 with dependency evidence -> 2 slices, ~N tasks".
5. Keep multi_agent_decision evidence/criteria accurate (orchestration_plan.py:935).
6. Verify gates still pass: service_design_gate, reviewer_gate, handoff_gate, and
   tests/test_orchestration.py, tests/test_e2e_dev_harness_scripts.py.
7. Update SKILL.md wording if slice-selection semantics change (watch 2200-word limit).

## Cautions
- Working tree has 2300+ lines of uncommitted in-flight diff ("coordinator context
  guardrails"). Confirm ownership / consider committing P0 separately before P1.
- Do NOT pursue Option B (relax R2/R3 hard rule); breaks review-isolation promise.
- Body-word limit on SKILL.md is the easiest accidental test break.

## Remaining lower-priority items
- P1 #5: mode-selection hard condition (require frozen contract / shared state / event
  dependency before forcing multi); overlaps Option A, may be same change.
- P2 #4: extend harness_stop_guard to flag "mid-run downgrade to manual coding".
