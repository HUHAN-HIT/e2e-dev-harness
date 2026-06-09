# U6 �?M5 Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (subagent dispatch is broken env-wide �?inline execution + post-hoc `/code-review`). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make e2e-dev-harness the sole, default harness �?switch Node + Python entry points to e2e-dev-harness, ship migration docs + CHANGELOG 0.1.0�?.2.0, then delete the legacy skill �?proving zero capability loss.

**Architecture:** Audit-first (方案 A): the committed parity table (design §2) gates the cutover. Entry points flip **before** deletion; the hard invariant is **Stage 2b (pyproject→e2e-dev-harness) precedes Stage 5 (delete legacy)**, else pip console-scripts break. Each stage is its own commit, reversible by revert.

**Tech Stack:** Python (setuptools/pyproject, pytest), Node (npm bin shim, install mjs), Bash smoke tests.

**Design doc:** `docs/superpowers/specs/2026-06-08-e2e-dev-harness-u6-cutover-design.md`

---

## Pre-flight (read once)

- e2e-dev-harness console entry callable: `e2e_harness.cli.main:main` (verified). Package root: `skills/e2e-dev-harness/scripts/`, package `e2e_harness`.
- npm side already at `version 0.2.0`, `files`→e2e-dev-harness, `lib/resolve.js` dispatches to `e2e_dev_harness.py` (working-tree `M`, uncommitted).
- pyproject `[project.scripts]` still �?legacy `e2e_dev_harness:main`.
- Full e2e-dev-harness suite baseline: `cd skills/e2e-dev-harness && python -m pytest tests/ -q` �?**223 passed**.

---

### Task 1: Stage 2a �?commit the npm cutover working set (after validation)

**Files (Modify, already in working tree):** `package.json`, `lib/install.js`, `lib/lifecycle.js`, `lib/paths.js`, `lib/resolve.js`, `bin/e2e-harness.js`, `tools/install-e2e-dev-harness.mjs`, `tests/test_node_installer.py`, `test/*.test.js`; **Create (working tree):** `.npmignore`, `tools/clean-pack.mjs`.

- [ ] **Step 1: Run the Node test suite**

Run: `npm test`
Expected: PASS (all node `test/*.test.js`). If a test references legacy paths, fix the test to expect the e2e-dev-harness surface, re-run.

- [ ] **Step 2: Run the Python installer test**

Run: `python -m pytest tests/test_node_installer.py -q`
Expected: PASS.

- [ ] **Step 3: npm pack dry-run (verify only e2e-dev-harness + bin/lib ship)**

Run: `npm pack --dry-run 2>&1 | grep -E 'e2e-dev-harness/|e2e-dev-harness/|^npm notice'`
Expected: tarball lists `skills/e2e-dev-harness/...`, `bin/`, `lib/`; **no** `skills/e2e-dev-harness/` legacy paths.

- [ ] **Step 4: bin smoke (resolve a e2e-dev-harness verb through the Node shim)**

Run: `node bin/e2e-harness.js validate-pipeline --pipeline skills/e2e-dev-harness/pipelines/minimal.yaml`
Expected: exits 0 with e2e-dev-harness validate-pipeline JSON (proves Node→`e2e_dev_harness.py` dispatch works).

- [ ] **Step 5: Commit**

```bash
git add package.json lib/ bin/ tools/install-e2e-dev-harness.mjs tools/clean-pack.mjs tests/test_node_installer.py test/ .npmignore
git commit -m "feat(e2e-dev-harness): U6 Stage 2a �?npm installer cuts over to e2e-dev-harness (0.2.0)"
```

---

### Task 2: Stage 2b �?switch pyproject Python entry to e2e-dev-harness

**Files (Modify):** `pyproject.toml` (`[project.scripts]`, `[tool.setuptools]` package-dir/packages).

- [ ] **Step 1: Run gitnexus impact on the legacy entry (CLAUDE.md mandate)**

```bash
cd skills/e2e-dev-harness && npx gitnexus analyze   # refresh stale index
```
Then via MCP: `gitnexus_impact({target: "main", direction: "upstream", repo: "e2e-dev-workflow", file_path: "skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py"})`. Expected: low blast radius (entry callable). Report before editing.

- [ ] **Step 2: Rewrite the entry + package mapping**

In `pyproject.toml` replace the legacy `[project.scripts]` block and the `[tool.setuptools]` `package-dir`/`packages` lines:

