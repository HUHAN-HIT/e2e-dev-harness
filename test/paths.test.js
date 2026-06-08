const { test } = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const os = require('node:os');
const { skillHome } = require('../lib/paths');

test('skillHome defaults to ~/.claude/skills/e2e-dev-harness-v2', () => {
  delete process.env.E2E_HARNESS_HOME;
  assert.strictEqual(
    skillHome(),
    path.join(os.homedir(), '.claude', 'skills', 'e2e-dev-harness-v2')
  );
});

test('skillHome honors E2E_HARNESS_HOME override', () => {
  process.env.E2E_HARNESS_HOME = path.join('C:', 'tmp', 'h');
  assert.strictEqual(skillHome(), path.join('C:', 'tmp', 'h'));
  delete process.env.E2E_HARNESS_HOME;
});
