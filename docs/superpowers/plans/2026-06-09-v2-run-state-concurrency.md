# v2 run-state Concurrency Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the v2 single-file SSOT (`run-state.json`) safe under concurrent writers so parallel reviewer evidence (r1/r2/r3) can never be silently lost.

**Architecture:** v2 already eliminated v1's multi-file split-brain — `run-state.json` is the sole SSOT and all derived views (navigation, gates, phase advance) are recomputed, not stored. The remaining gap is *intra-file* concurrency: every mutating CLI verb does `load() → mutate → save()` with no lock, so concurrent verbs lose updates (last-`os.replace`-wins). We add one exclusive-lock `mutate()` helper in `run_state.py` and route the three concurrent-capable verbs (`submit`, `dispatch`, `next`) through it. `gate` is read-only (excluded); `start` is run-creation / single-writer (excluded).

**Tech Stack:** Python 3.11 stdlib only (`os.open(O_CREAT|O_EXCL)` advisory lockfile, `contextlib`, `time`), pytest.

---

## Path note (staged rename in this working tree)

`git status` shows a **staged rename** `skills/e2e-dev-harness-v2/ → skills/e2e-dev-harness/`. All paths below use the **post-rename live path** `skills/e2e-dev-harness/...`. If a file fails to open (this tree is under a cloud-synced `Documents` folder and intermittently returns "file not found" for materialized-but-not-downloaded files), re-run the read/test once to force materialization, or `git show HEAD:skills/e2e-dev-harness-v2/<path>` to read the committed copy.

## File Structure

- **Modify** `skills/e2e-dev-harness/scripts/harness_v2/core/run_state.py` — add `_lock()` + `mutate()`, make `save()` tmp name unique. (Currently 61 lines; one clear responsibility = SSOT persistence. Adding the lock here keeps the critical section co-located with `load`/`save`.)
- **Modify** `skills/e2e-dev-harness/scripts/harness_v2/cli/commands/submit.py` — route through `mutate()`.
- **Modify** `skills/e2e-dev-harness/scripts/harness_v2/cli/commands/dispatch.py` — route the state write through `mutate()`.
- **Modify** `skills/e2e-dev-harness/scripts/harness_v2/cli/commands/next.py` — route the evaluate+save through `mutate()`.
- **Test** `skills/e2e-dev-harness/tests/test_run_state.py` — concurrency unit tests.
- **Test (create)** `skills/e2e-dev-harness/tests/test_concurrency_v2.py` — parallel-reviewer integration test.

**Test command (used throughout):**
```bash
python -m pytest skills/e2e-dev-harness/tests/test_run_state.py skills/e2e-dev-harness/tests/test_concurrency_v2.py -v
```
(`tests/conftest.py` puts `scripts/` on `sys.path`, so `from harness_v2.core import run_state` works.)

---

## Task 0: Baseline — existing suite green

**Files:** none (verification only)

- [ ] **Step 1: Run the existing run-state suite**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_run_state.py -v`
Expected: PASS (all existing tests). This also forces the v2 source files to materialize on disk and confirms the import path works before any edit.

- [ ] **Step 2: Capture baseline**

Run: `git stash list && git status --short | head`
Expected: a clean view of the staged rename; no unexpected modifications under `harness_v2/`.

---

## Task 1: Add concurrency-safe `mutate()` + unique tmp to `run_state.py`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/harness_v2/core/run_state.py`
- Test: `skills/e2e-dev-harness/tests/test_run_state.py`

- [ ] **Step 1: Write the failing concurrency test**

Append to `skills/e2e-dev-harness/tests/test_run_state.py`:

```python
import threading


def test_mutate_atomic_under_concurrency(tmp_path):
    p = tmp_path / "run-state.json"
    st = run_state.new_run_state("r1", "feat", "req")
    st["phases"] = {"REVIEWED": {"evidence": {}}}
    run_state.save(p, st)

    def add_key(k):
        run_state.mutate(
            p, lambda s: s["phases"]["REVIEWED"]["evidence"].__setitem__(k, {"path": k})
        )

    keys = [f"r{i}_review" for i in range(20)]
    threads = [threading.Thread(target=add_key, args=(k,)) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ev = run_state.load(p)["phases"]["REVIEWED"]["evidence"]
    assert sorted(ev) == sorted(keys)  # zero lost updates


def test_mutate_releases_lock_and_persists(tmp_path):
    p = tmp_path / "run-state.json"
    run_state.save(p, run_state.new_run_state("r1", "feat", "req"))
    run_state.mutate(p, lambda s: s.__setitem__("feature", "feat2"))
    assert not (tmp_path / "run-state.json.lock").exists()
    assert run_state.load(p)["feature"] == "feat2"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_run_state.py::test_mutate_atomic_under_concurrency -v`
