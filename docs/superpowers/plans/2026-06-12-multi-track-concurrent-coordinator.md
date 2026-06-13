# Multi-Track Concurrent Coordinator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the `e2e-dev-harness` engine from a single flattened cursor into first-class multi-track concurrency, so independent modules advance on their own cursors end-to-end while `current_phase` survives as a derived back-compat projection.

**Architecture:** Fork-join over three regions — `prologue` (CREATED→…→PLANNED, single cursor, unchanged), `module_band` (one independent cursor per module, gated by `depends_on`, joined at VERIFIED), `epilogue` (VERIFIED join barrier). `evaluate` becomes region-aware; the band returns a `tracks_frontier` (the per-beat dispatch set) while still projecting a single leading cursor so every existing single-cursor reader (guards, gate, navigation) keeps working. The harness stays a pure control plane: real parallel spawn remains the coordinator's job (one turn, N `Task`/`spawn_agent` calls, await all).

**Tech Stack:** Python 3 (stdlib only, zero runtime deps), pytest. Source under `skills/e2e-dev-harness/scripts/e2e_harness/`, tests under `skills/e2e-dev-harness/tests/`.

**Source spec:** `docs/superpowers/specs/2026-06-12-multi-track-concurrent-coordinator-design.md`

---

## Project Iron Rules (apply to every code-touching task)

- **Before editing any symbol**, run `gitnexus_impact({target: "<symbol>", direction: "upstream"})` and note the blast radius. If the index warns it is stale, run `npx gitnexus analyze` first. Warn the user on HIGH/CRITICAL risk before proceeding.
- **Before committing**, run `gitnexus_detect_changes()` to confirm only the expected symbols/flows changed.
- Run the harness test suite from `skills/e2e-dev-harness/`:
  ```bash
  cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest -q
  ```
  Single test:
  ```bash
  cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/<file>::<test> -q
  ```

## Invariants that MUST stay true (assert via the green suite after every task)

1. Gates own transitions (per track, per call).
2. Workers don't self-report — evidence keys only.
3. Harness never spawns.
4. Concurrent submit serialized by `run_state.mutate`; reconciliation is order-independent.
5. Simple runs pay nothing — single-module / single-track runs are byte-for-byte unchanged.

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `scripts/e2e_harness/core/multitrack.py` | spine expansion + track ledger + projection (pure) | **add** `module_chains`, `fork_tracks`, `active_track_ids`, `project_leading_phase`, `BAND_RANK` |
| `scripts/e2e_harness/core/engine.py` | terminating advance + evidence | **refactor** `evaluate` into region dispatcher; **add** `_evaluate_singleton` (extracted), `_evaluate_band`, `_region_of`, `_module_first_blocker`, `_last_code_write`, `_route_band_verification_rework`, fork trigger |
| `scripts/e2e_harness/core/navigation.py` | derived navigation map | **add** `region` + `tracks` lanes (additive; top-level shape preserved) |
| `scripts/e2e_harness/cli/commands/dispatch.py` | emit worker descriptors + dispatch bookkeeping | **add** per-track `tracks[m].dispatch` marking when band tracks exist |
| `SKILL.md` | coordinator discipline doc | **rewrite** loop section to beat semantics |
| `scripts/e2e_harness/core/run_state.py` | SSOT JSON | **no change** — `region`/`tracks` are additive, persisted by existing `save()` |
| `scripts/e2e_harness/cli/commands/next.py` | advance + nav map | **no change** — already returns the engine result verbatim, so `tracks_frontier` flows through |
| `scripts/e2e_harness/adapters/agent_team/builtin.py` | fanout planner | **no change** — `plan_module_fanout` already fans out the frontier |

New test files: `tests/test_tracks.py`, `tests/test_engine_band.py`, `tests/test_band_dispatch.py`, `tests/test_navigation_band.py`, `tests/test_band_e2e.py`. Modified test: `tests/test_skill_md.py`.

---

## Task 1: Pure track helpers — `module_chains` + `fork_tracks`

**Files:**
- Modify: `scripts/e2e_harness/core/multitrack.py` (append after `ready_frontier`)
- Test: `tests/test_tracks.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_tracks.py`:

```python
"""First-class track ledger: fork materialization + projection (pure, no I/O)."""
from e2e_harness import pipeline
from e2e_harness.core import multitrack, module_plan


def _plan(*mods):
    return {"schema": module_plan.SCHEMA, "modules": list(mods)}


def _mod(mid, deps=()):
    return {"id": mid, "name": f"{mid} svc", "depends_on": list(deps), "acceptance_ids": ["AC-001"]}


def _expanded(*mods):
    base = pipeline.build_spine("standard")
    return multitrack.expand(base, _plan(*mods)), _plan(*mods)


def test_module_chains_groups_phases_per_module_in_spine_order():
    spine, _ = _expanded(_mod("auth"), _mod("billing", deps=["auth"]))
    chains = multitrack.module_chains(spine)
    assert list(chains) == ["auth", "billing"]
    assert [p.name for p in chains["auth"]] == ["RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth"]
    assert [p.name for p in chains["billing"]] == ["RED#billing", "IMPLEMENTED#billing", "REVIEWED#billing"]


def test_fork_tracks_materializes_one_track_per_module():
    spine, mplan = _expanded(_mod("auth"), _mod("billing", deps=["auth"]))
    tracks = multitrack.fork_tracks(spine, mplan)
    assert set(tracks) == {"auth", "billing"}
    assert tracks["auth"] == {
        "module_id": "auth", "current_phase": "RED#auth",
        "dispatch": "pending", "depends_on": [], "complete": False,
    }
    assert tracks["billing"]["depends_on"] == ["auth"]
    assert tracks["billing"]["current_phase"] == "RED#billing"


def test_fork_tracks_without_plan_falls_back_to_linear_dependencies():
    spine, _ = _expanded(_mod("auth"), _mod("billing"))
    tracks = multitrack.fork_tracks(spine, None)
    # plan-less band serializes (matches the legacy flattened walk)
    assert tracks["auth"]["depends_on"] == []
    assert tracks["billing"]["depends_on"] == ["auth"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_tracks.py -q`
Expected: FAIL with `AttributeError: module 'e2e_harness.core.multitrack' has no attribute 'module_chains'`

- [ ] **Step 3: Run impact analysis, then implement**

Run `gitnexus_impact({target: "multitrack", direction: "upstream"})` and note callers (expect `pipeline`, `engine`, `dispatch`).

Append to `scripts/e2e_harness/core/multitrack.py`:

