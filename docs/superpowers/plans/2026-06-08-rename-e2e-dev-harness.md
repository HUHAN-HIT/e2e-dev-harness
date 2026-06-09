# Rename e2e-dev-harness �?e2e-dev-harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the `e2e-dev-harness` skill to its canonical name `e2e-dev-harness` across the entire repo �?skill directory, internal Python package, entry/hook scripts, Node installer/CLI, worker skills, both test suites, and all docs (living + historical).

**Architecture:** This is a mechanical multi-layer rename, not a behavior change. There are **no code-level `_e2e-dev-harness` symbols** (verified: zero `def *_e2e-dev-harness` / `class *e2e-dev-harness`), so the work is `git mv` (preserve history) + ordered token substitution + dual-suite verification. The existing Python (`pytest`) and Node (`node --test`) suites are the red/green oracle: every phase ends green, or it is not done.

**Tech Stack:** Python 3 (pytest, setuptools/pyproject), Node.js (`node --test`), git, bash (git-bash on win32 �?forward slashes, `sed -i` works).

**Canonical name mapping (authoritative):**

| Old token | New token | Notes |
|---|---|---|
| `skills/e2e-dev-harness/` (dir) | `skills/e2e-dev-harness/` | `git mv` |
| `e2e_dev_harness.py` (entry) | `e2e_dev_harness.py` | `git mv` |
| `e2e_harness/` (py package) | `e2e_harness/` | `git mv`; package renamed to avoid PyPI/global namespace collision |
| `phase_guard.py` | `phase_guard.py` | `git mv` |
| `stop_guard.py` | `stop_guard.py` | `git mv` |
| `e2e_dev_harness` (token) | `e2e_dev_harness` | replace **before** `e2e_harness` |
| `e2e-dev-harness` (kebab) | `e2e-dev-harness` | replace **before** `e2e-dev-harness` |
| `e2e_harness` (token/import) | `e2e_harness` | |
| `phase_guard` / `stop_guard` (token) | `phase_guard` / `stop_guard` | |
| `__e2e_harness_SCRIPTS__` | `__HARNESS_SCRIPTS__` | Node placeholder |
| console script `e2e-dev-harness` | **deleted** | keep `e2e-dev-harness`/`e2eh`; never add bare `e2e-harness` (collides with Node bin) |
| SKILL title "E2E Dev Harness e2e-dev-harness" | "E2E Dev Harness" | |

**Token replacement order (CRITICAL �?specific before general):**
1. `e2e_dev_harness` �?`e2e_dev_harness`
2. `e2e-dev-harness` �?`e2e-dev-harness`
3. `phase_guard` �?`phase_guard`
4. `stop_guard` �?`stop_guard`
5. `__e2e_harness_SCRIPTS__` �?`__HARNESS_SCRIPTS__`
6. `e2e_harness` �?`e2e_harness`
7. (docs only, manual) bare `e2e-dev-harness` product references �?`e2e-dev-harness`

> Names that must NOT change: Node package/CLI `e2e-harness` (`package.json` name, `bin/e2e-harness.js`); env vars `E2E_HARNESS_HOME` / `E2E_HARNESS_PYTHON`; `.harness-env.json`.

---

## Task 0: Branch + green baseline

**Files:** none (setup only)

- [ ] **Step 1: Create rename branch**

```bash
git checkout -b rename/e2e-dev-harness
```

- [ ] **Step 2: Record Python baseline (must be green before we touch anything)**

Run:
```bash
python -m pytest skills/e2e-dev-harness/tests tests/test_node_installer.py -q
```
Expected: all pass (note the count, e.g. "NN passed").

- [ ] **Step 3: Record Node baseline**

Run:
```bash
node --test test/
```
Expected: all pass. If either suite is red here, STOP and fix/report before renaming �?a red baseline makes the rename unverifiable.

---

## Task 1: Move directories and files (`git mv`, preserve history)

**Files:**
- Move: `skills/e2e-dev-harness/` �?`skills/e2e-dev-harness/`
- Move: `�?scripts/e2e_dev_harness.py` �?`�?scripts/e2e_dev_harness.py`
- Move: `�?scripts/e2e_harness/` �?`�?scripts/e2e_harness/`
- Move: `�?scripts/e2e_harness/adapters/hooks/phase_guard.py` �?`�?phase_guard.py`
- Move: `�?scripts/e2e_harness/adapters/hooks/stop_guard.py` �?`�?stop_guard.py`

- [ ] **Step 1: Rename the skill directory**

