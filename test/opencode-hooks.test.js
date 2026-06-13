const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { materializeOpencodePlugin } = require('../lib/opencode-hooks');

function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'e2eh-ocp-')); }

// A fake installed skill home carrying the opencode plugin template with the placeholder.
function fakeSkillHome() {
  const home = tmp();
  const hooksDir = path.join(home, 'hooks');
  fs.mkdirSync(hooksDir, { recursive: true });
  const tpl = [
    'const { spawnSync } = require("child_process");',
    'const PHASE_GUARD = "__HARNESS_SCRIPTS__/e2e_harness/adapters/hooks/phase_guard.py";',
    'module.exports.E2eDevHarnessPlugin = async () => ({',
    '  "tool.execute.before": async (input, output) => {},',
    '});',
  ].join('\n');
  fs.writeFileSync(path.join(hooksDir, 'opencode-plugin.example.js'), tpl);
  return home;
}

test('materializeOpencodePlugin writes the plugin into .opencode/plugins with the scripts dir substituted', () => {
  const home = fakeSkillHome();
  const projectRoot = tmp();
  const res = materializeOpencodePlugin({ skillHome: home, projectRoot });

  const pluginPath = path.join(projectRoot, '.opencode', 'plugins', 'e2e-dev-harness.js');
  assert.strictEqual(res.pluginPath, pluginPath);
  assert.ok(fs.existsSync(pluginPath));
  const body = fs.readFileSync(pluginPath, 'utf8');
  assert.ok(!body.includes('__HARNESS_SCRIPTS__'), 'placeholder must be substituted');
  assert.ok(!body.includes('\\'), 'plugin must embed a forward-slash scripts path (bash/Bun-safe)');
  const posixScripts = path.join(home, 'scripts').replace(/\\/g, '/');
  assert.ok(body.includes(`${posixScripts}/e2e_harness/adapters/hooks/phase_guard.py`));
  assert.strictEqual(res.added, 1);
  assert.strictEqual(res.alreadyPresent, 0);
});

test('materializeOpencodePlugin is idempotent: a second run adds nothing', () => {
  const home = fakeSkillHome();
  const projectRoot = tmp();
  materializeOpencodePlugin({ skillHome: home, projectRoot });
  const second = materializeOpencodePlugin({ skillHome: home, projectRoot });
  assert.strictEqual(second.added, 0);
  assert.strictEqual(second.alreadyPresent, 1);
});

test('materializeOpencodePlugin dryRun writes nothing but reports the plan', () => {
  const home = fakeSkillHome();
  const projectRoot = tmp();
  const res = materializeOpencodePlugin({ skillHome: home, projectRoot, dryRun: true });
  assert.strictEqual(res.added, 1);
  assert.ok(!fs.existsSync(path.join(projectRoot, '.opencode', 'plugins', 'e2e-dev-harness.js')));
});

test('materializeOpencodePlugin backs up an existing plugin before overwriting', () => {
  const home = fakeSkillHome();
  const projectRoot = tmp();
  const pluginsDir = path.join(projectRoot, '.opencode', 'plugins');
  fs.mkdirSync(pluginsDir, { recursive: true });
  fs.writeFileSync(path.join(pluginsDir, 'e2e-dev-harness.js'), 'old plugin body');

  const res = materializeOpencodePlugin({ skillHome: home, projectRoot });
  assert.ok(res.backup && fs.existsSync(res.backup), 'an existing plugin must be backed up');
  assert.strictEqual(fs.readFileSync(res.backup, 'utf8'), 'old plugin body');
  assert.strictEqual(res.added, 1);
});