```python
# --- First-class tracks (方案 B): ledger materialization + projection ----------
# These are pure: (spine, plan) -> data. The engine fills cursors from evidence;
# these helpers never touch the repo.

BAND_RANK = {"RED": 0, "IMPLEMENTED": 1, "REVIEWED": 2}


def module_chains(spine: list[Phase]) -> dict[str, list[Phase]]:
    """mid -> its ordered sub-spine of module-scoped phases, in spine (topo) order.
    Non-module (singleton) phases are ignored."""
    chains: dict[str, list[Phase]] = {}
    order: list[str] = []
    for phase in spine:
        mid = module_of(phase.name)
        if mid is None:
            continue
        if mid not in chains:
            chains[mid] = []
            order.append(mid)
        chains[mid].append(phase)
    return {mid: chains[mid] for mid in order}


def fork_tracks(spine: list[Phase], mplan: dict | None = None) -> dict:
    """Materialize the per-module track ledger at fork time. Each track carries
    its module id, its first phase as the initial cursor, a 'pending' dispatch,
    its declared depends_on, and complete=False. Track order follows the expanded
    spine (already topological).

    `mplan` supplies the real depends_on edges. When it is absent the band
    serializes (module i depends on module i-1), reproducing the legacy flattened
    walk so plan-less callers are unchanged.
    """
    chains = module_chains(spine)
    mids = list(chains)
    if mplan is not None:
        deps = {m["id"]: list(m.get("depends_on", []))
                for m in mplan.get("modules", []) if isinstance(m, dict) and "id" in m}
    else:
        deps = {mid: ([mids[i - 1]] if i > 0 else []) for i, mid in enumerate(mids)}
    tracks: dict = {}
    for mid in mids:
        tracks[mid] = {
            "module_id": mid,
            "current_phase": chains[mid][0].name,
            "dispatch": "pending",
            "depends_on": deps.get(mid, []),
            "complete": False,
        }
    return tracks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_tracks.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Run full suite (no regression) and commit**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest -q`
Expected: all pass. Then `gitnexus_detect_changes()` to confirm only `multitrack` changed.

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/multitrack.py skills/e2e-dev-harness/tests/test_tracks.py
git commit -m "feat(harness): materialize per-module track ledger (fork_tracks)"
```

---

## Task 2: Pure track helpers — `active_track_ids` + `project_leading_phase`

**Files:**
- Modify: `scripts/e2e_harness/core/multitrack.py` (append after `fork_tracks`)
- Test: `tests/test_tracks.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracks.py`:

```python
def _tracks(**by_mid):
    """Build a tracks dict from {mid: (current_phase, complete, depends_on)}."""
    out = {}
    for mid, (cur, complete, deps) in by_mid.items():
        out[mid] = {"module_id": mid, "current_phase": cur, "dispatch": "pending",
                    "depends_on": list(deps), "complete": complete}
    return out


def test_active_track_ids_excludes_complete_and_dep_blocked():
    tracks = _tracks(
        auth=("RED#auth", False, []),
        reports=("RED#reports", False, []),
        billing=("RED#billing", False, ["auth"]),
    )
    assert multitrack.active_track_ids(tracks) == ["auth", "reports"]


def test_active_track_ids_unblocks_dependent_when_dependency_complete():
    tracks = _tracks(
        auth=("REVIEWED#auth", True, []),
        billing=("RED#billing", False, ["auth"]),
    )
    assert multitrack.active_track_ids(tracks) == ["billing"]


def test_project_leading_phase_picks_least_advanced_active_track():
    tracks = _tracks(
        auth=("IMPLEMENTED#auth", False, []),   # rank 1
        reports=("RED#reports", False, []),      # rank 0 -> leads
    )
    assert multitrack.project_leading_phase(tracks, "module_band", None) == "RED#reports"


def test_project_leading_phase_tie_breaks_by_track_order():
    tracks = _tracks(
        auth=("RED#auth", False, []),
        reports=("RED#reports", False, []),
    )
    assert multitrack.project_leading_phase(tracks, "module_band", None) == "RED#auth"


def test_project_leading_phase_returns_singleton_outside_band():
    assert multitrack.project_leading_phase({}, "prologue", "PLANNED") == "PLANNED"
    assert multitrack.project_leading_phase({}, "epilogue", "VERIFIED") == "VERIFIED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_tracks.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'active_track_ids'`

- [ ] **Step 3: Implement**

Append to `scripts/e2e_harness/core/multitrack.py`:

```python
def active_track_ids(tracks: dict) -> list[str]:
    """Track ids that may run now: not complete and every depends_on track
    complete. Preserves the tracks-dict (topological) order."""
    done = {mid for mid, t in tracks.items() if t.get("complete")}
    out: list[str] = []
    for mid, t in tracks.items():
        if t.get("complete"):
            continue
        if all(dep in done for dep in t.get("depends_on", [])):
            out.append(mid)
    return out


def project_leading_phase(tracks: dict, region: str, singleton_phase: str | None) -> str | None:
    """Derived `current_phase` (the back-compat 'leading cursor').

    prologue/epilogue -> the singleton phase name. module_band -> the namespaced
    cursor of the least-advanced *active* track (fewest phases passed); ties broken
    by track (topological) order. When no track is active but some are incomplete,
    the least-advanced incomplete track leads. Deterministic — pure function of the
    ledger.
    """
    if region != "module_band":
        return singleton_phase
    pool = active_track_ids(tracks) or [mid for mid, t in tracks.items() if not t.get("complete")]
    if not pool:
        return singleton_phase
    order = list(tracks)

    def _key(mid: str):
        rank = BAND_RANK.get(base_phase_name(tracks[mid]["current_phase"]), 99)
        return (rank, order.index(mid))

    return tracks[min(pool, key=_key)]["current_phase"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_tracks.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/multitrack.py skills/e2e-dev-harness/tests/test_tracks.py
git commit -m "feat(harness): active-track selection + leading-cursor projection"
```

---

## Task 3: Engine refactor — extract `_evaluate_singleton`, add `_region_of` dispatcher (behavior-preserving)

This task introduces the region dispatcher with **zero observable change**: `region` defaults to `prologue`, which runs today's exact `evaluate` body (now named `_evaluate_singleton`). The `module_band`/`epilogue` branches and the fork trigger are added in Task 4.

**Files:**
- Modify: `scripts/e2e_harness/core/engine.py:113-143` (the `evaluate` function)
- Test: `tests/test_engine_band.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_band.py`:

```python
"""Region-aware engine: dispatcher + per-track band advance."""
from e2e_harness import pipeline
from e2e_harness.core import engine, run_state


def test_region_of_defaults_to_prologue():
    st = run_state.new_run_state("r1", "f", "r")
    assert engine._region_of(st) == "prologue"


def test_region_of_reads_explicit_region():
    st = run_state.new_run_state("r1", "f", "r")
    st["region"] = "module_band"
    assert engine._region_of(st) == "module_band"


def test_prologue_evaluate_is_unchanged_for_single_track():
    spine = pipeline.build_spine("minimal")
    st = run_state.new_run_state("r1", "f", "r")
    res = engine.evaluate(spine, st)
    assert st["current_phase"] == "CLARIFIED"
    assert res["blocked_phase"] == "CLARIFIED"
    assert res["complete"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_engine_band.py -q`
Expected: FAIL with `AttributeError: module 'e2e_harness.core.engine' has no attribute '_region_of'`

- [ ] **Step 3: Implement the refactor**

In `scripts/e2e_harness/core/engine.py`, add the `multitrack` import at the top (after the existing imports on line 6-8):

```python
from e2e_harness.core import gates, dispatch, multitrack
```
(Replace the existing `from e2e_harness.core import gates, dispatch` line.)

Replace the entire `evaluate` function body (lines 113-143) with the dispatcher + extracted singleton:

