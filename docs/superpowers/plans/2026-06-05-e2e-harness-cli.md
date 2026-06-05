# e2e-harness CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship a zero-dependency npm/npx `e2e-harness` CLI that installs the harness skill into `~/.claude/skills` and forwards subcommands to the canonical Python CLI, so hook paths never depend on which copy was run.

**Architecture:** Node bin (`bin/e2e-harness.js`) resolves a fixed `SKILL_HOME` (`~/.claude/skills/e2e-dev-harness`, override `E2E_HARNESS_HOME`) and a Python interpreter (`.harness-env.json` → `E2E_HARNESS_PYTHON` → `python`/`python3`/`py`). `install` copies the bundled `skills/e2e-dev-harness/` tree into `SKILL_HOME` (backing up to `.bak`) and records python. All other subcommands shell out to `SKILL_HOME/scripts/e2e_dev_harness.py`.

**Tech Stack:** Node 25 (built-in `node:test`, `node:fs`, `node:child_process`), Python 3 (existing harness).

---

## File Structure

- Create `package.json` — package metadata, `bin: {"e2e-harness": "bin/e2e-harness.js"}`, `files` includes `skills/e2e-dev-harness`, `bin`, `lib`.
- Create `bin/e2e-harness.js` — argv dispatch; thin.
- Create `lib/paths.js` — `skillHome()`, `resolvePython(skillHome)`. Pure, testable.
- Create `lib/install.js` — `installToMachine({pkgRoot, skillsDir, python})`: copy, backup, write env. Testable.
- Create `test/paths.test.js`, `test/install.test.js` — node:test.
- Modify `SKILL.md` — replace `python skills/e2e-dev-harness/scripts/...` invocations with `e2e-harness <subcommand>`.

---

## Task 1: package.json

**Files:** Create `package.json`

- [ ] **Step 1: Write package.json**

```json
{
  "name": "e2e-harness",
  "version": "0.1.0",
  "description": "Installer and CLI wrapper for the e2e-dev-harness skill.",
  "bin": { "e2e-harness": "bin/e2e-harness.js" },
  "files": ["bin", "lib", "skills/e2e-dev-harness"],
  "scripts": { "test": "node --test" },
  "license": "MIT"
}
```

- [ ] **Step 2: Commit** — `git add package.json && git commit -m "feat: add e2e-harness npm package manifest"`

## Task 2: lib/paths.js (path + python resolution)

**Files:** Create `lib/paths.js`, Test `test/paths.test.js`

- [ ] **Step 1: Write failing test**

```js
// test/paths.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const os = require('node:os');
const { skillHome } = require('../lib/paths');

test('skillHome defaults to ~/.claude/skills/e2e-dev-harness', () => {
  delete process.env.E2E_HARNESS_HOME;
  assert.strictEqual(
    skillHome(),
    path.join(os.homedir(), '.claude', 'skills', 'e2e-dev-harness')
  );
});

test('skillHome honors E2E_HARNESS_HOME override', () => {
  process.env.E2E_HARNESS_HOME = path.join('C:', 'tmp', 'h');
  assert.strictEqual(skillHome(), path.join('C:', 'tmp', 'h'));
  delete process.env.E2E_HARNESS_HOME;
});
```

- [ ] **Step 2: Run, expect FAIL** — `node --test test/paths.test.js` → Cannot find module '../lib/paths'.

- [ ] **Step 3: Implement**

```js
// lib/paths.js
const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');

function skillHome() {
  return process.env.E2E_HARNESS_HOME
    || path.join(os.homedir(), '.claude', 'skills', 'e2e-dev-harness');
}

function recordedPython(home) {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(home, '.harness-env.json'), 'utf8'));
    if (data && typeof data.python === 'string') return data.python;
  } catch { /* no env file */ }
  return null;
}

function detectPython() {
  const candidates = process.platform === 'win32'
    ? ['python', 'python3', 'py']
    : ['python3', 'python'];
  for (const c of candidates) {
    try {
      execFileSync(c, ['--version'], { stdio: 'ignore' });
      return c;
    } catch { /* try next */ }
  }
  return null;
}

function resolvePython(home) {
  if (process.env.E2E_HARNESS_PYTHON) return process.env.E2E_HARNESS_PYTHON;
  return recordedPython(home) || detectPython();
}

module.exports = { skillHome, resolvePython, detectPython, recordedPython };
```

