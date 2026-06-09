# Harness e2e-dev-harness �?Remaining-Work Roadmap (post scanner+kg leaf ports)

> **Genre:** This is a **roadmap / plan-of-plans**, not a single exact-code TDD plan. The remaining work spans several independent subsystems and three milestones (M2-tail �?M5) of very unequal readiness; per `superpowers:writing-plans` Scope Check, each unit below becomes its **own** focused writing-plans pass (and, where flagged, a `superpowers:brainstorming` pass first) when it is picked up. Each unit is independently shippable and ends green + committed.

**As of:** 2026-06-07, branch `e2e-dev-harness-m2`, full e2e-dev-harness suite **95 passed**.
**Design source:** [2026-06-07-e2e-dev-harness-redesign-design.md](../specs/2026-06-07-e2e-dev-harness-redesign-design.md) (§5 port list, §11 pruning, §12 config, §13 domain seam, §14 milestones, §15 invariants, §16 YAGNI).

## Done so far (do not re-plan)
- **M1** walking skeleton: SSOT run-state, terminating spine, single dispatch enum, navigation map, minimal tier, pointer packets. �?- **M2 core**: standard/critical/audited tiers, structural phase pruning, r1/r2/r3 review fan-out, R1 artifact-validating gates, R1' planning/review delegators, L1/L2/L5–L7, §4 all-tier gate-closure seed. �?- **M2 leaf ports** (design §5): `hashing`, `command_evidence`, `task_tier` (M2); **`kg-evidence` + `scanner`** (this session �?commits `2138153`, `012c071`). �?- **M2-tail (U1/U2/U3)**: memory leaf port, runtime→`spawn_worker` seam, scanner→tier escalation wiring (commits `ce3a7a7`, `41910be`, `2f44dfa`). �?- **M3 config layer (U4)**: pipelines-as-config (built-in tiers as `pipelines/*.yaml` + loader), `validate-pipeline` verb (I1/I2 preflight) + `start` guard, custom pipelines by name/path with hermetic run-state embed. �?- **M4 frontend `DomainAdapter` (U5)**: config-producer adapter selected at `start` (registry + marker auto-detect, `--adapter`/`--scan` flags), emitting pipeline-spec overrides + a self-describing `domain` block via U4's config layer; backend is the default adapter (byte-identical parity, **zero** core edits �?lifecycle/engine/gates/dispatch/navigation/pipeline untouched); `dispatch` surfaces the domain block to workers; a frontend fixture repo is auto-detected and driven `start �?VERIFIED`. �?
---

## Remaining units (sequenced)

| Unit | What | Milestone | Design-first? | Depends on | Est. size |
|---|---|---|---|---|---|
| **U1** | memory leaf port | M2-tail (§5) | No (one small coupling call) | �?| Medium-High |
| **U2** | runtime-adapter �?`spawn_worker` seam | M2-tail (§5) | **Yes �?brainstorm** | �?| High |
| **U3** | scanner �?tier escalation wiring | M2-tail follow-on (§11) | No | scanner port �?| Small |
| **U4** | M3 config layer: `pipelines/*.yaml` + `validate-pipeline` (R2) + custom pipelines | M3 (§12, §15) | **Yes �?brainstorm schema** | U1–U3 landed (stable spine) | High |
| **U5 �?* | M4 frontend `DomainAdapter` | M4 (§13) | **Yes �?brainstorm interface** | U4 (config overrides) | High |
| **U7 �?* | net-new e2e-dev-harness hook layer (PreToolUse phase-lock + Stop) �?parity-audit gap | §16 / hook design | **Yes �?design doc** | U1–U5 | Medium |
| **U6 �?* | M5 switchover: e2e-dev-harness default + migration docs + delete legacy | M5 (§14) | No | U1–U5, **U7** (hook parity) | Medium |

**Recommended order:** U3 (quick win) �?U1 (last pure port) �?U2 (brainstorm+build) �?U4 �?U5 �?U6. U1 and U3 are independently startable today; U2/U4/U5 each open with a brainstorming pass.