```python
def _region_of(state: dict) -> str:
    """Current fork-join region. Defaults to 'prologue' so legacy/single-track
    runs (which never set `region`) behave exactly as before."""
    return state.get("region", "prologue")


def evaluate(spine: list[Phase], state: dict, repo_root=None) -> dict:
    """Region-aware terminating advance. prologue/epilogue use the single-cursor
    walk; module_band advances each independent track to its own blocker. Each
    pass advances >=0 phases along a finite spine then blocks or completes."""
    region = _region_of(state)
    if region == "module_band":
        return _evaluate_band(spine, state, repo_root)
    return _evaluate_singleton(spine, state, repo_root)


def _evaluate_singleton(spine: list[Phase], state: dict, repo_root=None) -> dict:
    """Single-cursor walk: advance current_phase past every gate that already
    passes; stop at first blocker or terminal. Used for prologue and epilogue."""
    by_name = _by_name(spine)
    name = state.get("current_phase", spine[0].name)
    while True:
        phase = by_name[name]
        rec = state.get("phases", {}).get(name, {})
        ok, missing = gates.gate_passes(phase, rec, repo_root)
        if not ok:
            if _verification_rework_needed(phase, rec, missing):
                reason = rec.get("blocker") or f"verification gate failed: {', '.join(missing)}"
                routed = _route_verification_rework(spine, state, phase, missing, reason)
                if routed is not None:
                    return routed
            state["current_phase"] = name
            result = {
                "complete": False,
                "blocked_phase": name,
                "missing_evidence": missing,
                "next_action": dispatch.worker_packet(phase, state.get("_run_state_path", "")),
            }
            if rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
                result["failed"] = True
                result["blocker"] = rec.get("blocker")
            return result
        if phase.next_phase is None:
            state["current_phase"] = name
            return {"complete": True, "blocked_phase": None, "missing_evidence": [], "next_action": {}}
        name = phase.next_phase
```

Add a temporary stub for `_evaluate_band` at the end of the file so the dispatcher import-resolves (replaced fully in Task 4):

```python
def _evaluate_band(spine: list[Phase], state: dict, repo_root=None) -> dict:
    # Replaced in Task 4 with the real per-track advance. Unreachable until the
    # fork trigger sets region == "module_band".
    return _evaluate_singleton(spine, state, repo_root)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_engine_band.py tests/test_engine_termination.py tests/test_dispatch_failure.py tests/test_multitrack_e2e.py -q`
Expected: PASS (all). The full suite must also be green:
Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest -q`
Expected: all pass — this proves the refactor is behavior-preserving.

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/engine.py skills/e2e-dev-harness/tests/test_engine_band.py
git commit -m "refactor(harness): region-aware evaluate dispatcher (no behavior change)"
```

---

## Task 4: Engine — real `_evaluate_band` + fork trigger + join

**Files:**
- Modify: `scripts/e2e_harness/core/engine.py` (replace the `_evaluate_band` stub; add fork trigger inside `_evaluate_singleton`; add helpers)
- Test: `tests/test_engine_band.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine_band.py`:

```python
import json

from e2e_harness.core import module_plan, multitrack
from e2e_harness.adapters.evidence import command_evidence


def _mod(mid, deps=()):
    return {"id": mid, "name": f"{mid} svc", "depends_on": list(deps), "acceptance_ids": ["AC-001"]}


def _write_plan(repo, *mods):
    p = repo / "mp.json"
    p.write_text(json.dumps({"schema": module_plan.SCHEMA, "modules": list(mods)}), encoding="utf-8")
    return p


def _planned_state(repo, *mods):
    """State sitting at PLANNED with a valid >=2-module plan, ready to fork."""
    _write_plan(repo, *mods)
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    st["current_phase"] = "PLANNED"
    st["phases"] = {
        "CLARIFIED": {"evidence": {"clarification": {"path": "c"}, "acceptance_contract": {"path": "a"}}},
        "PLANNED": {"evidence": {"plan": {"path": "p"}, "module_plan": {"path": "mp.json"}}},
    }
    return st


def _failing(repo, mid):
    """Real failing-tests command evidence file for RED#<mid>."""
    art = repo / "art"; art.mkdir(exist_ok=True)
    ev = command_evidence.record_command(art, 'python -c "import sys; sys.exit(1)"')
    p = art / f"failing_{mid}.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    return str(p.relative_to(repo))


def test_passing_planned_forks_into_band(tmp_path):
    st = _planned_state(tmp_path, _mod("auth"), _mod("reports"))
    res = engine.evaluate(pipeline.spine_for_state(st, tmp_path), st, tmp_path)
    assert st["region"] == "module_band"
    assert set(st["tracks"]) == {"auth", "reports"}
    assert res["region"] == "module_band"


def test_band_frontier_holds_all_independent_tracks(tmp_path):
    st = _planned_state(tmp_path, _mod("auth"), _mod("reports"))
    res = engine.evaluate(pipeline.spine_for_state(st, tmp_path), st, tmp_path)
    blocked = sorted(e["blocked_phase"] for e in res["tracks_frontier"])
    assert blocked == ["RED#auth", "RED#reports"]
    # leading-cursor projection picks the topo-first track
    assert res["blocked_phase"] == "RED#auth"


def test_band_dependent_track_absent_from_frontier(tmp_path):
    st = _planned_state(tmp_path, _mod("auth"), _mod("billing", deps=["auth"]))
    res = engine.evaluate(pipeline.spine_for_state(st, tmp_path), st, tmp_path)
    blocked = [e["blocked_phase"] for e in res["tracks_frontier"]]
    assert blocked == ["RED#auth"]  # billing gated by depends_on


def test_band_tracks_advance_independently(tmp_path):
    st = _planned_state(tmp_path, _mod("auth"), _mod("reports"))
    spine = pipeline.spine_for_state(st, tmp_path)
    engine.evaluate(spine, st, tmp_path)              # fork -> frontier RED#auth, RED#reports
    # only auth submits its failing tests this beat
    engine.submit_evidence(st, "RED#auth", "failing_tests#auth", _failing(tmp_path, "auth"), repo_root=tmp_path)
    res = engine.evaluate(spine, st, tmp_path)
    frontier = {e["track"]: e["blocked_phase"] for e in res["tracks_frontier"]}
    assert frontier["auth"] == "IMPLEMENTED#auth"     # auth advanced
    assert frontier["reports"] == "RED#reports"       # reports unchanged -> not blocked by auth


def test_band_joins_to_verified_when_all_tracks_complete(tmp_path):
    st = _planned_state(tmp_path, _mod("auth"), _mod("reports"))
    spine = pipeline.spine_for_state(st, tmp_path)
    engine.evaluate(spine, st, tmp_path)
    # mark every module phase satisfied directly (gate uses presence when repo_root
    # validation is bypassed by structural keys; here use the evidence-mark helper)
    by = {p.name: p for p in spine}
    for name in ("RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth",
                 "RED#reports", "IMPLEMENTED#reports", "REVIEWED#reports"):
        st.setdefault("phases", {})[name] = {"evidence": {k: {"path": "x"} for k in by[name].exit_gate}}
    res = engine.evaluate(spine, st, None)   # repo_root=None -> presence-only gate
    assert st["region"] == "epilogue"
    assert st["current_phase"] == "VERIFIED"
    assert res["blocked_phase"] == "VERIFIED"
```

> Note: `test_band_joins_to_verified_when_all_tracks_complete` calls `evaluate` with `repo_root=None` for the join step so gates pass on evidence *presence* (no artifact validation), isolating the join logic.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_engine_band.py -q`
Expected: FAIL (band frontier not produced; region stays prologue).

- [ ] **Step 3: Run impact analysis, then implement**

Run `gitnexus_impact({target: "evaluate", direction: "upstream"})` — expect callers in `cli/commands/next.py`, `submit`, tests. Confirm no other hidden caller relies on the exact band return shape (single-track path is unchanged).

In `scripts/e2e_harness/core/engine.py`, add the fork trigger inside `_evaluate_singleton`. Replace the loop's tail:

```python
        if phase.next_phase is None:
            state["current_phase"] = name
            return {"complete": True, "blocked_phase": None, "missing_evidence": [], "next_action": {}}
        name = phase.next_phase