```toml
[project.scripts]
e2e-dev-harness = "e2e_harness.cli.main:main"
e2e-dev-harness = "e2e_harness.cli.main:main"
e2eh = "e2e_harness.cli.main:main"

[tool.setuptools]
package-dir = { "" = "skills/e2e-dev-harness/scripts" }
packages = { find = { where = ["skills/e2e-dev-harness/scripts"], include = ["e2e_harness*"] } }
```

Also update `[project]` `name`/`description` to the e2e-dev-harness surface and drop the legacy `py-modules`/`e2e_dev_harness` references (delete the `"e2e_dev_harness"` line near pyproject:50).

- [ ] **Step 3: Build + install smoke in an isolated venv**

```bash
python -m venv /tmp/u6venv && /tmp/u6venv/Scripts/python -m pip install -q -e . && \
/tmp/u6venv/Scripts/e2e-dev-harness start --repo /tmp/u6smoke --feature demo --request "x"
```
Expected: console script runs, emits `start` JSON with a `run_state` path. (Windows venv path uses `Scripts/`; on POSIX use `bin/`.)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(e2e-dev-harness): U6 Stage 2b �?pyproject console-scripts retarget to e2e-dev-harness (e2e_harness.cli.main:main)"
```

---

### Task 3: Stage 2c �?mark e2e-dev-harness SKILL.md as the default harness

**Files (Modify):** `skills/e2e-dev-harness/SKILL.md` (frontmatter description).

- [ ] **Step 1: Edit the description to claim canonical/default status**

Append to the e2e-dev-harness `SKILL.md` frontmatter `description:` the clause ` (default, canonical harness �?replaces the retired e2e-dev-harness)`. If a project/global pointer file names the legacy skill, repoint it to `e2e-dev-harness`.

- [ ] **Step 2: Commit**

```bash
git add skills/e2e-dev-harness/SKILL.md
git commit -m "feat(e2e-dev-harness): U6 Stage 2c �?e2e-dev-harness SKILL.md is the default harness"
```

---

### Task 4: Stage 3 �?installer wires the U7 e2e-dev-harness hooks

**Files:** Modify `tools/install-e2e-dev-harness.mjs` (add hook-config materialization); Test `tests/test_node_installer.py` (or a sibling Node test) asserting the rewritten command lands.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_node_installer.py` (Python installer test harness) a case asserting that after `--yes` install, the materialized claude settings contains the e2e-dev-harness hook command with the absolute installed scripts dir (no `__e2e_harness_SCRIPTS__` placeholder left):

```python
def test_yes_installs_e2e-dev-harness_phase_and_stop_hooks(self):
    home = self._run_install_yes()  # existing helper that performs a --yes install into a temp home
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    pre = json.dumps(settings["hooks"]["PreToolUse"])
    stop = json.dumps(settings["hooks"]["Stop"])
    self.assertIn("phase_guard.py", pre)
    self.assertIn("stop_guard.py", stop)
    self.assertNotIn("__e2e_harness_SCRIPTS__", pre + stop)
    self.assertIn(str(home), pre)  # abs path rewritten in
```

(If `_run_install_yes` does not exist, adapt to the existing yes-install helper used by `test_yes_copies_skill_and_writes_manifest`.)

- [ ] **Step 2: Run it �?expect fail**

Run: `python -m pytest tests/test_node_installer.py -k e2e-dev-harness_phase_and_stop -q`
Expected: FAIL (installer does not yet write hooks, or placeholder remains).

- [ ] **Step 3: Implement hook materialization in the installer**