```bash
git mv skills/e2e-dev-harness skills/e2e-dev-harness
```

- [ ] **Step 2: Rename the entry script and Python package**

```bash
git mv skills/e2e-dev-harness/scripts/e2e_dev_harness.py skills/e2e-dev-harness/scripts/e2e_dev_harness.py
git mv skills/e2e-dev-harness/scripts/e2e_harness skills/e2e-dev-harness/scripts/e2e_harness
```

- [ ] **Step 3: Rename the two hook scripts**

```bash
git mv skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/phase_guard.py skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/phase_guard.py
git mv skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/stop_guard.py skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/stop_guard.py
```

- [ ] **Step 4: Verify the tree shape**

Run:
```bash
ls skills/e2e-dev-harness/scripts/ && ls skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/
```
Expected: `e2e_dev_harness.py` + `e2e_harness/` present; hooks dir shows `phase_guard.py` and `stop_guard.py` (no `_e2e-dev-harness`). Imports are now broken �?that is expected; Task 2 fixes them.

- [ ] **Step 5: Commit the moves**

```bash
git add -A
git commit -m "refactor(rename): git mv e2e-dev-harness skill, e2e_harness pkg, _e2e-dev-harness hooks to canonical names"
```

---

## Task 2: Fix Python internals (imports + filename references inside the skill)

**Files:**
- Modify: every `.py` under `skills/e2e-dev-harness/scripts/` and `skills/e2e-dev-harness/tests/` referencing old tokens (�?9 import files; 0 code symbols).

- [ ] **Step 1: Apply ordered token substitution inside the skill tree**

```bash
cd skills/e2e-dev-harness
files=$(git grep -lIE "e2e_dev_harness|e2e_harness|phase_guard|stop_guard" -- . )
for f in $files; do
  sed -i \
    -e 's/e2e_dev_harness/e2e_dev_harness/g' \
    -e 's/phase_guard/phase_guard/g' \
    -e 's/stop_guard/stop_guard/g' \
    -e 's/e2e_harness/e2e_harness/g' "$f"
done
cd ../..
```

- [ ] **Step 2: Guard grep �?no old python tokens remain in the skill tree**

Run:
```bash
git grep -nI "e2e_harness\|e2e_dev_harness\|phase_guard\|stop_guard" -- skills/e2e-dev-harness/scripts skills/e2e-dev-harness/tests
```
Expected: **no output**.

- [ ] **Step 3: Run the Python suite against the new paths**

Run:
```bash
python -m pytest skills/e2e-dev-harness/tests -q
```
Expected: same pass count as Task 0 Step 2 (minus the node-installer file, which Task 6 covers). If `test_skill_md.py` fails on the `name:` field, that is fixed in Task 5 �?note it and continue; otherwise all green.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(rename): repoint Python imports e2e_harness->e2e_harness, drop _e2e-dev-harness in skill"
```

---

## Task 3: SKILL.md (main skill identity)

**Files:**
- Modify: `skills/e2e-dev-harness/SKILL.md`

- [ ] **Step 1: Rewrite frontmatter, title, and command paths**

Edit `skills/e2e-dev-harness/SKILL.md`:
- Frontmatter line 2: `name: e2e-dev-harness` �?`name: e2e-dev-harness`
- Frontmatter `description:` �?drop "(replaces the retired e2e-dev-harness)" wording; new text:
  `description: Default canonical multi-agent delivery harness. Use when a feature/bugfix/refactor needs a workflow that reliably runs to completion �?clarification, TDD, review, verification �?with a single source of truth, declarative tier-scaled gates, and worker subagents that self-load Superpowers skills.`
- Title line 6: `# E2E Dev Harness e2e-dev-harness` �?`# E2E Dev Harness`
- Body command block (`S=...`): `skills/e2e-dev-harness/scripts/e2e_dev_harness.py` �?`skills/e2e-dev-harness/scripts/e2e_dev_harness.py`

- [ ] **Step 2: Sweep any remaining tokens in this file**

```bash
sed -i -e 's/e2e_dev_harness/e2e_dev_harness/g' -e 's/e2e-dev-harness/e2e-dev-harness/g' -e 's/e2e_harness/e2e_harness/g' skills/e2e-dev-harness/SKILL.md
git grep -nI "e2e-dev-harness\|e2e_harness\|e2e-dev-harness" -- skills/e2e-dev-harness/SKILL.md
```
Expected: no `e2e_harness` / `e2e-dev-harness` / `e2e_dev_harness`. (A stray "e2e-dev-harness" only acceptable if part of prose you intentionally keep �?there should be none.)

