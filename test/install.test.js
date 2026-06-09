const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { installToMachine, defaultBackupDir } = require('../lib/install');

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

test('skips transient cache directories while copying the skill tree', () => {
  const pkgRoot = tmp();
  const skillRoot = path.join(pkgRoot, 'skills', 'e2e-dev-harness');
  fs.mkdirSync(path.join(skillRoot, 'scripts'), { recursive: true });
  fs.mkdirSync(path.join(skillRoot, '.pytest-tmp'), { recursive: true });
  fs.mkdirSync(path.join(skillRoot, 'scripts', '__pycache__'), { recursive: true });
  fs.writeFileSync(path.join(skillRoot, 'SKILL.md'), 'skill');
  fs.writeFileSync(path.join(skillRoot, '.pytest-tmp', 'leftover.txt'), 'cache');
  fs.writeFileSync(path.join(skillRoot, 'scripts', '__pycache__', 'mod.pyc'), 'cache');

  const skillsDir = tmp();
  installToMachine({ pkgRoot, skillsDir, python: null });
  const installed = path.join(skillsDir, 'e2e-dev-harness');

  assert.ok(fs.existsSync(path.join(installed, 'SKILL.md')));
  assert.ok(!fs.existsSync(path.join(installed, '.pytest-tmp')));
  assert.ok(!fs.existsSync(path.join(installed, 'scripts', '__pycache__')));
});

test('backs up existing install OUTSIDE skillsDir', () => {
  const pkgRoot = tmp();
  fs.mkdirSync(path.join(pkgRoot, 'skills', 'e2e-dev-harness'), { recursive: true });
  fs.writeFileSync(path.join(pkgRoot, 'skills', 'e2e-dev-harness', 'SKILL.md'), 'new');
  const skillsDir = tmp();
  const existing = path.join(skillsDir, 'e2e-dev-harness');
  fs.mkdirSync(existing, { recursive: true });
  fs.writeFileSync(path.join(existing, 'marker.txt'), 'old');
  const backupDir = tmp();
  const res = installToMachine({ pkgRoot, skillsDir, python: 'python3', backupDir });
  // backup is outside skillsDir, and skillsDir no longer holds a .bak skill
  assert.ok(fs.existsSync(path.join(backupDir, 'e2e-dev-harness', 'marker.txt')));
  assert.ok(!fs.existsSync(path.join(skillsDir, 'e2e-dev-harness.bak')));
  assert.ok(fs.existsSync(path.join(existing, 'SKILL.md')));
  assert.strictEqual(res.backup, path.join(backupDir, 'e2e-dev-harness'));
});

test('defaultBackupDir is a sibling of skillsDir, not inside it', () => {
  const skillsDir = path.join('C:', 'u', '.claude', 'skills');
  const dir = defaultBackupDir(skillsDir);
  assert.ok(!dir.startsWith(skillsDir + path.sep));
  assert.strictEqual(dir, path.join('C:', 'u', '.claude', 'skill-backups'));
});