In `tools/install-e2e-dev-harness.mjs`, after the skill copy, read `skills/e2e-dev-harness/hooks/claude-code-settings.example.json`, replace `__e2e_harness_SCRIPTS__` with the installed absolute scripts dir (`path.join(installedSkillDir, 'scripts')`), and merge its `hooks.PreToolUse`/`hooks.Stop` into the target `~/.claude/settings.json` (create/extend, don't clobber existing unrelated hooks). Mirror for opencode if the installer supports that runtime.

- [ ] **Step 4: Run the test �?expect pass**

Run: `python -m pytest tests/test_node_installer.py -k e2e-dev-harness_phase_and_stop -q`
Expected: PASS. Then full installer test: `python -m pytest tests/test_node_installer.py -q` �?PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/install-e2e-dev-harness.mjs tests/test_node_installer.py
git commit -m "feat(e2e-dev-harness): U6 Stage 3 �?installer wires U7 phase_guard + stop_guard"
```

---

### Task 5: Stage 4 �?migration docs + CHANGELOG

**Files:** Create `MIGRATION.md`; Create/Modify `CHANGELOG.md`.

- [ ] **Step 1: Write `MIGRATION.md`**

Sections: (a) what changed (35�? verbs table from design §6; entry-point rename `e2e-dev-harness`→e2e-dev-harness, same alias names); (b) parity table (reference design §2); (c) **Deferred / recoverable** list �?session-checkpoint, recover/gc/timeline, dir_graph �?each with `git show <pre-delete-sha>:skills/e2e-dev-harness/scripts/<file>` recovery hint; (d) hooks: `phase_guard`→`phase_guard`, `harness_stop_guard`→`stop_guard`.

- [ ] **Step 2: Write `CHANGELOG.md` 0.2.0 entry**

Under `## [0.2.0] - 2026-06-08`: Added (e2e-dev-harness harness default, declarative tier pipelines, U7 hook layer); Changed (CLI 35�? verbs, entry points �?e2e-dev-harness); Removed (legacy `skills/e2e-dev-harness/`); Deferred (recover/gc/timeline/dir_graph/session-checkpoint). Note prior baseline `## [0.1.0]` if absent.

- [ ] **Step 3: Commit**

```bash
git add MIGRATION.md CHANGELOG.md
git commit -m "docs(e2e-dev-harness): U6 Stage 4 �?MIGRATION.md + CHANGELOG 0.2.0"
```

---

### Task 6: Stage 5 �?delete legacy (dedicated commit) + verify

**Files:** Delete `skills/e2e-dev-harness/**`; remove any residual legacy-only pyproject artifacts.

- [ ] **Step 1: Record the pre-delete SHA (for recovery hints)**

Run: `git rev-parse HEAD` �?note it; ensure MIGRATION.md recovery hints reference it (amend Stage 4 doc if needed).

- [ ] **Step 2: Delete the legacy tree**

Run: `git rm -r skills/e2e-dev-harness`
Expected: ~70 scripts + references/agents/hooks removed.

- [ ] **Step 3: Full e2e-dev-harness suite must stay green (vendor self-containment proof)**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/ -q`
Expected: **223 passed** (identical to baseline �?proves no runtime dependency on the deleted tree).

- [ ] **Step 4: Grep for residual runtime references**

Run: `grep -rnE 'e2e-dev-harness/scripts|e2e_dev_harness\b' --include='*.py' --include='*.js' --include='*.mjs' --include='*.toml' --include='*.json' . | grep -v node_modules | grep -v '/docs/'`
Expected: no runtime hits (docs/historical references are fine). Fix any runtime hit before committing.

- [ ] **Step 5: Commit (dedicated)**

```bash
git add -A
git commit -m "chore(e2e-dev-harness): U6 Stage 5 �?delete legacy e2e-dev-harness skill (retired, parity covered by e2e-dev-harness)"
```

---

### Task 7: Stage 6 �?finish the branch

- [ ] **Step 1: detect_changes before completion**

Via MCP: `gitnexus_detect_changes({scope: "unstaged", repo: "e2e-dev-workflow"})` �?expect clean/low.

- [ ] **Step 2: Update roadmap �?mark U6 �?/ M5 done**

In `docs/superpowers/plans/2026-06-07-e2e-dev-harness-remaining-work-roadmap.md`: mark the U6 row �? note M5 milestone delivered (legacy retired). Commit `docs(e2e-dev-harness): U6 �?�?M5 cutover complete`.

- [ ] **Step 3: Post-hoc inline `/code-review`** of the U6 commit range; record verdict.

- [ ] **Step 4: finishing-a-development-branch**

REQUIRED SUB-SKILL: `superpowers:finishing-a-development-branch` �?verify full suite, present merge/PR options, execute choice.

---

## Self-Review

- **Spec coverage:** design §2 audit �?Task 1 pre-req (committed S1) + Task 5 MIGRATION; §5 stages �?Tasks 1�?; ordering invariant 2b�? �?Tasks 2 before 6. �?- **Ordering invariant honored:** Task 2 (pyproject→e2e-dev-harness) precedes Task 6 (delete). �?- **No placeholders:** entry callable `e2e_harness.cli.main:main` concrete; commands exact. Installer test references existing yes-install helper (adapt name on read). �?- **Type consistency:** console-script names (`e2e-dev-harness`/`e2e-dev-harness`/`e2eh`) consistent across Task 2 and MIGRATION (Task 5). Hook filenames `phase_guard.py`/`stop_guard.py` match U7. �?