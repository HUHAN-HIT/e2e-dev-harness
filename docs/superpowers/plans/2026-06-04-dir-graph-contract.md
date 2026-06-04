# Dir Graph Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `.e2e/dir-graph.yaml` contract that describes repository roles, protected paths, skill IO boundaries, lifecycle transitions, and pipeline steps, then validate it from preflight without changing runtime lifecycle semantics.

**Architecture:** Introduce a small `dir_graph.py` module that loads a constrained YAML subset, validates it against current harness constants, and returns structured blockers. Keep execution authority in `run_state.py`, `coordinator_flow.py`, and `state_store`; the dir graph is a contract projection and drift detector.

**Tech Stack:** Python standard library, existing `unittest` suite, existing preflight aggregator.

---

### Task 1: Read-Only Contract Loader

**Files:**
- Create: `skills/e2e-dev-harness/scripts/dir_graph.py`
- Test: `tests/test_preflight_aggregator.py`

- [ ] **Step 1: Write failing tests**

Add tests proving that absent dir graphs do not block, valid dir graphs pass, and invalid required directories produce `BLK_DIR_GRAPH_CONTRACT`.

- [ ] **Step 2: Run red test**

Run: `python -m unittest discover -s tests -p test_preflight_aggregator.py`
Expected: failure because `dir_graph` or `dir_graph_contract_blockers` does not exist.

- [ ] **Step 3: Implement minimal loader and validator**

Create `dir_graph.py` with:
- `DIR_GRAPH_SCHEMA = "e2e-dev-harness.dir-graph.v1"`
- `DIR_GRAPH_PATH = Path(".e2e") / "dir-graph.yaml"`
- `load_dir_graph(repo)`
- `validate_dir_graph(repo, graph)`
- `dir_graph_contract_blockers(repo, run_state_path=None)`

- [ ] **Step 4: Run green test**

Run: `python -m unittest discover -s tests -p test_preflight_aggregator.py`
Expected: pass.

### Task 2: Preflight Integration

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/preflight.py`
- Test: `tests/test_preflight_aggregator.py`

- [ ] **Step 1: Add failing preflight test**

Assert `aggregate_preflight_blockers()` includes a dir-graph blocker when `.e2e/dir-graph.yaml` declares a missing required directory.

- [ ] **Step 2: Run red test**

Run: `python -m unittest discover -s tests -p test_preflight_aggregator.py`
Expected: failure because preflight does not call the dir graph checker.

- [ ] **Step 3: Add additive check**

Import `dir_graph` in `preflight.py` and add a `dir_graph_contract` entry to `preflight_checks()`. The check must be optional when `.e2e/dir-graph.yaml` is absent.

- [ ] **Step 4: Run green test**

Run: `python -m unittest discover -s tests -p test_preflight_aggregator.py`
Expected: pass.

### Task 3: Current Repo Contract

**Files:**
- Create: `.e2e/dir-graph.yaml`
- Test: `tests/test_preflight_aggregator.py`

- [ ] **Step 1: Add current repo contract**

Declare core directories, protected harness source paths, role IO boundaries, lifecycle list, gate transitions, and pipeline phases matching the current code.

- [ ] **Step 2: Validate current repo**

Run: `python -m unittest discover -s tests -p test_preflight_aggregator.py`
Expected: pass with the checked-in dir graph.

### Task 4: Verification

**Files:**
- Existing changed files only.

- [ ] **Step 1: Run targeted tests**

Run: `python -m unittest discover -s tests -p test_preflight_aggregator.py`
Expected: pass.

- [ ] **Step 2: Run focused harness tests**

Run: `python -m unittest discover -s tests -p test_harness_doctor.py`
Expected: pass.

- [ ] **Step 3: Run GitNexus change detection**

Run GitNexus detect changes before any commit. Expected impact: new dir graph contract module, preflight aggregation path, and tests only.
