# Harness v2 — U5 DomainAdapter seam (M4 frontend) — Design Spec

- **Status:** Approved (brainstorming) — pending writing-plans
- **Date:** 2026-06-08
- **Branch:** `harness-v2-m2`
- **Roadmap unit:** U5 (`docs/superpowers/plans/2026-06-07-harness-v2-remaining-work-roadmap.md` §U5)
- **Design source:** `2026-06-07-harness-v2-redesign-design.md` §13 (领域适配 seam), §12 (流水线即配置), §15 (invariants)
- **Depends on:** U4 config layer ✅ (pipelines-as-config + `validate-pipeline` + hermetic `pipeline_spec` embed)

---

## 1. Goal

Implement the §13 domain seam: **one `DomainAdapter` interface** so the *same untouched control-plane core* can drive a **frontend** fixture repo to `VERIFIED`, with the existing backend behavior refactored to be "the default adapter." The adapter is auto-selected by repo marker and overridable via pipeline config / CLI flag.

**Non-goal (this unit):** real frontend test execution, real-worker dispatch, full framework AST. The e2e proves the *seam + termination + gate-closure* for a frontend domain using simulated workers — exactly as the backend e2e (`test_cli_e2e.py`) does today.

---

## 2. Grounding: how the current architecture constrains the design

Findings from reading the code (these are *why* the design is shaped this way):

- The **core is a pure control plane.** `core/{lifecycle,engine,gates,dispatch,navigation}` never run scanners or tests. Workers produce artifacts; `gates.gate_passes` only checks an artifact exists + hashes it (`engine.submit_evidence`). So `test_runner`/`review_profile` cannot be *executed* by the core — they are **metadata** surfaced to workers.
- The **only domain touch-point today is `cli/commands/start.py`**, which optionally calls `classify.classify_tier(request)` — text-only; it does not even invoke the (already ported) scanner.
- **U4 already provides the override channel §13 asks for.** A pipeline spec is per-phase `{worker_role, worker_skill, produces, exit_gate}` overrides (`pipeline._OVERRIDE_FIELDS`); a custom spec is embedded hermetically into run-state as `pipeline_spec` and rebuilt by `pipeline.spine_for_state`. `pipeline_validate.validate_spec` enforces I1/I2 on any spec.
- The **backend e2e simulates workers**: it writes real artifact files and submits their paths, asserting `start→VERIFIED` terminates in ≤6 steps (and that fake paths never reach `VERIFIED`). No real test suite runs.

**Consequence:** the adapter can be a **config-producer consulted only at `start`**, reusing U4 as its integration mechanism. The protected core needs zero edits.

---

## 3. Scope decisions (from brainstorming)

| # | Decision | Choice |
|---|---|---|
| S1 | Frontend e2e realism | **Simulated workers**, mirror `test_cli_e2e.py`; assert `start→VERIFIED` termination with frontend adapter selected. `test_runner` stays metadata. |
| S2 | Adapter selection + back-compat | **Auto-detect by repo marker**; adapter overridable via `--adapter` / pipeline `domain:` key; **`--tier auto` stays text-only by default** (scanner-floor escalation is opt-in via `--scan`). Existing runs/tests unchanged. |
| S3 | Integration approach | **Config-producer adapter** (Approach A): emits scope + pipeline-spec overrides through U4; core untouched. |

---

## 4. The "核心零改动" boundary (stated precisely)

§13 says "核心零改动." To keep that claim honest, the spec defines exactly what is and isn't touched:

- **Zero edits (protected core):** `core/lifecycle.py`, `core/engine.py`, `core/gates.py`, `core/dispatch.py`, `core/navigation.py`, `core/pipeline_validate.py`, `pipeline.py`.
- **Touched (CLI + SSOT plumbing, not control-plane logic):**
  - `cli/commands/start.py` — adapter selection, spec merge, `domain` block in state + output.
  - `cli/main.py` — new `start` flags `--adapter`, `--scan`.
  - `core/run_state.py::new_run_state` — **additive optional** `domain` block, **embedded only for non-default adapters** (omitted for the backend default → backend run-state is byte-identical to today, so `test_run_state.py` is untouched). Mirrors how `pipeline_spec` is omitted for named pipelines.
  - `cli/commands/dispatch.py` — attach domain metadata to the worker packet via the **existing** `dispatch.worker_packet(..., extra_context=…)` param, reading the `domain` block **from run-state** (no registry re-lookup; `core/dispatch.py` itself untouched).
- **New:** `adapters/domain/` package, a frontend scanner, tests, and a frontend fixture.

---

## 5. Components

