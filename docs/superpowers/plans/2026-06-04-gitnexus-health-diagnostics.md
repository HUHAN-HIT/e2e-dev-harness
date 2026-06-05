# GitNexus Health Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add compatible, read-only GitNexus freshness and FTS health diagnostics to `kg_refresh` and `doctor` without changing gate pass/fail semantics.

**Architecture:** `kg_refresh.detect_gitnexus_index()` remains the single source for repository-local GitNexus index facts. `harness_doctor.gitnexus_check()` consumes the same facts for operator-facing health messages, while existing gates keep their current behavior until a later tightening slice.

**Tech Stack:** Python standard library, unittest, GitNexus MCP impact analysis, existing e2e-dev-harness scripts.

---

### Task 1: Extend GitNexus Index Facts

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/kg_refresh.py`
- Test: `tests/test_kg_refresh.py`

- [ ] **Step 1: Write the failing test**

Add a test that creates `.gitnexus/meta.json` with `lastCommit`, `stats`, and `capabilities.fts.status`, patches current git HEAD, and asserts the returned `gitnexus_index` includes `last_commit`, `current_head`, `is_stale`, `files`, `fts_status`, and `recommended_refresh_command`.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m unittest discover -s tests -p test_kg_refresh.py`

Expected: FAIL because the new fields are missing.

- [ ] **Step 3: Implement minimal read-only metadata extraction**

Add a small helper that reads `git rev-parse HEAD` without throwing, then extend `detect_gitnexus_index()` with compatible fields only. Existing keys must keep their names and semantics.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `python -m unittest discover -s tests -p test_kg_refresh.py`

Expected: PASS.

### Task 2: Surface Health In Doctor

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/harness_doctor.py`
- Test: `tests/test_harness_doctor.py`

- [ ] **Step 1: Write the failing test**

Add a test that patches tool discovery, creates a stale GitNexus meta file, runs `harness_doctor.evaluate(repo)`, and asserts the `gitnexus` check warns with `gitnexus analyze .`, `lastCommit`, `HEAD`, and `FTS`.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m unittest discover -s tests -p test_harness_doctor.py`

Expected: FAIL because doctor only reports CLI availability.

- [ ] **Step 3: Implement minimal doctor message enrichment**

Import `kg_refresh`, pass `repo` into `gitnexus_check(repo)`, and include freshness/FTS details in the message. Missing CLI remains the existing warning; stale index becomes warning, fresh index with available FTS remains pass.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `python -m unittest discover -s tests -p test_harness_doctor.py`

Expected: PASS.

### Task 3: Verify Impact And Scope

**Files:**
- No additional code files.

- [ ] **Step 1: Run both focused suites**

Run: `python -m unittest discover -s tests -p test_kg_refresh.py`

Run: `python -m unittest discover -s tests -p test_harness_doctor.py`

Expected: both PASS.

- [ ] **Step 2: Run broader fast anchors**

Run: `python -m unittest discover -s tests -p test_gates_implementation.py`

Expected: PASS because gate behavior is unchanged.

- [ ] **Step 3: Run GitNexus change detection**

Run: `gitnexus_detect_changes(scope="all", repo="e2e-dev-workflow")`

Expected: changes map to `kg_refresh`, `harness_doctor`, and tests only.