- [ ] **Step 3: Verify SKILL.md test passes**

Run:
```bash
python -m pytest skills/e2e-dev-harness/tests/test_skill_md.py -q
```
Expected: PASS (asserts `name: e2e-dev-harness`).

- [ ] **Step 4: Commit**

```bash
git add skills/e2e-dev-harness/SKILL.md
git commit -m "refactor(rename): SKILL.md identity e2e-dev-harness -> e2e-dev-harness"
```

---

## Task 4: pyproject.toml (package discovery + console scripts)

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit the four affected blocks**

In `pyproject.toml`:
- `[project.scripts]` �?set to exactly:
  ```toml
  e2e-dev-harness = "e2e_harness.cli.main:main"
  e2eh = "e2e_harness.cli.main:main"
  ```
  (Delete the `e2e-dev-harness = …` line. Do NOT add a bare `e2e-harness` script �?it collides with the Node CLI on PATH.)
- `package-dir`: `{ "" = "skills/e2e-dev-harness/scripts" }` �?`{ "" = "skills/e2e-dev-harness/scripts" }`
- `packages = { find = { where = ["skills/e2e-dev-harness/scripts"], include = ["e2e_harness*"] } }` �?`where = ["skills/e2e-dev-harness/scripts"]`, `include = ["e2e_harness*"]`

- [ ] **Step 2: Guard grep**

```bash
git grep -nI "e2e_harness\|e2e-dev-harness\|e2e-dev-harness" -- pyproject.toml
```
Expected: no output.

- [ ] **Step 3: Verify package builds/discovers (editable install dry check)**

Run:
```bash
python -m pip install -e . --no-build-isolation --dry-run 2>&1 | tail -5 || python -c "import tomllib,sys; tomllib.load(open('pyproject.toml','rb')); print('pyproject parses OK')"
```
Expected: pyproject parses; if pip dry-run runs, no "package directory ... does not exist" error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "refactor(rename): pyproject pkg path/discovery + drop e2e-dev-harness script"
```

---

## Task 5: Worker skills (6 × SKILL.md)

**Files:**
- Modify: `skills/e2e-harness-clarification/SKILL.md`, `�?completion`, `�?implementation`, `�?planning`, `�?review`, `�?tdd-red` (all `/SKILL.md`)

- [ ] **Step 1: Substitute path + heading tokens across all six**

```bash
for f in skills/e2e-harness-*/SKILL.md; do
  sed -i \
    -e 's/e2e_dev_harness/e2e_dev_harness/g' \
    -e 's/e2e-dev-harness/e2e-dev-harness/g' \
    -e 's/(e2e-dev-harness)/(e2e-dev-harness)/g' \
    -e 's/## e2e-dev-harness 契约/## 契约/g' \
    -e 's/e2e_harness/e2e_harness/g' "$f"
done
```

- [ ] **Step 2: Guard grep**

```bash
git grep -nI "e2e-dev-harness\|e2e_dev_harness\|e2e_harness" -- skills/e2e-harness-*/SKILL.md
```
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add skills/e2e-harness-*/SKILL.md
git commit -m "refactor(rename): worker skills point at e2e-dev-harness/e2e_dev_harness.py"
```

---

## Task 6: Node installer / CLI / lib + hooks placeholder

**Files:**
- Modify: `lib/paths.js`, `lib/install.js`, `lib/lifecycle.js`, `lib/resolve.js`, `lib/init.js`, `lib/hooks.js`, `bin/e2e-harness.js`, `tools/install-e2e-dev-harness.mjs`, `tools/clean-pack.mjs`, `tools/pre-merge-check.mjs`, `package.json`

- [ ] **Step 1: Substitute tokens across the Node layer (NOT the Node CLI name)**

```bash
for f in lib/paths.js lib/install.js lib/lifecycle.js lib/resolve.js lib/init.js lib/hooks.js bin/e2e-harness.js tools/install-e2e-dev-harness.mjs tools/clean-pack.mjs tools/pre-merge-check.mjs package.json; do
  sed -i \
    -e 's/e2e_dev_harness/e2e_dev_harness/g' \
    -e 's/e2e-dev-harness/e2e-dev-harness/g' \
    -e 's/phase_guard/phase_guard/g' \
    -e 's/stop_guard/stop_guard/g' \
    -e 's/__e2e_harness_SCRIPTS__/__HARNESS_SCRIPTS__/g' \
    -e 's/e2e_harness/e2e_harness/g' "$f"
done
```