Expected: FAIL — `AttributeError: module 'harness_v2.core.run_state' has no attribute 'mutate'`.

- [ ] **Step 3: Implement `_lock` + `mutate`, make tmp unique**

In `run_state.py`, add `import contextlib` and `import time` to the existing imports (keep `json`, `os`, `datetime`, `Path`). After the `save()` function, add:

```python
_LOCK_TIMEOUT_S = 10.0
_LOCK_POLL_S = 0.02


@contextlib.contextmanager
def _lock(path):
    """Exclusive advisory lock via O_EXCL sidecar; cross-platform, stdlib only."""
    lock = Path(str(path) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    fd = None
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"run-state lock busy: {lock}")
            time.sleep(_LOCK_POLL_S)
    try:
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(str(lock))


def mutate(path, fn, now=None):
    """Concurrency-safe load -> fn(state) (in place) -> save, under an exclusive
    lock. Returns the saved state. Use this for every mutating verb so parallel
    workers (e.g. r1/r2/r3 reviewers) cannot clobber each other's evidence."""
    with _lock(path):
        state = load(path)
        fn(state)
        save(path, state, now=now)
        return state
```

In the existing `save()`, change the tmp filename to be process-unique (prevents two concurrent saves from sharing one `.tmp`):

```python
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
```

- [ ] **Step 4: Run to verify both tests pass**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_run_state.py -v`
Expected: PASS (all existing + the two new tests).

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/harness_v2/core/run_state.py skills/e2e-dev-harness/tests/test_run_state.py
git commit -m "fix(harness-v2): add locked run_state.mutate() to prevent lost updates"
```

---

## Task 2: Route `submit` through `mutate()` + parallel-reviewer integration test

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/harness_v2/cli/commands/submit.py`
- Test: `skills/e2e-dev-harness/tests/test_concurrency_v2.py` (create)

- [ ] **Step 1: Write the failing integration test**

Create `skills/e2e-dev-harness/tests/test_concurrency_v2.py`:

```python
import threading
import types
from pathlib import Path

from harness_v2.core import run_state
from harness_v2.cli.commands import submit as submit_cmd


def _args(state, repo, key, evidence):
    return types.SimpleNamespace(
        state=str(state), repo=str(repo), phase="REVIEWED",
        key=key, path=str(evidence), status="done", reason=None,
    )