```

with:

```python
        if phase.next_phase is None:
            state["current_phase"] = name
            return {"complete": True, "blocked_phase": None, "missing_evidence": [], "next_action": {}}
        nxt = phase.next_phase
        # Fork point: stepping from a singleton phase (e.g. PLANNED) into the
        # module band (a namespaced phase). Materialize tracks once and hand off.
        if multitrack.module_of(nxt) is not None and multitrack.module_of(name) is None:
            state["region"] = "module_band"
            state["tracks"] = multitrack.fork_tracks(spine, _band_module_plan(state, repo_root))
            return _evaluate_band(spine, state, repo_root)
        name = nxt
```

Replace the `_evaluate_band` stub with the real implementation, and add the helpers, at the end of the file:

```python
def _band_module_plan(state: dict, repo_root) -> dict | None:
    """Resolve the run's module plan (for real depends_on edges) without creating
    an import cycle at module load. None -> fork_tracks falls back to linear deps."""
    if repo_root is None:
        return None
    from e2e_harness import pipeline  # local import: pipeline imports multitrack/yaml, not engine
    return pipeline._module_plan_from_state(state, repo_root)


def _module_first_blocker(chain: list[Phase], state: dict, repo_root):
    """First phase in a module chain whose gate does not pass, with its missing
    keys. (None, []) when the whole chain passes (the module is complete)."""
    for phase in chain:
        rec = state.get("phases", {}).get(phase.name, {})
        ok, missing = gates.gate_passes(phase, rec, repo_root)
        if not ok:
            return phase, missing
    return None, []


def _evaluate_band(spine: list[Phase], state: dict, repo_root=None) -> dict:
    """Advance every active track to its own first blocker; surface the whole
    frontier (the per-beat dispatch set) plus a single leading-cursor projection
    for back-compat. Joins to epilogue/VERIFIED when all tracks complete."""
    tracks = state.setdefault("tracks", {})
    chains = multitrack.module_chains(spine)
    # Refresh each track's cursor + complete flag from evidence/gates (the cursor
    # is derived; only dispatch state is genuinely stored per track).
    for mid, chain in chains.items():
        track = tracks.setdefault(mid, {
            "module_id": mid, "current_phase": chain[0].name,
            "dispatch": "pending", "depends_on": [], "complete": False,
        })
        blocker, _missing = _module_first_blocker(chain, state, repo_root)
        if blocker is None:
            track["complete"] = True
            track["current_phase"] = chain[-1].name
        else:
            track["complete"] = False
            track["current_phase"] = blocker.name

    # Join barrier: all tracks complete -> epilogue, then run the VERIFIED gate.
    if tracks and all(t["complete"] for t in tracks.values()):
        state["region"] = "epilogue"
        state["current_phase"] = "VERIFIED"
        return _evaluate_singleton(spine, state, repo_root)

    rsp = state.get("_run_state_path", "")
    frontier: list[dict] = []
    for mid in multitrack.active_track_ids(tracks):
        blocker, missing = _module_first_blocker(chains[mid], state, repo_root)
        rec = state.get("phases", {}).get(blocker.name, {})
        entry = {
            "track": mid,
            "blocked_phase": blocker.name,
            "missing": missing,
            "worker_packet": dispatch.worker_packet(blocker, rsp),
        }
        if rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
            entry["failed"] = True
            entry["blocker"] = rec.get("blocker")
        frontier.append(entry)

    lead = multitrack.project_leading_phase(tracks, "module_band", None)
    state["current_phase"] = lead
    lead_entry = next((e for e in frontier if e["blocked_phase"] == lead),
                      frontier[0] if frontier else None)
    result = {
        "complete": False,
        "region": "module_band",
        "tracks_frontier": frontier,
        "blocked_phase": lead,
        "missing_evidence": lead_entry["missing"] if lead_entry else [],
        "next_action": lead_entry["worker_packet"] if lead_entry else {},
    }
    if lead_entry and lead_entry.get("failed"):
        result["failed"] = True
        result["blocker"] = lead_entry.get("blocker")
    return result
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_engine_band.py -q`
Expected: PASS (all band tests).
Then the full suite, especially the legacy multi-track e2e:
Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_multitrack_e2e.py tests/test_multitrack.py tests/test_module_fanout_dispatch.py -q`
Expected: PASS — `test_two_module_run_walks_each_module_lifecycle_then_reaches_verified` stays green via the projection.
Run full suite:
Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/engine.py skills/e2e-dev-harness/tests/test_engine_band.py
git commit -m "feat(harness): per-track band advance with fork + join barrier"
```

---

## Task 5: Engine — band-aware verification rework (per-track reopen)

**Files:**
- Modify: `scripts/e2e_harness/core/engine.py` (branch `_verification_rework_needed` handling on tracks; add `_route_band_verification_rework`, `_last_code_write`)
- Test: `tests/test_engine_band.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine_band.py`:

```python
from e2e_harness.core import dispatch as dispatch_core


def _completed_band_state(tmp_path, *mods):
    """A band state whose tracks are all complete and sitting at the VERIFIED
    join, with a *failing* verification artifact (command exits 1)."""
    st = _planned_state(tmp_path, *mods)
    spine = pipeline.spine_for_state(st, tmp_path)
    engine.evaluate(spine, st, tmp_path)  # fork
    by = {p.name: p for p in spine}
    for mid in (m["id"] for m in mods):
        for base in ("RED", "IMPLEMENTED", "REVIEWED"):
            name = f"{base}#{mid}"
            st["phases"][name] = {"evidence": {k: {"path": "x"} for k in by[name].exit_gate},
                                  "dispatch": dispatch_core.DispatchStatus.DONE.value}
    return st, spine


def test_band_verification_failure_reopens_implementation_tracks(tmp_path):
    st, spine = _completed_band_state(tmp_path, _mod("auth"), _mod("reports"))
    # join to epilogue with a FAILED verification (presence-only gate, but the
    # phase dispatch is marked failed to trigger verification rework)
    st["phases"]["VERIFIED"] = {
        "evidence": {"verification": {"path": "v"}, "scope_manifest": {"path": "s"}},
        "dispatch": dispatch_core.DispatchStatus.FAILED.value,
        "blocker": "verification command exited 1",
    }
    st["region"] = "epilogue"
    st["current_phase"] = "VERIFIED"
    res = engine.evaluate(spine, st, None)
    assert res["rework_required"] is True
    assert st["region"] == "module_band"
    # not attributable (VERIFIED keys are un-namespaced) -> reopen all tracks
    assert st["tracks"]["auth"]["complete"] is False
    assert st["tracks"]["reports"]["complete"] is False
    assert st["phases"]["IMPLEMENTED#auth"]["evidence"] == {}
    assert st["phases"]["IMPLEMENTED#auth"]["dispatch"] == dispatch_core.DispatchStatus.FAILED.value
    assert set(st["phases"]["IMPLEMENTED#auth"]["superseded_evidence"]) == \
        {"passing_tests#auth", "test_substance#auth"}


