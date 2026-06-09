# U6 �?M5 Cutover Design (e2e-dev-harness default + migration docs + delete legacy)

**Date:** 2026-06-08
**Unit:** U6 (final unit of e2e-dev-harness-m2)
**Status:** design (pre-writing-plans)
**SSOT baseline:** `2026-06-07-e2e-dev-harness-redesign-design.md` §1, §5, §6, §14 (M5), §16
**Depends on:** U1–U5 (capability parity) + **U7 �?* (hook-enforcement parity)

---

## 1. Goal

Retire the legacy `skills/e2e-dev-harness/` and make e2e-dev-harness the sole, default harness �?**only after** proving no capability loss (design §14 M5). Outward-facing: Node + Python entry points switch to e2e-dev-harness; version 0.1.0 �?0.2.0; migration doc published; legacy deleted in a dedicated, reversible-by-revert commit.

**Chosen approach (方案 A): audit-first �?cutover.** Establish evidence-backed parity (Stage 1) *before* flipping any entry point, so the delete is a documented consequence, not a leap.

---

## 2. Parity audit (Stage 1 �?evidence)

Baseline = every capability the legacy skill offered. Each row is **covered**, **deferred** (recorded, recoverable), or **dropped** (YAGNI, design §5/§16).

| Legacy capability | e2e-dev-harness coverage | Verdict |
|---|---|---|
| 35-verb CLI (start/next/dispatch/�?doctor/preflight/map/timeline) | 6 verbs + `validate-pipeline` (§6 mapping table) | **covered** |
| `phase_guard.py` PreToolUse (phase-lock code writes) | `phase_guard.py` (U7) | **covered (U7)** |
| `harness_stop_guard.py` Stop (continue-until-verified) | `stop_guard.py` (U7) | **covered (U7)** |
| tier scaling (`task_tier.py` + golden fixtures) | `minimal/standard/critical/audited` pipelines (M2) | **covered** |
| review fan-out r1/r2/r3 (isolated, no self-review) | critical/audited pipelines (M2) | **covered** |
| scanners (generic + java_spring AST) | `adapters/scanner` (M2/U3) | **covered** |
| KG evidence (gitnexus integration) | `adapters/kg` (M2) | **covered** |
| memory capture | `adapters/memory` (U1) | **covered** |
| runtime adapters (claude/codex/opencode/manual) | `spawn_worker` seam (U2) | **covered** |
| frontend support | `DomainAdapter` (M4/U5) | **covered** |
| navigation map (whole-journey awareness) | `next` navigation_map (M1) | **covered** |
| command_evidence / hash_artifacts | `adapters/evidence` (M2) | **covered** |
| declarative gates (clarify/coverage/handoff/impl/reviewer/rework/service-design gates) | declarative `gate` + pipeline `exit_gate` (M2/M3) | **covered** |
| user-custom pipelines | `pipelines/*.yaml` + `validate-pipeline` (M3) | **covered** |
| `session_checkpoint.py` | U7 design **deferred** session-checkpoint hook | **deferred** |
| `dir_graph.py` (dir-graph contract) | separate feature, not kg-evidence | **dropped (§16)** |
| `recover` / `gc_run` / `timeline` (`execution_trace`) | YAGNI; re-add if a real flow needs it | **deferred (§5/§6/§16)** |
| legacy state aliases / `worker_running_unverified` shim | single e2e-dev-harness state enum | **dropped (§5)** |
| `harness_doctor` / `harness_advice` / `preflight` | folded into `next` (§6) | **covered** |

**Conclusion:** no *covered* capability is lost. All non-covered items are explicitly deferred (recoverable, recorded here) or dropped per design §16 �?never silently. **Delete is safe.**

