const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { installToMachine, defaultBackupDir } = require('../lib/install');

function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'e2eh-')); }

test('copies skill tree and writes env', () => {
  const pkgRoot = tmp();
  const src = path.join(pkgRoot, 'skills', 'e2e-dev-harness-v2', 'scripts');
  fs.mkdirSync(src, { recursive: true });
  fs.writeFileSync(path.join(src, 'e2e_dev_harness_v2.py'), '# stub');
  const skillsDir = tmp();
  const res = installToMachine({ pkgRoot, skillsDir, python: 'python3' });
  const dest = path.join(skillsDir, 'e2e-dev-harness-v2', 'scripts', 'e2e_dev_harness_v2.py');
  assert.ok(fs.existsSync(dest));
  const env = JSON.parse(fs.readFileSync(
    path.join(skillsDir, 'e2e-dev-harness-v2', '.harness-env.json'), 'utf8'));
  assert.strictEqual(env.python, 'python3');
  assert.strictEqual(res.home, path.join(skillsDir, 'e2e-dev-harness-v2'));
});

test('backs up existing install OUTSIDE skillsDir', () => {
  const pkgRoot = tmp();
  fs.mkdirSync(path.join(pkgRoot, 'skills', 'e2e-dev-harness-v2'), { recursive: true });
  fs.writeFileSync(path.join(pkgRoot, 'skills', 'e2e-dev-harness-v2', 'SKILL.md'), 'new');
  const skillsDir = tmp();
  const existing = path.join(skillsDir, 'e2e-dev-harness-v2');
  fs.mkdirSync(existing, { recursive: true });
  fs.writeFileSync(path.join(existing, 'marker.txt'), 'old');
  const backupDir = tmp();
  const res = installToMachine({ pkgRoot, skillsDir, python: 'python3', backupDir });
  // backup is outside skillsDir, and skillsDir no longer holds a .bak skill
  assert.ok(fs.existsSync(path.join(backupDir, 'e2e-dev-harness-v2', 'marker.txt')));
  assert.ok(!fs.existsSync(path.join(skillsDir, 'e2e-dev-harness-v2.bak')));
  assert.ok(fs.existsSync(path.join(existing, 'SKILL.md')));
  assert.strictEqual(res.backup, path.join(backupDir, 'e2e-dev-harness-v2'));
});

test('defaultBackupDir is a sibling of skillsDir, not inside it', () => {
  const skillsDir = path.join('C:', 'u', '.claude', 'skills');
  const dir = defaultBackupDir(skillsDir);
  assert.ok(!dir.startsWith(skillsDir + path.sep));
  assert.strictEqual(dir, path.join('C:', 'u', '.claude', 'skill-backups'));
});