def test_single_track_verification_rework_is_unchanged(tmp_path):
    # guards the back-compat path: no tracks -> legacy _route_verification_rework
    from e2e_harness.adapters.evidence import command_evidence as ce
    spine = pipeline.build_spine("minimal")
    st = run_state.new_run_state("r1", "f", "r")
    st["current_phase"] = "VERIFIED"
    st["phases"]["IMPLEMENTED"] = {
        "dispatch": dispatch_core.DispatchStatus.DONE.value,
        "evidence": {"passing_tests": {"path": "old.json"}, "test_substance": {"path": "old.json"}},
    }
    ev = ce.record_command(tmp_path, 'python -c "import sys; sys.exit(1)"')
    v = tmp_path / "v.json"; v.write_text(json.dumps(ev), encoding="utf-8")
    s = tmp_path / "s.json"
    s.write_text(json.dumps({"schema": "e2e-dev-harness.scope-manifest.v1", "status": "COMPLETE",
                             "expected": {"services": [], "tables": [], "phases": []},
                             "delivered": {"services": [], "tables": [], "phases": []}}), encoding="utf-8")
    engine.submit_evidence(st, "VERIFIED", "verification", str(v), repo_root=tmp_path)
    engine.submit_evidence(st, "VERIFIED", "scope_manifest", str(s), repo_root=tmp_path)
    res = engine.evaluate(spine, st, tmp_path)
    assert res["rework_required"] is True
    assert res["blocked_phase"] == "IMPLEMENTED"   # single-chain target, unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_engine_band.py -k verification -q`
Expected: FAIL (band reopen not implemented; first test errors on missing `rework_required`).

- [ ] **Step 3: Implement**

In `scripts/e2e_harness/core/engine.py`, inside `_evaluate_singleton`, replace the verification-rework branch:

```python
            if _verification_rework_needed(phase, rec, missing):
                reason = rec.get("blocker") or f"verification gate failed: {', '.join(missing)}"
                routed = _route_verification_rework(spine, state, phase, missing, reason)
                if routed is not None:
                    return routed
```

with a tracks-aware dispatch:

```python
            if _verification_rework_needed(phase, rec, missing):
                reason = rec.get("blocker") or f"verification gate failed: {', '.join(missing)}"
                if state.get("tracks"):
                    routed = _route_band_verification_rework(spine, state, missing, reason, repo_root)
                else:
                    routed = _route_verification_rework(spine, state, phase, missing, reason)
                if routed is not None:
                    return routed
```

Add the helpers at the end of the file:

```python
def _last_code_write(chain: list[Phase]) -> Phase | None:
    """The rework target inside a module chain — the last phase that may write
    code (IMPLEMENTED#m). None when the chain has no code-write phase."""
    for phase in reversed(chain):
        if phase.allows_code_write:
            return phase
    return None


def _route_band_verification_rework(spine: list[Phase], state: dict, missing: list[str],
                                    reason: str, repo_root) -> dict | None:
    """Verification rework for a multi-track run (design §Per-Track Rework, v1).

    Attributable (a missing key carries a #module suffix) -> reopen only those
    modules; otherwise reopen every track conservatively. Reopening a track resets
    its IMPLEMENTED#m phase (supersede + clear evidence, mark failed) and flips the
    run back to module_band so the band re-drives the affected implementations.
    """
    chains = multitrack.module_chains(spine)
    tracks = state.get("tracks", {})
    attributed = sorted({multitrack.module_of(k) for k in missing
                         if multitrack.module_of(k) is not None})
    targets = attributed or list(tracks)
    reopened: list[str] = []
    for mid in targets:
        target = _last_code_write(chains.get(mid, []))
        if target is None:
            continue
        target_rec = _phase_record(state, target.name)
        existing = target_rec.get("evidence", {})
        if existing:
            target_rec["superseded_evidence"] = dict(existing)
        target_rec["evidence"] = {}
        target_rec["dispatch"] = dispatch.DispatchStatus.FAILED.value
        target_rec["blocker"] = reason
        target_rec["rework_required"] = {
            "from_phase": "VERIFIED",
            "missing_evidence": list(missing),
            "reason": reason,
        }
        tracks[mid]["complete"] = False
        tracks[mid]["dispatch"] = dispatch.DispatchStatus.PENDING.value
        tracks[mid]["current_phase"] = target.name
        reopened.append(mid)
    if not reopened:
        return None
    state["region"] = "module_band"
    result = _evaluate_band(spine, state, repo_root)
    result["rework_required"] = True
    result["rework_from_phase"] = "VERIFIED"
    result["verification_missing_evidence"] = list(missing)
    result["reopened_tracks"] = reopened
    result["blocker"] = reason
    return result
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_engine_band.py tests/test_dispatch_failure.py -q`
Expected: PASS (band reopen + unchanged single-track rework).
Run full suite:
Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/engine.py skills/e2e-dev-harness/tests/test_engine_band.py
git commit -m "feat(harness): band-aware verification rework (per-track reopen)"
```

---

## Task 6: Dispatch — per-track dispatch bookkeeping in the band

**Files:**
- Modify: `scripts/e2e_harness/cli/commands/dispatch.py:139-143` (the `_mark_dispatched` closure)
- Test: `tests/test_band_dispatch.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_band_dispatch.py`:

```python
"""Band dispatch marks each frontier track's ledger entry (not just current_phase)."""
import json
import types

from e2e_harness.cli.commands import dispatch as dispatch_cmd
from e2e_harness.core import run_state, module_plan


def _args(state_path, repo):
    return types.SimpleNamespace(state=str(state_path), repo=str(repo),
                                 runtime="codex", team_profile=None, max_workers=None)


def _mod(mid, deps=()):
    return {"id": mid, "name": f"{mid} svc", "depends_on": list(deps), "acceptance_ids": ["AC-001"]}


def _band_state(repo, *mods):
    (repo / "mp.json").write_text(
        json.dumps({"schema": module_plan.SCHEMA, "modules": list(mods)}), encoding="utf-8")
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    st["region"] = "module_band"
    st["current_phase"] = "RED#auth"
    st["tracks"] = {
        "auth": {"module_id": "auth", "current_phase": "RED#auth", "dispatch": "pending",
                 "depends_on": [], "complete": False},
        "reports": {"module_id": "reports", "current_phase": "RED#reports", "dispatch": "pending",
                    "depends_on": [], "complete": False},
    }
    st["phases"] = {"PLANNED": {"evidence": {"module_plan": {"path": "mp.json"}}}}
    sp = repo / "docs" / "agent-runs" / "r1" / "run-state.json"
    sp.parent.mkdir(parents=True)
    sp.write_text(json.dumps(st), encoding="utf-8")
    return sp


def test_band_dispatch_marks_every_frontier_track(tmp_path):
    sp = _band_state(tmp_path, _mod("auth"), _mod("reports"))
    code, result = dispatch_cmd.run(_args(sp, tmp_path))
    assert code == 0
    assert result["agent_team_plan"]["execution_model"] == "module-fanout"
    saved = run_state.load(sp)
    assert saved["tracks"]["auth"]["dispatch"] == "dispatched"
    assert saved["tracks"]["reports"]["dispatch"] == "dispatched"