- [ ] **Step 2: Sanity-check the Node CLI name survived**

```bash
git grep -nI "\"name\": \"e2e-harness\"" -- package.json && git grep -nI "e2e-harness <command>" -- bin/e2e-harness.js
```
Expected: both still match (the `e2e-harness` CLI identity is intact).

- [ ] **Step 3: Guard grep �?old tokens gone from Node layer**

```bash
git grep -nI "e2e_harness\|e2e-dev-harness\|e2e_dev_harness\|e2e_harness\|phase_guard\|stop_guard" -- lib/ bin/ tools/ package.json
```
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add lib/ bin/ tools/ package.json
git commit -m "refactor(rename): Node installer/CLI/lib + placeholder to e2e-dev-harness/e2e_harness"
```

---

## Task 7: Update both test suites to the new names

**Files:**
- Modify: `test/hooks.test.js`, `test/install.test.js`, `test/init.test.js`, `test/paths.test.js`, `test/resolve.test.js`, `test/lifecycle.test.js`, `test/pre-merge-check.test.js`, `tests/test_node_installer.py`

- [ ] **Step 1: Substitute tokens in Node + Python installer tests**

```bash
for f in test/*.test.js tests/test_node_installer.py; do
  sed -i \
    -e 's/e2e_dev_harness/e2e_dev_harness/g' \
    -e 's/e2e-dev-harness/e2e-dev-harness/g' \
    -e 's/phase_guard/phase_guard/g' \
    -e 's/stop_guard/stop_guard/g' \
    -e 's/__e2e_harness_SCRIPTS__/__HARNESS_SCRIPTS__/g' \
    -e 's/e2e_harness/e2e_harness/g' "$f"
done
```

- [ ] **Step 2: Guard grep across all tests**

```bash
git grep -nI "e2e_harness\|e2e-dev-harness\|e2e_dev_harness\|e2e_harness\|phase_guard\|stop_guard" -- test/ tests/
```
Expected: no output.

- [ ] **Step 3: Run Node suite**

Run:
```bash
node --test test/
```
Expected: all pass (same count as Task 0 Step 3).

- [ ] **Step 4: Run full Python suite (skill + node-installer)**

Run:
```bash
python -m pytest skills/e2e-dev-harness/tests tests/test_node_installer.py -q
```
Expected: all pass (same count as Task 0 Step 2).

- [ ] **Step 5: Commit**

```bash
git add test/ tests/
git commit -m "test(rename): update Node + Python installer suites to canonical names"
```

---

## Task 8: Living docs (README / MIGRATION / CHANGELOG)

**Files:**
- Modify: `README.md`, `MIGRATION.md`, `CHANGELOG.md`

- [ ] **Step 1: Substitute product/code tokens**

```bash
for f in README.md MIGRATION.md CHANGELOG.md; do
  sed -i \
    -e 's/e2e_dev_harness/e2e_dev_harness/g' \
    -e 's/e2e-dev-harness/e2e-dev-harness/g' \
    -e 's/phase_guard/phase_guard/g' \
    -e 's/stop_guard/stop_guard/g' \
    -e 's/e2e_harness/e2e_harness/g' \
    -e 's/`e2e-dev-harness`[^`]*//g' "$f"
done
```

- [ ] **Step 2: Manual edits these tools cannot do safely**

- `CHANGELOG.md`: add a new top entry:
  `**Rename: e2e-dev-harness promoted to canonical e2e-dev-harness; Python package e2e_harness �?e2e_harness; entry/hook scripts drop _e2e-dev-harness; console script e2e-dev-harness removed (e2e-dev-harness/e2eh retained).**`
- `MIGRATION.md`: fix the hook mapping table rows so the right column reads `scripts/e2e_harness/adapters/hooks/phase_guard.py` and `�?stop_guard.py`; fix the title's right side to `e2e-dev-harness`.
- README: confirm the directory tree block shows `skills/e2e-dev-harness/`, `e2e_dev_harness.py`, `e2e_harness/`.

- [ ] **Step 3: Guard grep**

```bash
git grep -nI "e2e_harness\|e2e-dev-harness\|e2e_dev_harness\|e2e-dev-harness" -- README.md MIGRATION.md CHANGELOG.md
```
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add README.md MIGRATION.md CHANGELOG.md
git commit -m "docs(rename): living docs to e2e-dev-harness / e2e_harness"
```

---

## Task 9: Historical docs (specs / plans / handoff) �?content rewrite

