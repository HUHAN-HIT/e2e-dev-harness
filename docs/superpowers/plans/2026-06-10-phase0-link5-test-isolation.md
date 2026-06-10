# Phase 0 ⑤ Auth-Layer Self-Fidelity (Test Isolation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the harness self-test suite trustworthy: reproducibly green under randomized collection order, with a dependency-free seed guard that makes any isolation defect reproducible, and a clean encoding baseline.

**Architecture:** Add a seedable `pytest_collection_modifyitems` shuffle in `tests/conftest.py` (no third-party plugin, preserving the project's zero-dependency property). Factor the shuffle into a pure, unit-testable helper. Then sweep the suite across several seeds, and for every order-dependent failure, fix the underlying shared-state leak with proper fixtures/teardown — not by pinning order.

**Tech Stack:** Python 3.10+, pytest 9, stdlib `random`.

---

## Files

- Modify: `skills/e2e-dev-harness/tests/conftest.py` — add `_seeded_order()` helper + `pytest_collection_modifyitems` + `pytest_report_header`.
- Create: `skills/e2e-dev-harness/tests/test_conftest_shuffle.py` — unit test for the helper.
- Modify: (discovered during sweep) whichever test/source files leak shared state.

## Discipline

- `gitnexus_impact` before editing any production symbol; TDD red→green; `detect_changes` before commit.

---

### Task 1: Seedable, dependency-free shuffle guard

**Files:**
- Modify: `skills/e2e-dev-harness/tests/conftest.py`
- Create: `skills/e2e-dev-harness/tests/test_conftest_shuffle.py`

- [ ] **Step 1: Write the failing test for the pure helper**

```python
# tests/test_conftest_shuffle.py
import importlib

conftest = importlib.import_module("conftest")


def test_seeded_order_is_deterministic_permutation():
    items = list(range(20))
    a = conftest._seeded_order(items, 42)
    b = conftest._seeded_order(items, 42)
    assert a == b                      # same seed -> same order
    assert sorted(a) == items          # a permutation, nothing lost
    assert a != items                  # actually reorders (seed 42 on 0..19)


def test_seeded_order_differs_across_seeds():
    items = list(range(20))
    assert conftest._seeded_order(items, 1) != conftest._seeded_order(items, 2)
```

- [ ] **Step 2: Run it, expect failure**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_conftest_shuffle.py -q`
Expected: FAIL (`_seeded_order` does not exist).

- [ ] **Step 3: Implement the helper + hooks in conftest.py**

Append to `tests/conftest.py`:

```python
import os
import random


def _seeded_order(items, seed):
    """Pure, deterministic permutation of items for a given integer seed."""
    ordered = list(items)
    random.Random(seed).shuffle(ordered)
    return ordered


def _active_seed():
    raw = os.environ.get("E2E_TEST_SEED")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def pytest_collection_modifyitems(session, config, items):
    seed = _active_seed()
    if seed is None:
        return
    items[:] = _seeded_order(items, seed)


def pytest_report_header(config):
    seed = _active_seed()
    if seed is not None:
        return f"e2e-test-seed: {seed} (reproduce failures with E2E_TEST_SEED={seed})"
    return None
```

- [ ] **Step 4: Run it, expect pass**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_conftest_shuffle.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/tests/conftest.py skills/e2e-dev-harness/tests/test_conftest_shuffle.py
git commit -m "test(e2e-dev-harness): seedable dependency-free isolation guard"
```

---

### Task 2: Isolation sweep — find and fix order-dependent leaks

This task is investigation-driven; the concrete sub-fixes depend on what the sweep reveals.

- [ ] **Step 1: Sweep across seeds**

Run (bash):
```bash
cd skills/e2e-dev-harness
for s in 1 2 3 42 1337 2026; do
  echo "=== seed $s ==="; E2E_TEST_SEED=$s PYTHONIOENCODING=utf-8 python -m pytest tests -q -p no:cacheprovider 2>&1 | tail -3
done
```
Expected: record which seeds fail and which tests fail.

- [ ] **Step 2: For each failing test, reproduce in isolation vs. in-suite**

For a failing `tests/test_X.py::test_y` under seed `S`:
```bash
E2E_TEST_SEED=S python -m pytest tests/test_X.py::test_y -q          # isolated
E2E_TEST_SEED=S python -m pytest tests -q 2>&1 | grep -A3 test_y     # in suite
```
A test that passes isolated but fails in-suite confirms cross-test state leakage.

- [ ] **Step 3: Diagnose the leak (systematic-debugging)**

Classify the leaked state. Common sources and fixes:
- module/class-level mutable global not reset → reset via fixture/teardown.
- `os.chdir(...)` without restore → switch to `monkeypatch.chdir(tmp_path)`.
- `os.environ[...] = ...` without restore → `monkeypatch.setenv(...)`.
- module attribute patched without isolation → `monkeypatch.setattr(...)`.
- reused fixed temp path → `tmp_path`.

- [ ] **Step 4: TDD each fix**

Pin the failure first (run with the failing seed), apply the minimal fixture/teardown fix in the offending test (or a `conftest` autouse reset for a genuinely shared module global), re-run that test under the failing seed to confirm green. Run `gitnexus_impact` first only if the fix touches a production symbol.

- [ ] **Step 5: Re-sweep until clean**

Re-run the Step 1 loop. Expected: all seeds green.

- [ ] **Step 6: Commit**

```bash
git add -A skills/e2e-dev-harness/tests
git commit -m "fix(e2e-dev-harness): remove cross-test state leaks (order-stable suite)"
```

---

### Task 3: Confirm / lock encoding baseline

- [ ] **Step 1: Verify the previously-red encoding tests**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_cli_request_file.py -q`
Expected: PASS (subprocess calls already pass `encoding="utf-8"`). If any I/O path still decodes with the platform default, force `encoding="utf-8"` there and pin with a test. If already green, no code change — record that the baseline is clean.

- [ ] **Step 2: Full green under default + several seeds (final gate)**

Run:
```bash
cd skills/e2e-dev-harness
python -m pytest tests -q
for s in 7 99 31415; do E2E_TEST_SEED=$s python -m pytest tests -q 2>&1 | tail -1; done
```
Expected: all green.

- [ ] **Step 3: detect_changes + ensure scope is ⑤-only**

```text
detect_changes(scope="all", repo="e2e-dev-workflow")
```
Expected: only test-isolation/conftest changes (plus any minimal encoding fix).

---

## Self-Review

- Spec coverage: implements ⑤ exit criteria (green under ≥5 seeds, reproducible seed printed, no long-red tests).
- Placeholder scan: Task 2 is intentionally investigation-driven; its concrete fixes are bounded by the enumerated leak taxonomy and TDD'd per failure — not a "TODO".
- Type consistency: helper named `_seeded_order` used consistently in conftest and its test.

## Follow-on (separate plans, after ⑤ lands)

- ① acceptance contract (`core/acceptance.py` + clarification gate)
- ③ test-substance gate (`core/test_substance.py` + IMPLEMENTED gate)
- ② scope manifest + PARTIAL-vs-VERIFIED gate
