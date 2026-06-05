const { test } = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const { resolveCommand } = require('../lib/resolve');

const HOME = path.join('C:', 'h', 'e2e-dev-harness');
const PY = 'python';
const s = (...p) => path.join(HOME, 'scripts', ...p);

test('passthrough subcommand -> e2e_dev_harness.py', () => {
  assert.deepStrictEqual(
    resolveCommand(HOME, PY, ['next', '.']),
    { file: PY, args: [s('e2e_dev_harness.py'), 'next', '.'] });
});

test('status maps to doctor', () => {
  assert.deepStrictEqual(
    resolveCommand(HOME, PY, ['status', '.', '--json']),
    { file: PY, args: [s('e2e_dev_harness.py'), 'doctor', '.', '--json'] });
});

test('dispatch maps to dispatch-status', () => {
  assert.deepStrictEqual(
    resolveCommand(HOME, PY, ['dispatch', '.']),
    { file: PY, args: [s('e2e_dev_harness.py'), 'dispatch-status', '.'] });
});

test('init -> install_hooks.py', () => {
  assert.deepStrictEqual(
    resolveCommand(HOME, PY, ['init', '.', '--runtime', 'claude']),
    { file: PY, args: [s('install_hooks.py'), '.', '--runtime', 'claude'] });
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