### Delete-safety evidence (independent of parity)
- 6 worker skills `skills/e2e-harness-*/` import nothing from legacy (`grep -rl 'e2e-dev-harness/scripts|e2e_dev_harness' skills/e2e-harness-*/` �?empty).
- e2e-dev-harness vendors its own `_legacy/` leaves (kg/scanner/memory) �?self-contained; no runtime path into `skills/e2e-dev-harness/`.
- Full e2e-dev-harness suite green (223 passed) with legacy present **and** must stay green after delete (Stage 5 gate).

---

## 3. Current cutover landscape (working tree, pre-U6)

The npm side was **partially cut** in a prior session (the deferred working-tree `M`):

| Surface | State today | U6 action |
|---|---|---|
| `package.json` | `version: 0.2.0`, `bin �?bin/e2e-harness.js`, `files` includes `skills/e2e-dev-harness` (not legacy) | validate + commit (Stage 2a) |
| `lib/resolve.js` | `HARNESS_VERBS` �?dispatches to `e2e_dev_harness.py` | validate + commit (Stage 2a) |
| `bin/`, `lib/*`, `tools/install-*.mjs`, `tests/test_node_installer.py`, `.npmignore`, `tools/clean-pack.mjs` | half-finished npm-cutover working set | validate + commit (Stage 2a) |
| **`pyproject.toml`** | `[project.scripts]` �?**`e2e_dev_harness:main` (LEGACY)**, `package-dir` = legacy scripts | **switch to e2e-dev-harness (Stage 2b)** |
| `skills/e2e-dev-harness/SKILL.md` | exists, not marked default | mark default (Stage 2c) |
| `skills/e2e-dev-harness/` (legacy) | present, frozen | delete (Stage 5) |

**Critical ordering invariant:** `pyproject.toml` currently *points at* legacy. The Python entry MUST switch to e2e-dev-harness (Stage 2b) **before** legacy is deleted (Stage 5), or `pip install` / console-scripts break. The plan enforces Stage 2b �?Stage 5 ordering.

---

## 4. Resolved decisions

