const { test } = require('node:test');
const assert = require('node:assert');
const packageJson = require('../package.json');

test('pre-merge plan runs status, node tests, python tests, and GitNexus detection', async () => {
  const { buildPlan } = await import('../tools/pre-merge-check.mjs');

  assert.deepStrictEqual(
    buildPlan({ skipGitNexus: false }).map((step) => step.command),
    [
      ['git', 'status', '--short', '--branch'],
      ['npm', 'test'],
      ['python', '-m', 'pytest', 'skills/e2e-dev-harness/tests', 'tests/test_node_installer.py', '-q'],
      ['npx', 'gitnexus', 'detect-changes', '--scope', 'all', '--repo', 'e2e-dev-workflow'],
    ]
  );
});

test('pre-merge runner stops at the first failed check', async () => {
  const { runPlan } = await import('../tools/pre-merge-check.mjs');
  const seen = [];
  const plan = [
    { name: 'first', command: ['first'] },
    { name: 'second', command: ['second'] },
    { name: 'third', command: ['third'] },
  ];

  const result = runPlan(plan, {
    cwd: 'repo',
    log() {},
    error() {},
    runCommand(step, options) {
      seen.push([step.name, options.cwd]);
      return { status: step.name === 'second' ? 9 : 0 };
    },
  });

  assert.strictEqual(result.exitCode, 9);
  assert.deepStrictEqual(seen, [['first', 'repo'], ['second', 'repo']]);
});

test('pre-merge check script is included in the published package', () => {
  assert.match(packageJson.scripts['pre-merge-check'], /tools\/pre-merge-check\.mjs/);
  assert.ok(
    packageJson.files.includes('tools/pre-merge-check.mjs'),
    'package files must include tools/pre-merge-check.mjs so npm run pre-merge-check works after publish'
  );
});