def test_non_band_dispatch_keeps_legacy_marking(tmp_path):
    # no tracks/region -> the legacy current_phase dispatch marking, unchanged
    (tmp_path / "mp.json").write_text(
        json.dumps({"schema": module_plan.SCHEMA, "modules": [_mod("auth"), _mod("billing", deps=["auth"])]}),
        encoding="utf-8")
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    st["current_phase"] = "RED#auth"
    st["phases"] = {"PLANNED": {"evidence": {"module_plan": {"path": "mp.json"}}}}
    sp = tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json"
    sp.parent.mkdir(parents=True)
    sp.write_text(json.dumps(st), encoding="utf-8")
    code, _ = dispatch_cmd.run(_args(sp, tmp_path))
    assert code == 0
    saved = run_state.load(sp)
    assert saved["phases"]["RED#auth"]["dispatch"] == "dispatched"
    assert "tracks" not in saved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_band_dispatch.py -q`
Expected: FAIL — `saved["tracks"]["auth"]["dispatch"]` is still `"pending"`.

- [ ] **Step 3: Run impact analysis, then implement**

Run `gitnexus_impact({target: "run", direction: "upstream"})` scoped to `cli/commands/dispatch.py` (or inspect callers manually — only `cli/main.py` dispatches the verb).

In `scripts/e2e_harness/cli/commands/dispatch.py`, replace the `_mark_dispatched` closure and its call (lines 139-143):

```python
    def _mark_dispatched(s):
        rec = s.setdefault("phases", {}).setdefault(s.get("current_phase"), {})
        rec["dispatch"] = dispatch.DispatchStatus.DISPATCHED.value

    run_state.mutate(args.state, _mark_dispatched)
    return 0, packet
```

with band-aware marking:

```python
    dispatched = dispatch.DispatchStatus.DISPATCHED.value
    frontier_phase_names = [w["id"] for w in team_plan["workers"]]

    def _mark_dispatched(s):
        tracks = s.get("tracks")
        if tracks and s.get("region") == "module_band":
            # Per-track bookkeeping: every frontier worker maps to one track via
            # its module-namespaced phase id. Mark each track AND its phase record.
            for phase_name in frontier_phase_names:
                mid = multitrack.module_of(phase_name)
                if mid in tracks:
                    tracks[mid]["dispatch"] = dispatched
                s.setdefault("phases", {}).setdefault(phase_name, {})["dispatch"] = dispatched
        else:
            rec = s.setdefault("phases", {}).setdefault(s.get("current_phase"), {})
            rec["dispatch"] = dispatched

    run_state.mutate(args.state, _mark_dispatched)
    return 0, packet
```

(`multitrack` is already imported at the top of `dispatch.py`.)

- [ ] **Step 4: Run tests to verify pass**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_band_dispatch.py tests/test_module_fanout_dispatch.py tests/test_dispatch.py -q`
Expected: PASS (band marking + legacy fanout/dispatch unchanged).
Run full suite:
Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py skills/e2e-dev-harness/tests/test_band_dispatch.py
git commit -m "feat(harness): per-track dispatch bookkeeping in the module band"
```

---

## Task 7: Navigation map — `region` + per-track lanes (additive)

**Files:**
- Modify: `scripts/e2e_harness/core/navigation.py:29-72` (the `navigation_map` return)
- Test: `tests/test_navigation_band.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_navigation_band.py`:

```python
"""Navigation map gains region + per-track lanes; top-level shape preserved."""
import json

from e2e_harness import pipeline
from e2e_harness.core import navigation, run_state, engine, module_plan


def _mod(mid, deps=()):
    return {"id": mid, "name": f"{mid} svc", "depends_on": list(deps), "acceptance_ids": ["AC-001"]}


def _band_state(tmp_path, *mods):
    (tmp_path / "mp.json").write_text(
        json.dumps({"schema": module_plan.SCHEMA, "modules": list(mods)}), encoding="utf-8")
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    st["current_phase"] = "PLANNED"
    st["phases"] = {
        "CLARIFIED": {"evidence": {"clarification": {"path": "c"}, "acceptance_contract": {"path": "a"}}},
        "PLANNED": {"evidence": {"plan": {"path": "p"}, "module_plan": {"path": "mp.json"}}},
    }
    spine = pipeline.spine_for_state(st, tmp_path)
    engine.evaluate(spine, st, tmp_path)  # fork into band
    return st, spine


def test_navigation_includes_region_and_track_lanes(tmp_path):
    st, spine = _band_state(tmp_path, _mod("auth"), _mod("billing", deps=["auth"]))
    m = navigation.navigation_map(spine, st, tmp_path)
    assert m["region"] == "module_band"
    lanes = {lane["module_id"]: lane for lane in m["tracks"]}
    assert set(lanes) == {"auth", "billing"}
    assert lanes["auth"]["progress"].endswith("/3")
    assert lanes["billing"]["blocked_by_deps"] == ["auth"]
    assert [p["name"] for p in lanes["auth"]["phases"]] == \
        ["RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth"]


def test_navigation_top_level_shape_preserved_for_single_track(tmp_path):
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(pipeline.build_spine("minimal"), st)
    m = navigation.navigation_map(pipeline.build_spine("minimal"), st)
    assert m["region"] == "prologue"
    assert m["tracks"] == []          # additive, empty outside a band
    assert m["schema"] == "e2e-dev-harness.navigation-map.v1"
    assert "you_are_here" in m and "phases" in m and "progress" in m and "next" in m
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_navigation_band.py -q`
Expected: FAIL — `KeyError: 'region'`.

- [ ] **Step 3: Implement**

In `scripts/e2e_harness/core/navigation.py`, add a `multitrack` import (line 4 area):

```python
from e2e_harness.core import gates, dispatch, multitrack
```

Add a lane builder before `navigation_map`:

```python
def _track_lanes(spine: list[Phase], state: dict, repo_root, *, skip_replay: bool) -> list[dict]:
    """One lane per track: its module phases (status + gate), progress, dispatch,
    and which depends_on tracks still block it. Empty outside a module band."""
    tracks = state.get("tracks")
    if not tracks:
        return []
    chains = multitrack.module_chains(spine)
    done = {mid for mid, t in tracks.items() if t.get("complete")}
    lanes: list[dict] = []
    for mid, track in tracks.items():
        chain = chains.get(mid, [])
        lane_phases = []
        passed = 0
        for phase in chain:
            rec = state.get("phases", {}).get(phase.name, {})
            ok, missing = gates.gate_passes(phase, rec, repo_root, skip_replay=skip_replay)
            if ok:
                passed += 1
                status = "done"
            elif rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
                status = "blocked"
            elif phase.name == track.get("current_phase"):
                status = "current"
            else:
                status = "pending"
            lane_phases.append({
                "name": phase.name, "status": status,
                "gate": {"required": len(phase.exit_gate), "missing": missing, "ok": ok},
            })
        lanes.append({
            "module_id": mid,
            "phases": lane_phases,
            "progress": f"{passed}/{len(chain)}",
            "dispatch": track.get("dispatch", "pending"),
            "blocked_by_deps": [d for d in track.get("depends_on", []) if d not in done],
        })
    return lanes
```

In `navigation_map`, change the return dict to add the two additive fields (insert `region` and `tracks` into the existing returned mapping):

```python
    return {
        "schema": "e2e-dev-harness.navigation-map.v1",
        "goal": GOAL,
        "region": state.get("region", "prologue"),
        "you_are_here": cur,
        "tracks": _track_lanes(spine, state, repo_root, skip_replay=skip_replay),
        "phases": phases,
        "full_catalog": full,
        "progress": f"{done}/{len(spine)}",
        "remaining_gates": remaining_gates,
        "next": nxt,
    }
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_navigation_band.py tests/test_navigation.py -q`
Expected: PASS (new lanes + legacy nav tests).
Run full suite:
Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/navigation.py skills/e2e-dev-harness/tests/test_navigation_band.py
git commit -m "feat(harness): navigation map region + per-track lanes (additive)"
```