- [ ] **Step 4: Run, expect PASS** — `node --test test/paths.test.js`.

- [ ] **Step 5: Commit** — `git add lib/paths.js test/paths.test.js && git commit -m "feat: add path and python resolution for e2e-harness CLI"`

## Task 3: lib/install.js (machine install)

**Files:** Create `lib/install.js`, Test `test/install.test.js`

- [ ] **Step 1: Write failing test**

```js
// test/install.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { installToMachine } = require('../lib/install');

function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'e2eh-')); }

test('copies skill tree and writes env', () => {
  const pkgRoot = tmp();
  const src = path.join(pkgRoot, 'skills', 'e2e-dev-harness', 'scripts');
  fs.mkdirSync(src, { recursive: true });
  fs.writeFileSync(path.join(src, 'e2e_dev_harness.py'), '# stub');
  const skillsDir = tmp();
  const res = installToMachine({ pkgRoot, skillsDir, python: 'python3' });
  const dest = path.join(skillsDir, 'e2e-dev-harness', 'scripts', 'e2e_dev_harness.py');
  assert.ok(fs.existsSync(dest));
  const env = JSON.parse(fs.readFileSync(
    path.join(skillsDir, 'e2e-dev-harness', '.harness-env.json'), 'utf8'));
  assert.strictEqual(env.python, 'python3');
  assert.strictEqual(res.home, path.join(skillsDir, 'e2e-dev-harness'));
});

test('backs up existing install to .bak', () => {
  const pkgRoot = tmp();
  fs.mkdirSync(path.join(pkgRoot, 'skills', 'e2e-dev-harness'), { recursive: true });
  fs.writeFileSync(path.join(pkgRoot, 'skills', 'e2e-dev-harness', 'SKILL.md'), 'new');
  const skillsDir = tmp();
  const existing = path.join(skillsDir, 'e2e-dev-harness');
  fs.mkdirSync(existing, { recursive: true });
  fs.writeFileSync(path.join(existing, 'marker.txt'), 'old');
  installToMachine({ pkgRoot, skillsDir, python: 'python3' });
  assert.ok(fs.existsSync(path.join(skillsDir, 'e2e-dev-harness.bak', 'marker.txt')));
  assert.ok(fs.existsSync(path.join(existing, 'SKILL.md')));
});
```

- [ ] **Step 2: Run, expect FAIL** — `node --test test/install.test.js`.

- [ ] **Step 3: Implement**

```js
// lib/install.js
const fs = require('node:fs');
const path = require('node:path');

function installToMachine({ pkgRoot, skillsDir, python }) {
  const src = path.join(pkgRoot, 'skills', 'e2e-dev-harness');
  if (!fs.existsSync(src)) throw new Error(`bundled skill not found: ${src}`);
  fs.mkdirSync(skillsDir, { recursive: true });
  const home = path.join(skillsDir, 'e2e-dev-harness');
  if (fs.existsSync(home)) {
    const bak = home + '.bak';
    fs.rmSync(bak, { recursive: true, force: true });
    fs.renameSync(home, bak);
  }
  fs.cpSync(src, home, { recursive: true });
  if (python) {
    fs.writeFileSync(
      path.join(home, '.harness-env.json'),
      JSON.stringify({ python }, null, 2) + '\n'
    );
  }
  return { home };
}

module.exports = { installToMachine };
```

- [ ] **Step 4: Run, expect PASS**.

- [ ] **Step 5: Commit** — `git add lib/install.js test/install.test.js && git commit -m "feat: add machine install with backup for e2e-harness CLI"`

