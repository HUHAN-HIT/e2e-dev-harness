# Review Policy Start Customization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auditable startup review policy contract that records the user requested tier, the automatically detected minimum tier, and the effective tier.

**Status:** Completed; Tasks 1-5 implemented and verified.

**Architecture:** Reuse `task_tier.py` as the source of truth for tier ordering and required gates. Keep existing `tier` and `required_gates` fields backward compatible while adding explicit policy fields that make user customization visible and non-downgrading.

**Tech Stack:** Python standard library, `unittest`, existing e2e-dev-harness CLI modules.

---

### Task 1: Tier Policy Contract

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/task_tier.py`
- Test: `tests/test_e2e_dev_harness_scripts.py`

- [x] Write failing tests showing an explicit low tier cannot reduce below the auto minimum.
- [x] Add tier ordering helpers in `task_tier.py`.
- [x] Return `user_requested`, `auto_minimum`, `effective`, and `downgrade_blocked` fields from `task_tier.evaluate`.
- [x] Keep legacy `tier` and `required_gates` mapped to the effective tier.
- [x] Run focused workflow-tier tests.

### Task 2: Startup Workflow Plan Recording

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Test: `tests/test_e2e_dev_harness_scripts.py`

- [x] Write failing tests showing `workflow-plan.json` records review policy request/minimum/effective fields.
- [x] Thread a `review_policy` argument into `workflow_plan_for_start`.
- [x] Store the review policy in `workflow_plan` and `run-state.json` without changing lifecycle order.
- [x] Run focused start workflow tests.

### Task 3: Verification

**Files:**
- Verify: `skills/e2e-dev-harness/scripts/task_tier.py`
- Verify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Verify: `tests/test_e2e_dev_harness_scripts.py`

- [x] Run `python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py`.
- [x] Run `python -m unittest discover -s tests -p test_orchestration.py` if start workflow changes touch shared orchestration contracts.
- [x] Run `gitnexus_detect_changes` before any commit or completion claim.
- [x] Report changed files, verification evidence, and any residual risk.

### Task 4: Startup CLI Review Tier

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Test: `tests/test_e2e_dev_harness_scripts.py`

- [x] Add a focused CLI test for `start --review-tier basic`.
- [x] Add `--review-tier` to the `start` parser with `task_tier.TIERS` choices.
- [x] Thread `review_tier` through `run_from_args` into the startup review policy calculation.
- [x] Keep automatic safety minimum enforcement unchanged.
- [x] Run focused start CLI tests and broader harness regression.

### Task 5: Compact Stdout Review Policy Visibility

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/output_contract.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Test: `tests/test_e2e_dev_harness_scripts.py`

- [x] Write a failing CLI test showing default `start` compact stdout omits `review_policy`.
- [x] Add a compact review policy summary with `user_requested`, `auto_minimum`, `effective`, and `downgrade_blocked`.
- [x] Expose the computed startup review policy at the command result top level for output-contract consumers.
- [x] Preserve the review policy summary in compact truncation fallback.
- [x] Run focused start tests, full harness regression, and GitNexus change detection.