---

## Task 8: End-to-end beat walkthrough (3 modules) via the CLI surface

This proves the design's worked walkthrough through the *public* verbs (`next`/`dispatch`/`submit`), confirming `tracks_frontier` reaches the coordinator and a failing track does not block siblings.

**Files:**
- Test: `tests/test_band_e2e.py` (create) — no source change.

- [ ] **Step 1: Write the failing test**

Create `tests/test_band_e2e.py`:

```python
"""Design walkthrough: 3 modules (auth, reports independent; billing depends on
auth) advance concurrently through the public verbs. Proves: a beat returns
multiple descriptors, independent tracks sit in the frontier at the same time, a
failing track does not block its sibling, and billing only enters the frontier
after auth completes — then the run joins at VERIFIED."""
import json
import sys

from e2e_harness import pipeline
from e2e_harness.core import run_state, engine, module_plan, acceptance, multitrack
from e2e_harness.adapters.evidence import command_evidence


def _mods():
    return [
        {"id": "auth", "name": "Auth", "depends_on": [], "acceptance_ids": ["AC-001"]},
        {"id": "reports", "name": "Reports", "depends_on": [], "acceptance_ids": ["AC-001"]},
        {"id": "billing", "name": "Billing", "depends_on": ["auth"], "acceptance_ids": ["AC-001"]},
    ]


def _artifact(repo, art, phase, key, *, fail=False):
    bkey = multitrack.base_key(key)
    stem = f"{phase.replace('#', '_')}-{key.replace('#', '_')}"
    if bkey == "acceptance_contract":
        p = art / f"{stem}.json"
        p.write_text(json.dumps({"schema": acceptance.SCHEMA, "items": [
            {"id": "AC-001", "criterion": "c", "observable_behavior": "o"}]}), encoding="utf-8")
    elif bkey == "module_plan":
        p = art / f"{stem}.json"
        p.write_text(json.dumps({"schema": module_plan.SCHEMA, "modules": _mods()}), encoding="utf-8")
    elif bkey == "test_substance":
        tf = art / f"{stem}_test.py"
        tf.write_text("def test_x():\n    assert 1 + 1 == 2\n", encoding="utf-8")
        p = art / f"{stem}.json"
        p.write_text(json.dumps({"schema": "e2e-dev-harness.test-substance.v1",
                                 "acceptance_contract_path": str(art / "CLARIFIED-acceptance_contract.json"),
                                 "language": "python", "test_files": [str(tf)],
                                 "red_tests": ["t::test_x"], "green_tests": ["t::test_x"],
                                 "ac_coverage": {"AC-001": ["t::test_x"]}}), encoding="utf-8")
    elif bkey in ("failing_tests", "passing_tests"):
        code = 1 if bkey == "failing_tests" else 0
        if fail:  # force a passing_tests artifact that actually fails its gate
            code = 1
        ev = command_evidence.record_command(art, f'"{sys.executable}" -c "import sys; sys.exit({code})"')
        p = art / f"{stem}.json"
        p.write_text(json.dumps(ev), encoding="utf-8")
    elif bkey == "scope_manifest":
        p = art / f"{stem}.json"
        p.write_text(json.dumps({"schema": "e2e-dev-harness.scope-manifest.v1", "status": "COMPLETE",
                                 "expected": {"services": [], "tables": [], "phases": []},
                                 "delivered": {"services": [], "tables": [], "phases": []}}), encoding="utf-8")
    elif bkey == "verification":
        tf = art / f"{stem}-replay_test.py"
        tf.write_text("def test_real():\n    assert 1 + 1 == 2\n", encoding="utf-8")
        ev = command_evidence.record_command(art, f'"{sys.executable}" -m pytest "{tf}" -q')
        p = art / f"{stem}.json"
        p.write_text(json.dumps(ev), encoding="utf-8")
    else:
        p = art / f"{stem}.md"
        p.write_text("real", encoding="utf-8")
    return str(p.relative_to(repo))


def _drive_prologue(st, repo, art):
    """Walk CREATED..PLANNED submitting evidence until the band forks."""
    for _ in range(8):
        spine = pipeline.spine_for_state(st, repo)
        st["_run_state_path"] = "rs.json"
        res = engine.evaluate(spine, st, repo)
        if st.get("region") == "module_band":
            return res
        ph = res["blocked_phase"]
        phase = next(p for p in spine if p.name == ph)
        for key in phase.produces:
            engine.submit_evidence(st, ph, key, _artifact(repo, art, ph, key), repo_root=repo)
    raise AssertionError("never forked into band")


def test_three_module_beats_reach_verified(tmp_path):
    repo = tmp_path
    art = repo / "art"; art.mkdir()
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    res = _drive_prologue(st, repo, art)

    # Beat 1: auth + reports both in frontier; billing absent (depends on auth)
    blocked = sorted(e["blocked_phase"] for e in res["tracks_frontier"])
    assert blocked == ["RED#auth", "RED#reports"]

    saw_billing_before_auth_done = False
    auth_done_beat = None
    for beat in range(40):
        spine = pipeline.spine_for_state(st, repo)
        st["_run_state_path"] = "rs.json"
        res = engine.evaluate(spine, st, repo)
        if res.get("complete") or res.get("blocked_phase") == "VERIFIED":
            break
        frontier = res.get("tracks_frontier")
        if frontier is None:    # prologue/epilogue singleton step
            ph = res["blocked_phase"]
            phase = next(p for p in spine if p.name == ph)
            for key in phase.produces:
                engine.submit_evidence(st, ph, key, _artifact(repo, art, ph, key), repo_root=repo)
            continue
        # auth completes before billing ever appears
        auth_complete = st["tracks"]["auth"]["complete"]
        if any(e["track"] == "billing" for e in frontier) and not auth_complete:
            saw_billing_before_auth_done = True
        # submit the whole frontier this beat (the real concurrent path)
        for entry in frontier:
            ph = entry["blocked_phase"]
            phase = next(p for p in spine if p.name == ph)
            for key in phase.produces:
                engine.submit_evidence(st, ph, key, _artifact(repo, art, ph, key), repo_root=repo)

    # drive the VERIFIED epilogue to completion
    for _ in range(4):
        spine = pipeline.spine_for_state(st, repo)
        st["_run_state_path"] = "rs.json"
        res = engine.evaluate(spine, st, repo)
        if res.get("complete"):
            break
        ph = res["blocked_phase"]
        phase = next(p for p in spine if p.name == ph)
        for key in phase.produces:
            engine.submit_evidence(st, ph, key, _artifact(repo, art, ph, key), repo_root=repo)

    assert st["current_phase"] == "VERIFIED"
    assert res.get("complete") is True
    assert saw_billing_before_auth_done is False  # billing gated until auth complete


def test_failing_track_does_not_block_sibling(tmp_path):
    repo = tmp_path
    art = repo / "art"; art.mkdir()
    st = run_state.new_run_state("r1", "f", "r", tier="standard", pipeline="standard")
    _drive_prologue(st, repo, art)

    # Beat 1: both RED -> submit failing_tests for both, advancing to IMPLEMENTED
    for mid in ("auth", "reports"):
        engine.submit_evidence(st, f"RED#{mid}", f"failing_tests#{mid}",
                               _artifact(repo, art, f"RED#{mid}", f"failing_tests#{mid}"), repo_root=repo)
    spine = pipeline.spine_for_state(st, repo)
    res = engine.evaluate(spine, st, repo)
    frontier = {e["track"]: e["blocked_phase"] for e in res["tracks_frontier"]}
    assert frontier["auth"] == "IMPLEMENTED#auth"
    assert frontier["reports"] == "IMPLEMENTED#reports"

    # reports IMPLEMENTED fails; auth IMPLEMENTED succeeds
    engine.submit_evidence(st, "IMPLEMENTED#reports", None, None, status="failed", reason="impl bug")
    for key in ("passing_tests#auth", "test_substance#auth"):
        engine.submit_evidence(st, "IMPLEMENTED#auth", key,
                               _artifact(repo, art, "IMPLEMENTED#auth", key), repo_root=repo)
    res = engine.evaluate(spine, st, repo)
    frontier = {e["track"]: e for e in res["tracks_frontier"]}
    assert frontier["auth"]["blocked_phase"] == "REVIEWED#auth"      # auth advanced
    assert frontier["reports"]["blocked_phase"] == "IMPLEMENTED#reports"
    assert frontier["reports"].get("failed") is True                  # reports still in rework
```