1. **Audit-first (方案 A).** Stage 1 parity table is committed as the gating artifact before any entry flip.
2. **pyproject �?e2e-dev-harness before delete.** Hard ordering constraint (§3). pyproject `[project.scripts]` retargets to the e2e-dev-harness entry; `package-dir`/`packages` repoint to `skills/e2e-dev-harness/scripts` (`e2e_harness*` + the `e2e_dev_harness` module). Keep the three legacy alias names? �?**No**: rename console scripts to the e2e-dev-harness surface (`e2e-dev-harness` matching the argparse `prog`), with `e2e-dev-harness`/`e2eh` retained as aliases pointing to e2e-dev-harness for muscle-memory continuity. (Final alias set resolved in the plan after reading the e2e-dev-harness entry's `main` signature.)
3. **npm already 0.2.0.** Do not re-bump; Stage 2a only validates + commits the existing working set. CHANGELOG documents 0.1.0 �?0.2.0 (Stage 4).
4. **Installer wires U7 hooks (Stage 3).** The Node + Python installers register `phase_guard`/`stop_guard` (claude settings + opencode plugin) from `skills/e2e-dev-harness/hooks/*.example.*`, rewriting `__e2e_harness_SCRIPTS__` to the installed abs path. Replaces the legacy `install_hooks.py` phase_guard/stop_guard wiring �?**no capability gap** (U7 supplied the e2e-dev-harness hooks).
5. **Default = e2e-dev-harness.** e2e-dev-harness `SKILL.md` description/title marked as the canonical harness; the user-global `CLAUDE.md`/project pointer (if any) and installer manifest point to e2e-dev-harness. Legacy SKILL.md removed with the rest in Stage 5.
6. **Deferred items stay recorded, not deleted-into-void.** A "Deferred / recoverable" section in `MIGRATION.md` lists session-checkpoint, recover/gc/timeline, dir_graph with the legacy file they lived in (recover via `git show <pre-delete-sha>:<path>`).

---

## 5. Stages (execution order)

| Stage | What | Commit | Reversible? |
|---|---|---|---|
| **1** | Parity audit table (this doc §2) | docs commit | n/a |
| **2a** | npm cutover: validate (`npm test`, `test_node_installer`, `npm pack` dry-run, `bin` smoke in a scratch install) �?commit working set | feat commit | yes (revert) |
| **2b** | pyproject `[project.scripts]` + `package-dir`/`packages` �?e2e-dev-harness; `python -m build`/`pip install -e .` smoke; console-script smoke | feat commit | yes (revert) |
| **2c** | e2e-dev-harness `SKILL.md` set as default canonical harness | feat commit | yes |
| **3** | installer registers U7 e2e-dev-harness hooks (Node + Python paths) + tests | feat commit | yes |
| **4** | docs: parity table �?this doc (done S1); `MIGRATION.md`; `CHANGELOG` 0.1.0 �?0.2.0 | docs commit | yes |
| **5** | **delete `skills/e2e-dev-harness/`** (+ legacy pyproject artifacts) �?dedicated commit; then full suite (223) green + `grep` no residual legacy refs | chore/remove commit | by revert |
| **6** | `superpowers:finishing-a-development-branch` | �?| �?|

**Verification gates:**
- After 2a/2b: respective entry smoke passes (Node bin resolves a e2e-dev-harness verb; Python console script runs `start`).
- After 3: installer tests green (hook files land at install target with rewritten path).
- After 5: `python -m pytest skills/e2e-dev-harness/tests -q` = 223 passed; `grep -r 'e2e-dev-harness/scripts\|e2e_dev_harness\b'` over repo (excluding docs/git history) returns no *runtime* reference.

---

## 6. Affected files (anticipated)

- `pyproject.toml` (2b �?entry/package retarget)
- `package.json`, `lib/*.js`, `bin/*.js`, `tools/install-e2e-dev-harness.mjs`, `tests/test_node_installer.py`, `.npmignore`, `tools/clean-pack.mjs` (2a �?commit existing working set; minor fixups if validation fails)
- `tools/install-e2e-dev-harness.mjs` + Python installer + their tests (3 �?hook wiring)
- `skills/e2e-dev-harness/SKILL.md` (2c)
- `MIGRATION.md` (new, 4), `CHANGELOG.md` (4)
- `skills/e2e-dev-harness/**` (5 �?deleted)
- roadmap doc (6 �?mark U6 �? milestone M5 done)

CLAUDE.md mandate: Stage 2b/3 edit existing symbols (`resolveCommand`, installer functions, `NodeInstallerTests`) �?run `gitnexus_impact` before editing (index refresh first). Stage 5 is pure deletion of a self-contained tree (impact = the parity audit itself).

---

## 7. Risks

- **R1 �?pip entry breaks if delete precedes pyproject switch.** Mitigated by the Stage 2b�? ordering invariant (§3) baked into the plan.
- **R2 �?installer hook-path rewrite wrong on Windows.** Mitigated by installer test asserting the materialized command string contains the abs scripts dir + forward/back-slash tolerance.
- **R3 �?residual legacy import surfaces only at runtime, not import-time.** Mitigated by Stage 5 post-delete full-suite + grep gate, plus the worker-skill independence evidence (§2).
- **R4 �?dispatch broken (env-wide).** Units land **inline** + post-hoc `/code-review`; no subagent two-stage. (Cross-cutting constraint, unchanged.)

---

## 8. Deferred / out of scope (recorded for recovery)
- session-checkpoint hook (U7-deferred) �?recover from `session_checkpoint.py`.
- recover / gc / timeline (`execution_trace.py`, `gc_run.py`) �?§5/§6/§16.
- `dir_graph.py` �?§16 (separate contract feature).
All recoverable post-delete via `git show <pre-delete-sha>:skills/e2e-dev-harness/scripts/<file>`.

---

## 9. Next step
`superpowers:writing-plans` �?staged TDD plan honoring the Stage 2b�? ordering invariant, then inline execution with per-stage commits.