**Files:**
- Modify (content only): `docs/superpowers/specs/*e2e-dev-harness*.md`, `docs/superpowers/plans/*e2e-dev-harness*.md`, `docs/superpowers/HANDOFF-e2e-dev-harness.md`, and `docs/*harness*.md` that reference old tokens.

> Decision baked in: rewrite the **product/code tokens** inside historical docs, but **keep dated filenames intact** (e.g. `2026-06-07-e2e-dev-harness-redesign-design.md` stays �?renaming it would break cross-links and git history of those records). Bare milestone tokens like `e2e-dev-harness-m2` (branch/milestone labels) are left as-is unless they are clearly the product name in prose.

- [ ] **Step 1: Substitute code/product tokens across historical docs**

```bash
files=$(git grep -lI "e2e-dev-harness\|e2e_dev_harness\|e2e_harness\|phase_guard\|stop_guard" -- docs/)
for f in $files; do
  sed -i \
    -e 's/e2e_dev_harness/e2e_dev_harness/g' \
    -e 's/e2e-dev-harness/e2e-dev-harness/g' \
    -e 's/phase_guard/phase_guard/g' \
    -e 's/stop_guard/stop_guard/g' \
    -e 's/e2e_harness/e2e_harness/g' "$f"
done
```

- [ ] **Step 2: Guard grep (code/product tokens cleared; bare `e2e-dev-harness` filename refs may remain by design)**

```bash
git grep -nI "e2e_harness\|e2e-dev-harness\|e2e_dev_harness\|phase_guard\|stop_guard" -- docs/
```
Expected: no output. (Then review remaining `e2e-dev-harness` hits with `git grep -nI "e2e-dev-harness" -- docs/` and confirm each is a dated filename/milestone label intentionally kept.)

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs(rename): rewrite historical specs/plans/handoff product+code tokens"
```

---

## Task 10: Whole-repo verification + smoke test

**Files:** none (verification only)

- [ ] **Step 1: Final repo-wide guard grep**

Run:
```bash
git grep -nI "e2e_harness\|e2e-dev-harness\|e2e_dev_harness\|phase_guard\|stop_guard\|__e2e_harness_SCRIPTS__\|e2e-dev-harness"
```
Expected: **no output** anywhere in the repo.

- [ ] **Step 2: Full Python suite**

Run:
```bash
python -m pytest skills/e2e-dev-harness/tests tests/test_node_installer.py -q
```
Expected: all pass, count matches Task 0.

- [ ] **Step 3: Full Node suite**

Run:
```bash
node --test test/
```
Expected: all pass, count matches Task 0.

- [ ] **Step 4: Repo pre-merge gate**

Run:
```bash
node tools/pre-merge-check.mjs
```
Expected: green (it invokes the pytest path that now points at `skills/e2e-dev-harness/tests`).

- [ ] **Step 5: End-to-end CLI smoke**

Run:
```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py start --repo . --feature smoke --request "rename smoke test"
```
Expected: creates a run-state and prints navigation map without import errors. Clean up any scratch run-state it created (`git status` should show no unintended tracked changes).

- [ ] **Step 6: GitNexus change scope check (per project CLAUDE.md)**

Run `gitnexus_detect_changes(scope="unstaged")` (or `--staged`) and confirm the affected symbols/flows are exactly the renamed surface �?no unexpected blast radius.

- [ ] **Step 7: Final commit if anything pending**

```bash
git status
# commit only if Step 5/6 surfaced fixes
```

---

## Notes & risks (carry into execution)

1. **Already-installed old skill.** `~/.claude/skills/` may still hold the retired `e2e-dev-harness` (from the global registry). After merge, the user must reinstall (`e2e-harness install`) �?the installer backs up the prior copy automatically. Not a repo change; surface it in the PR description.
2. **Console-script collision is intentional.** The Node CLI owns `e2e-harness` on PATH; the Python package deliberately ships only `e2e-dev-harness`/`e2eh`. Never reintroduce a bare `e2e-harness` Python script.
3. **`sed` ordering already encoded.** Every batch lists `e2e_dev_harness`/`e2e-dev-harness` substitutions before `e2e_harness` to avoid corrupting the longer tokens (they contain `e2e_harness`/`e2e-dev-harness` as substrings).
4. **win32 bash.** All commands use forward slashes and git-bash `sed -i`. If running under PowerShell instead, switch to the project's bash shell first.
5. **No run-state migration needed.** Verified: `e2e_harness` is not used as a persisted schema/version string in run-state, so existing/new run-states are unaffected by the package rename.