- [ ] **Step 2: Run test to verify it fails (then passes)**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_band_e2e.py -q`
Expected: with Tasks 1-7 merged, this should PASS. If it FAILS, the failure localizes a real gap in the band engine — fix the engine (not the test) per superpowers:systematic-debugging, keeping all prior tests green.

- [ ] **Step 3: Commit**

```bash
git add skills/e2e-dev-harness/tests/test_band_e2e.py
git commit -m "test(harness): 3-module concurrent beat walkthrough e2e"
```

---

## Task 9: SKILL.md — beat-cycle coordinator semantics

**Files:**
- Modify: `SKILL.md` (the `## 循环` section, lines 32-34)
- Modify: `tests/test_skill_md.py` (append a beat-semantics assertion)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skill_md.py`:

```python
def test_skill_md_documents_beat_cycle_for_module_band():
    text = SKILL.read_text(encoding="utf-8")
    assert "tracks_frontier" in text
    assert "beat" in text or "一拍" in text
    # the concurrent fan-out + reconcile loop must be described
    assert "module_band" in text
    assert "await" in text or "并发" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_skill_md.py -q`
Expected: FAIL — `tracks_frontier` not present.

- [ ] **Step 3: Implement the doc edit**

In `SKILL.md`, replace the `## 循环` section (lines 32-34):

```markdown
## 循环

`start` → 循环{ `next` → 若 `complete` 收尾;否则 `dispatch` 当前阶段 → spawn worker 子 agent(自加载 `next_action.skill`)→ worker `submit` 证据 → 回到 `next` } 直到 `VERIFIED`。
```

with the beat-aware loop:

```markdown
## 循环 (单游标 + 多轨 beat)

`start` → 循环 → 直到 `VERIFIED`。两种节奏由 `next` 返回的 `region` 决定:

**prologue / epilogue (单游标):** `next` → 若 `complete` 收尾;否则 `dispatch` 当前阶段 → spawn 1 个 worker 子 agent(自加载 `next_action.skill`)→ worker `submit` 证据 → 回到 `next`。

**module_band (多轨 beat):** `next` 返回 `tracks_frontier`(每条活跃轨一个 blocker)。**一个 beat** = 一次并发循环:

1. `next` → 看到 `tracks_frontier`(独立轨可处不同 base 阶段)。
2. `dispatch` → band 区一次拿到整批 descriptor,按轨记 `tracks[m].dispatch = dispatched`。
3. coordinator **一个回合**发 N 个 `Task`/`spawn_agent` 并 `await` 全部 ← 真并发在这里。
4. 各 worker `submit` 自己的 namespaced 证据(经 `run_state.mutate` 串行化)。
5. `next` 对账:所有过 gate 的轨推进;失败轨进轨内 rework(**不卡兄弟轨**);新解锁的依赖轨进下一拍 frontier。

循环 beat 直到三轨全 complete → join → `region=epilogue`、`current_phase=VERIFIED`。

> harness 仍是纯控制面:`tracks_frontier` 只是并行**意图**,真正并发 spawn 永远是 coordinator 的工具调用。`current_phase` 是派生的"领头游标",单游标读者(guards/gate/navigation)照常工作。
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest tests/test_skill_md.py -q`
Expected: PASS (incl. existing frontmatter/verb/tier assertions).

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/SKILL.md skills/e2e-dev-harness/tests/test_skill_md.py
git commit -m "docs(harness): document multi-track beat cycle in SKILL.md"
```

---

## Task 10: Full verification + change scope check + spec self-review

**Files:** none (verification only).

- [ ] **Step 1: Run the complete suite, twice (default + shuffled)**

```bash
cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest -q
cd skills/e2e-dev-harness && E2E_TEST_SEED=1 PYTHONUTF8=1 python -m pytest -q
```
Expected: all pass under both orders (the shuffle seed guards against cross-test state leakage).

- [ ] **Step 2: Confirm change scope with GitNexus**

Run `gitnexus_detect_changes()`. Expected affected symbols: `multitrack.*`, `engine.evaluate`/`_evaluate_band`/`_route_band_verification_rework`, `navigation.navigation_map`, `dispatch.run`. Flag anything unexpected.

- [ ] **Step 3: Spec coverage self-review**

Walk `docs/superpowers/specs/2026-06-12-multi-track-concurrent-coordinator-design.md` section-by-section and confirm each is covered:
- Architecture three regions → Tasks 3-4
- State schema (region/tracks) → Tasks 1, 4 (additive; run_state untouched by design intent — "版本兼容默认值")
- `current_phase` projection → Task 2
- Engine region-aware per-track advance → Task 4
- Beat cycle / no new verb → Tasks 6, 9
- Per-track rework isolation → Task 4 (natural, per-chain cursors) + Task 5 (verification rework)
- navigation_map multi-track view → Task 7
- Determinism & concurrency safety → invariants asserted across the suite
- Back-compat / degenerate single-track → Tasks 3-7 each re-run the legacy suite green
- E2E walkthrough → Task 8

Document any gap found and add a follow-up task before finishing.

- [ ] **Step 4: Finish the development branch**

Use superpowers:finishing-a-development-branch to decide merge/PR/cleanup. Summarize the change: engine evolved to first-class multi-track with `current_phase` as a derived projection; 5 source files touched; new band tests + legacy suite green.

---

## Notes / Decisions baked into this plan

- **No `run_state.py` change:** `region`/`tracks` are additive keys; `save()` already serializes the whole state dict and `load()` validates only the schema string. This honors the design's "版本兼容默认值" with the smallest surface.
- **No `next.py` change:** `next.run` returns the engine result verbatim, so `tracks_frontier`/`region` propagate automatically; `navigation_map` already re-derives.
- **No `agent_team/builtin.py` change:** `plan_module_fanout` already fans the frontier into one worker per module with `module:<id>` parallel groups.
- **Projection is the back-compat keystone:** every existing single-cursor reader (phase_guard, stop_guard, gate, pipeline_validate, status) reads `current_phase`, which the band keeps populated as the least-advanced active track. The legacy `test_multitrack_e2e` therefore stays green unedited.
- **Verification-rework v1 is conservative by construction:** VERIFIED's gate keys (`verification`, `scope_manifest`) are un-namespaced, so the `#module` attribution branch is forward-looking; the practical path reopens all tracks. Precise per-module attribution is future work (design §Open Questions).