---

## U1 �?memory leaf port (M2-tail)

**Goal:** Vendor `memory_capture.py` (1210L) into `e2e_harness/adapters/memory/` behind a narrow interface and bring `tests/test_memory_capture.py` green �?same faithful vendoring pattern as kg/scanner (verbatim `cp`, byte-diff verified, test header repointed).

**The one non-mechanical decision (resolve before writing the plan):** `tests/test_memory_capture.py` imports **both** `memory_capture` **and** `e2e_dev_harness` (the legacy CLI). The kg/scanner tests had no such coupling; memory does. Options to decide in the U1 writing-plans pass:
1. **Vendor the minimal slice of `e2e_dev_harness` the test touches** (preferred if it's a few helpers) �?keep test verbatim.
2. **Trim the test** to the `memory_capture`-only assertions and drop the `e2e_dev_harness`-dependent cases, recording exactly which cases were dropped and why (no silent truncation).
3. **Vendor the whole legacy CLI module** (rejected unless the coupling is deep �?that drags M5-owned code into e2e-dev-harness early).
First action of the U1 plan: grep `test_memory_capture.py` for every `e2e_dev_harness.` reference and pick the narrowest option.

**Acceptance criteria:**
- `memory_capture.py` (+ any `common` deps) vendored byte-identical under `adapters/memory/_legacy/`; `diff` proves it.
- `adapters/memory/__init__.py` re-exports the public surface (e.g. `init_memory`, `scan_memory`, `validate_memory`, `render_entry`, parse/format helpers as needed by callers).
- Ported `test_memory_capture.py` green; the `e2e_dev_harness` coupling resolved by one of the options above, decision documented in the plan.
- Full e2e-dev-harness suite green; changes confined to `skills/e2e-dev-harness/`; no legacy edits.

**Affected files:** new `adapters/memory/_legacy/*`, `adapters/memory/__init__.py`, `tests/test_memory_capture.py` (ported); possibly a vendored slice of legacy CLI helpers.

**Workflow:** `superpowers:writing-plans` �?`superpowers:subagent-driven-development` (or inline �?dispatch is currently broken, see Risks). Pattern reference: this session's kg/scanner commits.

---

## U2 �?runtime-adapter �?single `spawn_worker` seam (M2-tail)

**Goal:** Converge the legacy runtime adapters (`runtime_adapters.py` 388L + `e2e_harness/adapters/runtime/{base,claude_code,codex_multi_agent,manual,opencode_task}.py`) into **one** narrow `spawn_worker(packet) -> handle` interface (design §5), so the e2e-dev-harness coordinator has a single way to launch a worker regardless of runtime.

**Why brainstorm first (no plan yet):** Unlike kg/scanner/memory this is **not a faithful port** �?there is **no legacy test** to anchor behavior, and §5 explicitly asks for a *redesign* (collapse 4 runtimes to one seam). Open questions for `superpowers:brainstorming`:
- What is the exact `spawn_worker` signature and the `handle` it returns? (sync result vs async handle vs detached-with-poll?)
- How does the pointer packet `{role, skill, context_paths[], expected_outputs[]}` map onto each runtime's launch?
- Which of the 4 legacy runtimes must e2e-dev-harness actually support now (YAGNI �?design is "current backend-first"), and which collapse to `manual`/stub?
- How does this relate to the **broken subagent dispatch** observed this session (model resolved to inaccessible `glm-4.7`)? The seam design should make the runtime/model selection explicit and testable.

**Acceptance criteria (to be firmed in brainstorming):**
- A single `spawn_worker(packet)->handle` in `adapters/runtime/` with a fresh TDD test suite (no legacy test exists to port).
- At least the in-use runtime path works end-to-end driving a real (or stub) worker; unused runtimes are explicitly out-of-scope, not silently dropped.
- The e2e-dev-harness dispatch core (`core/dispatch.py`) can call the seam; coordinator stays a pure control plane.

**Workflow:** `superpowers:brainstorming` (interface + scope) �?`superpowers:writing-plans` �?TDD build.

---

## U3 �?scanner �?tier escalation wiring (M2-tail follow-on; quick win)

**Goal:** Now that the scanner leaf is ported, wire its output into tier classification. `adapters/tier/classify.py` currently notes multi-service / dependency-report escalation is "intentionally omitted until the scanner leaf is ported." Unblock it.

**Why it's a behavior change, not a port:** classification will now **escalate** the tier (e.g. `standard �?critical`) when the scanner reports multiple services or cross-service dependencies. That changes outputs, so it gets its own TDD task with golden fixtures asserting the thresholds �?not a silent addition.

**Acceptance criteria:**
- `classify` (or a thin wrapper) accepts an optional scanner scope/dependency-report and escalates per documented rules (e.g. �? services �?at least `standard`; cross-service dependency edges �?`critical`); thresholds asserted by golden fixtures.
- Text-only classification path unchanged when no scanner input is supplied (back-compat: existing `test_tier_classify.py` stays green).
- The `intentionally omitted` comment in `classify.py` is removed/updated to describe the now-live behavior.
- Full e2e-dev-harness suite green.

**Affected files:** `adapters/tier/classify.py`, new `tests/test_tier_escalation.py` (+ golden fixtures), update `tests/test_tier_classify.py` only if signatures change.

**Workflow:** `superpowers:writing-plans` (small) �?TDD. Startable today.

---

## U4 �?M3 config layer (`pipelines/*.yaml` + `validate-pipeline` + custom pipelines)

**Goal:** Make the spine **configuration, not hardcode** (design §12): declarative `pipelines/*.yaml` (phase order, per-phase worker skill, gate/evidence sets, tier overrides); a `validate-pipeline` command enforcing invariants **I1 (termination)** and **I2 (gate-closure)** at runtime (this is **R2** from the M2 planning input, formally an M3 item �?its seed test `test_all_builtin_tiers_gate_closed` already exists); user/project custom pipelines interpreted by the state machine with built-in tiers as just the factory config.

**Why brainstorm first:** the yaml **schema** and the `validate-pipeline` **semantics** are design decisions. Open questions for `superpowers:brainstorming`:
- yaml shape: how phases, gates, evidence keys, tier-activation, and skill bindings are expressed.
- Where built-in tiers move from `pipeline.py` constants into shipped yaml (and how that stays backward-compatible with the current `pipeline.py` tests).
- `validate-pipeline` as a CLI verb vs a start/next early guard (design §12 wants "any config validated before running").

**Acceptance criteria (firm in brainstorming):**
- Built-in tiers expressed as shipped `pipelines/*.yaml`; state machine interprets them; existing tier/pruning/fan-out tests stay green (behavior parity).
- `validate-pipeline` rejects an unsatisfiable pipeline (I2 violation: a required evidence with no producing phase) and a non-terminating one (I1) with a clear JSON error �?with tests for both a custom valid pipeline (runs) and an unsatisfiable one (rejected).
- A user-supplied custom pipeline can run end-to-end.

**Workflow:** `superpowers:brainstorming` �?`superpowers:writing-plans` �?TDD. Best sequenced after U1–U3 so the spine it serializes is stable.

---

## U5 �?M4 frontend `DomainAdapter` (§13)

**Goal:** Implement the domain seam so the same core drives a **frontend** fixture repo to `VERIFIED`: one `DomainAdapter` interface (`scan(repo)->services/components`, `test_runner`, `review_profile`, `gate_bindings`/`worker_skill_overrides`) with a frontend adapter (routes/components scan, vitest/jest/playwright runner) �?core untouched.

**Why brainstorm first:** the `DomainAdapter` interface is the load-bearing abstraction; getting it right is the whole point of the §13 seam. Brainstorm the interface, the default-adapter auto-detection by repo markers, and the minimal frontend fixture repo. Depends on U4 (pipeline config is how an adapter overrides gate bindings / worker skills).

**Acceptance criteria (firm in brainstorming):**
- `DomainAdapter` protocol + the existing backend behavior refactored to be "the default adapter" with **zero** core changes to spine/dispatch/gates/navigation (design §13: "核心零改�?).
- A frontend adapter drives a frontend fixture repo `start �?VERIFIED`.
- Adapter selected by repo marker, overridable in pipeline config.

**Workflow:** `superpowers:brainstorming` �?`superpowers:writing-plans` �?TDD.

---

## U6 �?M5 switchover (§14) �?DONE 2026-06-08

**Milestone M5 delivered:** e2e-dev-harness is the default harness; npm + pyproject entry points cut to e2e-dev-harness; U7 hooks wired by the installer; MIGRATION.md + CHANGELOG 0.2.0 shipped; legacy `skills/e2e-dev-harness/` + its test suite deleted (207 files, 80762 lines). e2e-dev-harness suite 228 green, node suite 28 green post-delete. Design doc: `docs/superpowers/specs/2026-06-08-e2e-dev-harness-u6-cutover-design.md`; plan: `docs/superpowers/plans/2026-06-08-e2e-dev-harness-u6-cutover.md`. **e2e-dev-harness-m2 complete (M1–M5 + U7).**

**Goal:** Make e2e-dev-harness the default harness, write migration docs, retire the legacy skill �?**only after** U1–U5 prove no capability loss.

**Acceptance criteria:**
- Parity audit: every capability the legacy skill offered is covered by e2e-dev-harness (or explicitly, documentedly dropped per §16 YAGNI �?recover/gc/timeline). **Legacy tool-layer enforcement (`phase_guard` PreToolUse + `harness_stop_guard` Stop) is now covered by U7's e2e-dev-harness hook layer** �?no longer a deletion blocker.
- e2e-dev-harness set as default entry point; migration/CHANGELOG doc; legacy `skills/e2e-dev-harness/` removed in a dedicated commit.
- Installer wires the U7 e2e-dev-harness hooks (claude `phase_guard`/`stop_guard`, opencode plugin) �?U6 Stage 3.
- Old harness retired with no functional regression.

**Workflow:** `superpowers:writing-plans` �?`superpowers:finishing-a-development-branch`. Gated on all prior units. **Delete-legacy is now unblocked: U7 (�? supplied the missing hook-enforcement parity that previously gated retirement.** U6 still needs its own design doc before the writing-plans pass.

---

## Cross-cutting risks / notes

- **Subagent dispatch is currently broken** in this environment: every `Agent`/workflow dispatch �?even with an explicit `model` override �?resolves to inaccessible `glm-4.7`. Until fixed, the `subagent-driven-development` two-stage review can't run; units land via **inline execution** with byte-diff + full-suite + parity evidence, and reviews must be run separately (e.g. `/code-review` on the commits). Worth fixing before U2/U4/U5 (which benefit most from independent review). Likely a workflow/subagent model pin in settings.
- **GitNexus index is stale** (`npx gitnexus analyze`) �?refresh before U2/U4/U5 so the CLAUDE.md-mandated `gitnexus_impact` pre-edit checks are meaningful (U3/U4 edit existing e2e-dev-harness symbols; U1/U2 are mostly new files).
- **No legacy edits before M5** (design §15): U1–U5 are new e2e-dev-harness files / e2e-dev-harness-internal edits only. The legacy `skills/e2e-dev-harness/` stays frozen until U6.
- **Faithful-port units (U1) vs build units (U2–U5):** U1 follows the proven verbatim-vendoring recipe (kg/scanner). U2–U5 are real design+build and each opens with brainstorming; do not shortcut them into copy jobs.

## Deferred / explicitly out of scope (design §16 YAGNI)
- `dir_graph.py` (separate dir-graph contract feature; not part of kg-evidence).
- recover / gc / timeline legacy commands �?not ported unless a real flow needs them.
- Re-homing the full legacy 1266-test suite �?only per-leaf tests travel with their leaves.