## Task 4: bin/e2e-harness.js (dispatch)

**Files:** Create `bin/e2e-harness.js`

- [ ] **Step 1: Implement bin**

```js
#!/usr/bin/env node
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const { skillHome, resolvePython, detectPython } = require('../lib/paths');
const { installToMachine } = require('../lib/install');

const PKG_ROOT = path.join(__dirname, '..');
const SUB_MAP = { status: 'doctor', dispatch: 'dispatch-status' };

function runPython(home, args) {
  const py = resolvePython(home);
  if (!py) { console.error('No Python interpreter found. Set E2E_HARNESS_PYTHON.'); process.exit(3); }
  const cli = path.join(home, 'scripts', 'e2e_dev_harness.py');
  const r = spawnSync(py, [cli, ...args], { stdio: 'inherit' });
  process.exit(r.status === null ? 1 : r.status);
}

function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  if (!cmd || cmd === '--help' || cmd === '-h') {
    console.log('Usage: e2e-harness <install|init|status|next|dispatch|...> [project] [opts]');
    process.exit(cmd ? 0 : 1);
  }
  if (cmd === 'install') {
    const skillsDir = path.join(os.homedir(), '.claude', 'skills');
    const python = process.env.E2E_HARNESS_PYTHON || detectPython();
    const { home } = installToMachine({ pkgRoot: PKG_ROOT, skillsDir, python });
    console.log(`Installed harness to ${home} (python=${python || 'NOT FOUND'})`);
    process.exit(0);
  }
  const home = skillHome();
  if (!fs.existsSync(home)) {
    console.error(`Harness not installed at ${home}. Run: e2e-harness install`);
    process.exit(3);
  }
  if (cmd === 'init') {
    const py = resolvePython(home);
    const installHooks = path.join(home, 'scripts', 'install_hooks.py');
    const r = spawnSync(py, [installHooks, ...rest], { stdio: 'inherit' });
    process.exit(r.status === null ? 1 : r.status);
  }
  const mapped = SUB_MAP[cmd] || cmd;
  runPython(home, [mapped, ...rest]);
}

main();
```

- [ ] **Step 2: Manual smoke** — `node bin/e2e-harness.js --help` → prints usage.

- [ ] **Step 3: Commit** — `git add bin/e2e-harness.js && git commit -m "feat: add e2e-harness bin dispatcher"`

## Task 5: End-to-end install + init regression

**Files:** none (verification)

- [ ] **Step 1: Install to machine** — Run `node bin/e2e-harness.js install`. Expected: prints install line; `~/.claude/skills/e2e-dev-harness/.harness-env.json` exists.

- [ ] **Step 2: Re-init petalpay and assert canonical path** — Run `node bin/e2e-harness.js init "C:/Users/14907/Documents/Codex/2026-05-23/petalpay" --runtime claude`, then grep `petalpay/.claude/settings.json` for `phase_guard.py`. Expected: path contains `.claude/skills/e2e-dev-harness/scripts/phase_guard.py`, NOT the dev repo path.

- [ ] **Step 3: status smoke** — `node bin/e2e-harness.js status "C:/.../petalpay" --json` runs doctor.

## Task 6: Update SKILL.md invocations

**Files:** Modify `SKILL.md`

- [ ] **Step 1:** Replace each `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py <sub> .` with `e2e-harness <sub>` and `install_hooks.py ... --runtime claude` with `e2e-harness init . --runtime claude`. Keep semantics identical.

- [ ] **Step 2: Commit** — `git add SKILL.md && git commit -m "docs: use e2e-harness CLI in SKILL.md invocations"`

## Self-Review Notes
- Spec §3.1 install/backup → Task 3. §3.2 path constants → Task 2 + bin. §3.3 command set → bin SUB_MAP + init/install. §3.5 docs → Task 6. §3.6 petalpay fix → Task 5. §5 tests → Tasks 2,3,5.
- Names consistent: `skillHome`, `resolvePython`, `installToMachine` used identically across tasks.