### 5.1 `adapters/domain/base.py` — the interface
```python
from pathlib import Path
from typing import Protocol

class DomainAdapter(Protocol):
    name: str                                   # "backend" | "frontend"
    test_runner: str                            # metadata: "pytest"/"maven" | "vitest"
    review_profile: str                         # metadata: "backend-default" | "frontend-default"

    def detect(self, repo: Path) -> bool: ...                       # marker sniff
    def scan(self, repo: Path, request: str) -> dict | None: ...    # scanner-scope.v1 | None
    def pipeline_overrides(self) -> dict: ...                       # {phase_name: {override fields}}
```
`pipeline_overrides()` returns a mapping consumable by the spec merge (§6): keys are phase names, values use the same fields as `pipeline._OVERRIDE_FIELDS` (`worker_role`, `worker_skill`, `produces`, `exit_gate`).

### 5.2 `adapters/domain/registry.py` — selection
`select(repo: Path, explicit: str | None = None) -> DomainAdapter`:
1. `explicit` (from `--adapter` or pipeline `domain:`) — resolve by `name`; unknown ⇒ raise (CLI maps to exit 2).
2. else first adapter in registry order whose `detect(repo)` is True. **Order: frontend before backend** (frontend is the more specific marker).
3. else the registry's **default adapter** (= backend). The registry owns the fallback; no adapter's `detect` is a degenerate always-`True`.

The backend is the **default** in the registry's sense: when no marker matches (e.g. an empty/unmarked repo), `select` returns it. Symmetric with `pipeline_spec`-absent ⇒ named pipeline.

### 5.3 `adapters/domain/backend.py`
- `name="backend"`, `test_runner` derived from markers (`"maven"` if `pom.xml`/`build.gradle`, else `"pytest"`), `review_profile="backend-default"`.
- `detect`: marker-based — `pom.xml` | `build.gradle*` | `pyproject.toml` | `setup.py` | `go.mod` present. **Not** an always-`True` sentinel; the registry (§5.2 step 3) supplies the no-marker fallback.
- `scan`: choose `scanner.discover_scope_java_spring` when a Spring/Java marker is present, else `scanner.discover_scope`. Returns `scanner-scope.v1` (or `None`).
- **`pipeline_overrides() == {}`** — the catalog defaults *are* the backend defaults, and (per §4) the `domain` block is omitted for the default adapter. This is the **parity guarantee**: a backend run's spec and run-state are byte-identical to today, so all existing tier/pipeline/e2e/run_state tests stay green.

