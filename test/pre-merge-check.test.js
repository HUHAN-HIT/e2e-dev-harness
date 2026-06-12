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
      [
        'python', '-m', 'pytest',
        'skills/e2e-dev-harness/tests',
        'tests/test_node_installer.py',
        '-q',
        '-p', 'no:cacheprovider',
        '--basetemp=.test-tmp/pre-merge-pytest',
      ],
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

test('pre-merge python step uses repo-local temp and disables pytest cache', async () => {
  const { buildPlan, runPlan } = await import('../tools/pre-merge-check.mjs');
  const seen = [];

  runPlan(buildPlan({ skipGitNexus: true }), {
    cwd: 'repo',
    log() {},
    error() {},
    runCommand(step, options) {
      if (step.name === 'python-tests') seen.push(options.env);
      return { status: 0 };
    },
  });

  assert.strictEqual(seen.length, 1);
  assert.strictEqual(seen[0].PYTHONUTF8, '1');
  assert.strictEqual(seen[0].PYTEST_ADDOPTS, process.env.PYTEST_ADDOPTS);
  assert.match(seen[0].TMP, /pre-merge-temp$/);
  assert.strictEqual(seen[0].TEMP, seen[0].TMP);
});

test('pre-merge check script is included in the published package', () => {
  assert.match(packageJson.scripts['pre-merge-check'], /tools\/pre-merge-check\.mjs/);
  assert.ok(
    packageJson.files.includes('tools/pre-merge-check.mjs'),
    'package files must include tools/pre-merge-check.mjs so npm run pre-merge-check works after publish'
  );
});

test('package whitelist avoids broad skill directory scans', () => {
  assert.ok(
    !packageJson.files.includes('skills/e2e-dev-harness'),
    'packing the whole skill directory scans unreadable runtime residue such as .pytest-tmp'
  );
  for (const required of [
    'skills/e2e-dev-harness/SKILL.md',
    'skills/e2e-dev-harness/hooks',
    'skills/e2e-dev-harness/pipelines',
    'skills/e2e-dev-harness/scripts',
    'skills/e2e-dev-harness/tests',
  ]) {
    assert.ok(packageJson.files.includes(required), `package files must include ${required}`);
  }
});
