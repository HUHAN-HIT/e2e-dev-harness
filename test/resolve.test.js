const { test } = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const { resolveCommand } = require('../lib/resolve');

const HOME = path.join('C:', 'h', 'e2e-dev-harness-v2');
const PY = 'python';
const s = (...p) => path.join(HOME, 'scripts', ...p);
const ENTRY = 'e2e_dev_harness_v2.py';

test('start passes through verbatim to e2e_dev_harness_v2.py', () => {
  assert.deepStrictEqual(
    resolveCommand(HOME, PY, ['start', '--repo', '.', '--feature', 'f', '--request', 'q']),
    { file: PY, args: [s(ENTRY), 'start', '--repo', '.', '--feature', 'f', '--request', 'q'] });
});

test('next passes through with --state', () => {
  assert.deepStrictEqual(
    resolveCommand(HOME, PY, ['next', '--state', 'rs.json']),
    { file: PY, args: [s(ENTRY), 'next', '--state', 'rs.json'] });
});

test('status passes through (no longer maps to doctor)', () => {
  assert.deepStrictEqual(
    resolveCommand(HOME, PY, ['status', '--state', 'rs.json']),
    { file: PY, args: [s(ENTRY), 'status', '--state', 'rs.json'] });
});

test('dispatch passes through (no longer maps to dispatch-status)', () => {
  assert.deepStrictEqual(
    resolveCommand(HOME, PY, ['dispatch', '--state', 'rs.json', '--runtime', 'claude-code']),
    { file: PY, args: [s(ENTRY), 'dispatch', '--state', 'rs.json', '--runtime', 'claude-code'] });
});

test('submit and gate pass through', () => {
  assert.deepStrictEqual(
    resolveCommand(HOME, PY, ['submit', '--state', 'rs.json', '--phase', 'RED', '--key', 'k', '--path', 'p']),
    { file: PY, args: [s(ENTRY), 'submit', '--state', 'rs.json', '--phase', 'RED', '--key', 'k', '--path', 'p'] });
  assert.deepStrictEqual(
    resolveCommand(HOME, PY, ['gate', '--state', 'rs.json']),
    { file: PY, args: [s(ENTRY), 'gate', '--state', 'rs.json'] });
});

test('validate-pipeline passes through', () => {
  assert.deepStrictEqual(
    resolveCommand(HOME, PY, ['validate-pipeline', '--pipeline', 'minimal']),
    { file: PY, args: [s(ENTRY), 'validate-pipeline', '--pipeline', 'minimal'] });
});

test('exec -> scripts/<name>', () => {
  assert.deepStrictEqual(
    resolveCommand(HOME, PY, ['exec', 'memory_capture.py', 'select', '.']),
    { file: PY, args: [s('memory_capture.py'), 'select', '.'] });
});

test('exec rejects path traversal', () => {
  assert.throws(() => resolveCommand(HOME, PY, ['exec', '../evil.py']), /invalid script/);
});

test('exec requires a script', () => {
  assert.throws(() => resolveCommand(HOME, PY, ['exec']), /requires a script/);
});