def test_parallel_reviewer_submits_all_survive(tmp_path):
    p = tmp_path / "run-state.json"
    st = run_state.new_run_state("r1", "feat", "req",
                                 tier="critical", pipeline="critical")
    st["current_phase"] = "REVIEWED"
    run_state.save(p, st)
    evidence = tmp_path / "review.txt"
    evidence.write_text("ok", encoding="utf-8")

    def do(key):
        submit_cmd.run(_args(p, tmp_path, key, evidence))

    threads = [threading.Thread(target=do, args=(k,))
               for k in ("r1_review", "r2_review", "r3_review")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ev = run_state.load(p)["phases"]["REVIEWED"]["evidence"]
    assert set(ev) == {"r1_review", "r2_review", "r3_review"}
```

- [ ] **Step 2: Run to verify it is flaky/failing on the current code**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_concurrency_v2.py -v --count=1`
Expected: FAIL or intermittently FAIL — fewer than 3 evidence keys survive, because `submit.py` still uses unguarded `load()/save()`. (If `--count` is unavailable, run the command 5x; at least one run drops a key.)

- [ ] **Step 3: Route submit through `mutate()`**

Replace the body of `run()` in `submit.py` with:

```python
def run(args) -> tuple[int, dict]:
    repo_root = Path(args.repo).resolve()
    run_state.mutate(
        args.state,
        lambda state: engine.submit_evidence(
            state, args.phase, args.key, args.path,
            repo_root=repo_root,
            status=getattr(args, "status", "done"),
            reason=getattr(args, "reason", None),
        ),
    )
    return 0, {"schema": "e2e-dev-harness-v2.submit.v1", "phase": args.phase,
               "key": args.key, "recorded": args.path,
               "status": getattr(args, "status", "done")}
```

(Keep the existing imports `from harness_v2.core import run_state, engine` and `from pathlib import Path`.)

- [ ] **Step 4: Run to verify it passes deterministically**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_concurrency_v2.py skills/e2e-dev-harness/tests/test_submit.py -v`
Expected: PASS — all three reviewer keys survive every run; existing submit tests still green.

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/harness_v2/cli/commands/submit.py skills/e2e-dev-harness/tests/test_concurrency_v2.py
git commit -m "fix(harness-v2): route submit through locked mutate (parallel review safe)"
```

---

## Task 3: Route `dispatch` through `mutate()`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/harness_v2/cli/commands/dispatch.py`
- Test: `skills/e2e-dev-harness/tests/test_dispatch.py`

- [ ] **Step 1: Write the failing test (dispatch persists status under the lock)**

Append to `skills/e2e-dev-harness/tests/test_dispatch.py`:

```python
import types
from pathlib import Path
from harness_v2.core import run_state as _rs
from harness_v2.cli.commands import dispatch as _dispatch_cmd


def test_dispatch_marks_dispatched_and_leaves_no_lock(tmp_path):
    p = tmp_path / "run-state.json"
    st = _rs.new_run_state("r1", "feat", "req", tier="minimal", pipeline="minimal")
    st["current_phase"] = "CLARIFIED"
    _rs.save(p, st)
    args = types.SimpleNamespace(state=str(p), repo=str(tmp_path), runtime="claude-code")
    code, packet = _dispatch_cmd.run(args)
    assert code == 0
    saved = _rs.load(p)
    assert saved["phases"]["CLARIFIED"]["dispatch"] == "dispatched"
    assert not (tmp_path / "run-state.json.lock").exists()
```

- [ ] **Step 2: Run to verify it passes on current code but check lock cleanliness**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_dispatch.py::test_dispatch_marks_dispatched_and_leaves_no_lock -v`
Expected: PASS on dispatch status (current code already sets it), establishing the regression guard before refactor. (The value of this test is to prove behavior is preserved after Step 3.)

- [ ] **Step 3: Route the state write through `mutate()`**

Replace the body of `run()` in `dispatch.py` with (validation stays a pre-lock read; the setter re-reads `current_phase` inside the lock so it always marks the live phase):

```python
def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    spine = pipeline.spine_for_state(state)
    name = state.get("current_phase")
    phase = next((p for p in spine if p.name == name), None)
    if phase is None or not phase.worker_skill:
        return 2, {"error": f"no dispatchable worker at phase {name}"}

    def _mark_dispatched(s):
        rec = s.setdefault("phases", {}).setdefault(s.get("current_phase"), {})
        rec["dispatch"] = dispatch.DispatchStatus.DISPATCHED.value

    state = run_state.mutate(args.state, _mark_dispatched)

    extra: list[str] = []
    dom = state.get("domain")
    if dom:
        extra = [f"domain:{dom['name']} test_runner:{dom['test_runner']} "
                 f"review_profile:{dom['review_profile']}"]
    packet = dispatch.worker_packet(phase, str(args.state), extra_context=extra)
    packet["worker_descriptor"] = runtime.spawn_worker(
        packet, getattr(args, "runtime", "claude-code"))
    return 0, packet
```

(Keep existing imports: `from harness_v2.core import run_state, dispatch`, `from harness_v2 import pipeline`, `from harness_v2.adapters import runtime`.)

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_dispatch.py -v`
Expected: PASS (new test + all existing dispatch tests).

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/harness_v2/cli/commands/dispatch.py skills/e2e-dev-harness/tests/test_dispatch.py
git commit -m "fix(harness-v2): route dispatch state write through locked mutate"
```

---

## Task 4: Route `next` through `mutate()`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/harness_v2/cli/commands/next.py`
- Test: `skills/e2e-dev-harness/tests/test_dispatch.py` (reuse) or existing `next` test file

- [ ] **Step 1: Write the failing test (next advances + leaves no lock)**

Append to `skills/e2e-dev-harness/tests/test_dispatch.py`:

```python
from harness_v2.cli.commands import next as _next_cmd


def test_next_advances_and_leaves_no_lock(tmp_path):
    p = tmp_path / "run-state.json"
    st = _rs.new_run_state("r1", "feat", "req", tier="minimal", pipeline="minimal")
    _rs.save(p, st)  # current_phase == CREATED, no gates -> should advance
    args = types.SimpleNamespace(state=str(p), repo=str(tmp_path))
    code, res = _next_cmd.run(args)
    assert code == 0
    assert "navigation_map" in res
    assert not (tmp_path / "run-state.json.lock").exists()
    # _run_state_path transient key must never be persisted into the SSOT
    assert "_run_state_path" not in _rs.load(p)
```

- [ ] **Step 2: Run to verify it passes pre-refactor (regression guard)**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_dispatch.py::test_next_advances_and_leaves_no_lock -v`
Expected: PASS on current code (guards the behavior we must preserve).

- [ ] **Step 3: Route evaluate+save through `mutate()`**

Replace the body of `run()` in `next.py` with (spine is derived from the immutable pipeline/tier, so computing it from a pre-lock load is safe; `evaluate` runs on the fresh in-lock state):

```python
def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    spine = pipeline.spine_for_state(run_state.load(args.state))
    holder: dict = {}

    def _advance(state):
        state["_run_state_path"] = str(args.state)
        holder["res"] = engine.evaluate(spine, state, repo)
        state.pop("_run_state_path", None)

    state = run_state.mutate(args.state, _advance)
    res = holder["res"]
    res["navigation_map"] = navigation.navigation_map(spine, state, repo)
    res["run_state"] = str(args.state)
    return 0, res
```

(Keep existing imports: `from pathlib import Path`, `from harness_v2.core import run_state, engine, navigation`, `from harness_v2 import pipeline`.)

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest skills/e2e-dev-harness/tests/ -v`
Expected: PASS (whole v2 suite green).

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/harness_v2/cli/commands/next.py skills/e2e-dev-harness/tests/test_dispatch.py
git commit -m "fix(harness-v2): route next evaluate/save through locked mutate"
```

---

## Task 5 (OPTIONAL — requires user decision): pin `current_phase` lag semantics (Finding V2)

> **Decision gate:** Finding V2 is a *semantic* choice, not a safety bug. Today `current_phase` advances **only** on `next` (lazy); `submit` records evidence but does not advance. This is **fail-safe** (the phase guard stays restrictive until `next` runs). Do **not** implement this task until the user confirms the desired semantics:
> - **(A) Keep lazy + document (recommended, default):** no behavior change; add the pin test below so the fail-safe contract can't silently regress.
> - **(B) Eager self-heal:** make `submit` also run `engine.evaluate` so the SSOT `current_phase` is always current — this opens code-write as soon as the last gate evidence lands, *before* the coordinator runs `next`. Only choose if you want eager phase advance. (Not specified here; needs its own task.)

**Files (Option A only):**
- Modify: `skills/e2e-dev-harness/scripts/harness_v2/core/run_state.py` (docstring on `save`/module) and/or `lifecycle.py` (Phase docstring) to state: *"`current_phase` = last phase evaluated by `next`; it may lag the true gate-derived phase between a `submit` and the next `next`. Readers (e.g. phase guard) treat this as fail-safe."*
- Test: `skills/e2e-dev-harness/tests/test_concurrency_v2.py`

- [ ] **Step 1: Add the pin test**

```python
from harness_v2.cli.commands import submit as _submit_cmd


def test_submit_does_not_advance_current_phase(tmp_path):
    p = tmp_path / "run-state.json"
    st = run_state.new_run_state("r1", "feat", "req", tier="minimal", pipeline="minimal")
    st["current_phase"] = "CLARIFIED"
    run_state.save(p, st)
    evidence = tmp_path / "clar.md"
    evidence.write_text("ok", encoding="utf-8")
    args = types.SimpleNamespace(state=str(p), repo=str(tmp_path), phase="CLARIFIED",
                                 key="clarification", path=str(evidence),
                                 status="done", reason=None)
    _submit_cmd.run(args)
    # submit records evidence but MUST NOT advance the phase (lazy, fail-safe)
    assert run_state.load(p)["current_phase"] == "CLARIFIED"
```

- [ ] **Step 2: Run**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_concurrency_v2.py::test_submit_does_not_advance_current_phase -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add skills/e2e-dev-harness/scripts/harness_v2/core/run_state.py skills/e2e-dev-harness/tests/test_concurrency_v2.py
git commit -m "docs(harness-v2): pin current_phase lazy-advance fail-safe semantics"
```

---

## Out of scope (explicitly deferred)

- **Finding V4 (schema migration):** `run_state.load()` hard-fails on schema mismatch. This is correct fail-closed behavior today and there is only one schema (`...run-state.v1`). YAGNI until a `.v2` schema actually ships; revisit then with a migration hook.
- **`gate` and `start` verbs:** `gate` is read-only (no `save`); `start` is run-creation (single writer by definition). Neither participates in the concurrent-writer race, so neither is rerouted through `mutate()`.

---

## Self-Review

- **Spec coverage:** V1 (lost updates) → Tasks 1–4. V3 (shared `.tmp`) → Task 1 Step 3 (process-unique tmp). V2 (current_phase lag) → Task 5 (decision-gated). V4 → explicitly deferred. `.phase-lock` / multi-file split-brain → already eliminated in v2, no task needed. ✓
- **Type/name consistency:** `run_state.mutate(path, fn, now=None)` signature is identical across Tasks 1–4. `DispatchStatus.DISPATCHED.value == "dispatched"` matches the dispatch test assertion. `engine.submit_evidence`, `engine.evaluate`, `navigation.navigation_map`, `pipeline.spine_for_state` signatures unchanged from current source. ✓
- **No placeholders:** every code step shows full code; every run step shows command + expected result. ✓
- **Concurrency test validity:** Task 1's 20-thread test and Task 2's 3-reviewer test fail without the lock (lost keys) and pass with it (all keys survive) — they exercise the real defect, not a proxy. ✓