### 5.4 `adapters/domain/frontend.py`
- `name="frontend"`, `test_runner="vitest"`, `review_profile="frontend-default"`.
- `detect`: `package.json` present **and** (a known frontend framework dep — `react`/`vue`/`svelte`/`@angular/core` — **or** a `vite.config.*` / `vitest.config.*`).
- `scan`: thin frontend scope function (§5.5) → `scanner-scope.v1` with discovered components/routes as `services`/`components`. **Heuristic, not full framework AST** (deferred, §9).
- `pipeline_overrides()`: **metadata-only / empty for this unit** (YAGNI — no contrived spine change). Same 7-phase catalog; frontend differences ride as **metadata** (`test_runner`/`review_profile` → worker context). Dedicated frontend worker-skills are deferred until real workers exist (§9). The e2e's meaning comes from adapter selection by marker + frontend scope + the `domain` block in state — **not** from a structurally different spine.
- **Override *channel* is still proven** (so the §13 capability isn't shipped untested): a focused unit test (§8 `test_domain_overrides_merge`) uses a synthetic adapter that *does* contribute per-phase overrides, asserting the merge applies them and the merged spec still passes `validate_spec`. This tests the capability without contriving frontend behavior.

### 5.5 Frontend scanner
A small `scan_frontend(repo) -> dict` producing `scanner-scope.v1`, placed at `adapters/scanner/frontend.py` and re-exported from the scanner package (cohesion with the existing scanner adapter). Walks the fixture's `src/` for component files (`*.tsx`/`*.jsx`/`*.vue`/`*.svelte`) and a routes manifest if present; returns `{services: [...], components: [...], dependencies: []}` shaped like `scanner-scope.v1`. No external tooling; pure file walk.

---

## 6. Data flow — `start`

```
start --repo R --feature F --request "..." [--adapter X] [--pipeline P] [--tier auto] [--scan]
```
1. `adapter = registry.select(R, explicit=X or spec.domain)` — always selected (even when `--scan` off).
2. tier: if `--tier auto` → `classify_tier(request, scope=adapter.scan(R, request) if --scan else None)`. **Default (no `--scan`): text-only**, identical to today.
3. base pipeline = `--pipeline` or `tier` → `pipeline.load_spec(base)`.
4. **merge** `adapter.pipeline_overrides()` into the base spec's phase entries → `merged_spec`.
5. `validate_spec(merged_spec)` (U4 I1/I2). Invalid ⇒ exit 2 JSON.
6. embed-when-non-default rule: let `non_default = is_custom_path(base) or adapter.pipeline_overrides() or adapter.name != "backend"`.
   `run_state.new_run_state(..., pipeline=base, pipeline_spec=merged_spec if non_default else None, domain=domain_block if adapter.name != "backend" else None)` → `save`.
   The **`domain` block** is `{"name": adapter.name, "test_runner": adapter.test_runner, "review_profile": adapter.review_profile}` — self-describing SSOT so no consumer re-derives from the registry. For the backend default both are `None` ⇒ run-state byte-identical to today.
7. `start.v1` output gains `"domain": adapter.name` (and `tier_reasons` as today).
8. On `dispatch`, the CLI reads the `domain` block **from run-state** and appends a domain-metadata pointer to `extra_context`, so the worker packet carries the conventions without any `core/dispatch.py` change. (Backend: no block ⇒ no extra context ⇒ unchanged packet.)

**Merge rule:** for each phase in `pipeline_overrides()`, apply its fields onto the matching base-spec phase entry (promoting a bare string entry to a mapping `{phase, ...overrides}`). Phases not mentioned are unchanged. Backend (`{}`) ⇒ no-op ⇒ parity.

---

## 7. Error handling

| Condition | Behavior |
|---|---|
| Unknown `--adapter` / `domain:` value | exit 2 JSON `{"error":"unknown adapter", "adapter":X}` (mirrors unknown-pipeline). |
| Both frontend & backend markers (fullstack repo) | frontend wins by registry order; overridable via `--adapter`/`domain:`. Rule documented. |
| `adapter.scan` raises / returns nothing | treated as no scope (tier floor skipped) + recorded reason; `start` never crashes. (Only reachable under `--scan`.) |
| Merged spec unsatisfiable (I1/I2) | existing `validate_spec` rejects → exit 2. |

---

## 8. Testing (TDD; new core-style tests + simulated-worker e2e)

| Test file | Asserts |
|---|---|
| `tests/test_domain_adapter.py` | `detect` on backend vs frontend fixtures; `select` precedence (explicit > marker > fallback); unknown-adapter error. |
| `tests/test_domain_backend_parity.py` | backend `pipeline_overrides()=={}` ⇒ merged spec == base spec for each tier; backend run-state has **no `domain`/`pipeline_spec` keys** (byte-identical to today). |
| `tests/test_domain_overrides_merge.py` | synthetic adapter with per-phase overrides ⇒ merge applies them onto the base spec **and** `validate_spec` still passes (proves the §13 override channel). |
| `tests/test_domain_frontend_scan.py` | `scan_frontend` on the fixture ⇒ `scanner-scope.v1` listing the fixture's component(s). |
| `tests/test_cli_frontend_e2e.py` | `start` on the frontend fixture → drive to `VERIFIED` with **real artifact files** (mirror `test_cli_e2e.py`); assert `domain=="frontend"`, `navigation_map.you_are_here=="VERIFIED"`, steps ≤ 6; assert fake paths never reach `VERIFIED`. |

Fixture: `tests/fixtures/frontend_app/` — `package.json` (with a frontend dep), one component under `src/`, and a vitest test file **as data** (never executed). Existing full v2 suite must stay green (parity).

---

## 9. YAGNI / deferred (explicit, non-silent)

- Real framework AST scan (React/Vue route+component graph) — heuristic file-walk suffices for the seam.
- Real `vitest` execution / real-worker dispatch — blocked on the broken subagent dispatch; e2e simulates workers.
- Dedicated `e2e-harness-*-frontend` worker skills — current skills are domain-agnostic; conventions ride as metadata until real workers land.
- Additional domains (mobile, infra, etc.) — the registry is open; only backend+frontend ship now.

---

## 10. Invariants & affected nodes

- **I1/I2 re-checked on the merged spec** via U4's `validate_spec` — a domain adapter cannot produce a non-terminating or gate-unsatisfiable pipeline.
- **Parity invariant (precise):** the backend default contributes `{}` overrides **and** omits both the `pipeline_spec` and `domain` keys, so a backend run-state is **byte-identical** to today's — not merely behaviorally equivalent. Every existing tier/pipeline/e2e/`run_state` test stays green unchanged.
- Per CLAUDE.md, run `gitnexus_impact` on any edited existing symbol (`start.run`, `new_run_state`, `main` arg parser, `dispatch` command) before editing in the build phase.

---

## 11. Workflow

`superpowers:writing-plans` → TDD build (`superpowers:test-driven-development`). Lands green + committed; reviewed separately (`/code-review`) given subagent dispatch is broken (roadmap risk note).
