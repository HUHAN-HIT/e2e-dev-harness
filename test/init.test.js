const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { runInit, detectRuntime } = require('../lib/init');

function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'e2eh-init-')); }

function baseDeps(overrides = {}) {
  return {
    skillHome: () => '/fake/skill/home',
    resolvePython: () => 'python3',
    ensureSkillInstalled: () => ({ home: '/fake/skill/home', installed: false }),
    materializeHooks: () => ({ added: 2, alreadyPresent: 0, settingsPath: '/p/.claude/settings.json', backup: null, scriptsDir: '/fake/skill/home/scripts' }),
    selfCheck: () => ({ ok: true }),
    ...overrides,
  };
}

test('detectRuntime: explicit runtime wins over detection', () => {
  const r = detectRuntime({ projectRoot: tmp(), runtime: 'claude' });
  assert.strictEqual(r.runtime, 'claude');
  assert.strictEqual(r.warning, null);
});

test('detectRuntime: .claude present resolves claude with no warning', () => {
  const root = tmp();
  fs.mkdirSync(path.join(root, '.claude'));
  const r = detectRuntime({ projectRoot: root, runtime: 'auto' });
  assert.strictEqual(r.runtime, 'claude');
  assert.strictEqual(r.warning, null);
});

test('detectRuntime: .codex-only warns about claude-format hooks but still targets claude', () => {
  const root = tmp();
  fs.mkdirSync(path.join(root, '.codex'));
  const r = detectRuntime({ projectRoot: root, runtime: 'auto' });
  assert.strictEqual(r.runtime, 'claude');
  assert.ok(r.warning && /opencode/i.test(r.warning));
});

test('runInit fails fast (exit 3) when python is missing and not forced', () => {
  const root = tmp();
  assert.throws(
    () => runInit({ projectRoot: root, deps: baseDeps({ resolvePython: () => null }) }),
    (err) => {
      assert.strictEqual(err.exitCode, 3);
      assert.ok(/python/i.test(err.message));
      return true;
    }
  );
});

test('runInit proceeds when python missing but --force is set', () => {
  const root = tmp();
  let merged = false;
  const res = runInit({
    projectRoot: root,
    force: true,
    deps: baseDeps({ resolvePython: () => null, materializeHooks: () => { merged = true; return { added: 2, alreadyPresent: 0, settingsPath: 'x', backup: null, scriptsDir: 'y' }; } }),
  });
  assert.ok(merged);
  assert.strictEqual(res.python, null);
});

test('runInit fails (exit 2) when project root is not a directory', () => {
  assert.throws(
    () => runInit({ projectRoot: path.join(tmp(), 'does-not-exist'), deps: baseDeps() }),
    (err) => {
      assert.strictEqual(err.exitCode, 2);
      return true;
    }
  );
});

test('runInit happy path materializes hooks and runs doctor', () => {
  const root = tmp();
  const calls = { hooks: null, doctor: 0 };
  const res = runInit({
    projectRoot: root,
    deps: baseDeps({
      materializeHooks: (args) => { calls.hooks = args; return { added: 2, alreadyPresent: 0, settingsPath: 's', backup: null, scriptsDir: 'sc' }; },
      selfCheck: () => { calls.doctor += 1; return { ok: true }; },
    }),
  });
  assert.strictEqual(res.hooks.added, 2);
  assert.strictEqual(calls.hooks.projectRoot, root);
  assert.strictEqual(calls.hooks.skillHome, '/fake/skill/home');
  assert.strictEqual(calls.doctor, 1);
  assert.ok(res.doctor && res.doctor.ok);
});

test('runInit repairs stale installed skill before materializing hooks', () => {
  const root = tmp();
  const skillsDir = tmp();
  const staleHome = path.join(skillsDir, 'e2e-dev-harness');
  fs.mkdirSync(staleHome, { recursive: true });
  fs.writeFileSync(path.join(staleHome, 'SKILL.md'), 'old install without hooks');

  const res = runInit({
    projectRoot: root,
    deps: {
      skillHome: () => staleHome,
      resolvePython: () => 'python3',
      selfCheck: () => ({ ok: true }),
    },
  });

  assert.strictEqual(res.skill.installed, true);
  assert.ok(fs.existsSync(path.join(staleHome, 'hooks', 'claude-code-settings.example.json')));
  assert.strictEqual(res.hooks.added, 2);
  assert.ok(fs.existsSync(path.join(root, '.claude', 'settings.json')));
});

test('runInit skips doctor when doctor:false', () => {
  const root = tmp();
  let doctorCalls = 0;
  const res = runInit({
    projectRoot: root,
    doctor: false,
    deps: baseDeps({ selfCheck: () => { doctorCalls += 1; return { ok: true }; } }),
  });
  assert.strictEqual(doctorCalls, 0);
  assert.strictEqual(res.doctor, null);
});

test('runInit dryRun passes dryRun through to materializeHooks', () => {
  const root = tmp();
  let seenDryRun = null;
  runInit({
    projectRoot: root,
    dryRun: true,
    deps: baseDeps({ materializeHooks: (args) => { seenDryRun = args.dryRun; return { added: 2, alreadyPresent: 0, settingsPath: 's', backup: null, scriptsDir: 'sc' }; } }),
  });
  assert.strictEqual(seenDryRun, true);
});

const { parseInitArgs } = require('../lib/init');

test('parseInitArgs defaults: cwd project, auto runtime, doctor on, execute', () => {
  const a = parseInitArgs([]);
  assert.strictEqual(a.projectDir, null);
  assert.strictEqual(a.runtime, 'auto');
  assert.strictEqual(a.dryRun, false);
  assert.strictEqual(a.doctor, true);
  assert.strictEqual(a.force, false);
});

test('parseInitArgs reads positional project dir and all flags', () => {
  const a = parseInitArgs(['./repo', '--runtime', 'claude', '--dry-run', '--no-doctor', '--force']);
  assert.strictEqual(a.projectDir, './repo');
  assert.strictEqual(a.runtime, 'claude');
  assert.strictEqual(a.dryRun, true);
  assert.strictEqual(a.doctor, false);
  assert.strictEqual(a.force, true);
});

test('parseInitArgs rejects an unknown flag', () => {
  assert.throws(() => parseInitArgs(['--nope']), /unknown/i);
});

// --- U2: opencode runtime detection + dispatch --------------------------------

test('detectRuntime: .opencode present resolves opencode', () => {
  const root = tmp();
  fs.mkdirSync(path.join(root, '.opencode'));
  const r = detectRuntime({ projectRoot: root, runtime: 'auto' });
  assert.strictEqual(r.runtime, 'opencode');
});

test('detectRuntime: explicit opencode runtime wins over detection', () => {
  const root = tmp();
  fs.mkdirSync(path.join(root, '.claude'));
  const r = detectRuntime({ projectRoot: root, runtime: 'opencode' });
  assert.strictEqual(r.runtime, 'opencode');
});

test('runInit materializes the opencode plugin (not claude settings) when runtime is opencode', () => {
  const root = tmp();
  let claudeCalled = false;
  let ocArgs = null;
  const res = runInit({
    projectRoot: root,
    runtime: 'opencode',
    deps: baseDeps({
      materializeHooks: () => { claudeCalled = true; return { added: 2, alreadyPresent: 0, settingsPath: 's', backup: null, scriptsDir: 'sc' }; },
      materializeOpencodePlugin: (args) => { ocArgs = args; return { added: 1, alreadyPresent: 0, pluginPath: 'p', backup: null, scriptsDir: 'sc' }; },
    }),
  });
  assert.strictEqual(res.runtime, 'opencode');
  assert.ok(ocArgs, 'materializeOpencodePlugin must be called for the opencode runtime');
  assert.strictEqual(ocArgs.projectRoot, root);
  assert.strictEqual(claudeCalled, false, 'the claude materializer must NOT run for opencode');
});

test('detectRuntime: opencode resolves with a stop-guard downgrade warning', () => {
  // opencode enforces the phase-write lock but cannot enforce run-to-VERIFIED
  // (no stop-veto hook); detectRuntime must surface that as a warning.
  const r = detectRuntime({ projectRoot: tmp(), runtime: 'opencode' });
  assert.strictEqual(r.runtime, 'opencode');
  assert.ok(r.warning && /verified|advisory|stop/i.test(r.warning));
});

test('runInit still materializes claude settings for the claude runtime', () => {
  const root = tmp();
  let claudeCalled = false;
  let ocCalled = false;
  runInit({
    projectRoot: root,
    runtime: 'claude',
    deps: baseDeps({
      materializeHooks: () => { claudeCalled = true; return { added: 2, alreadyPresent: 0, settingsPath: 's', backup: null, scriptsDir: 'sc' }; },
      materializeOpencodePlugin: () => { ocCalled = true; return { added: 1, alreadyPresent: 0, pluginPath: 'p', backup: null, scriptsDir: 'sc' }; },
    }),
  });
  assert.ok(claudeCalled, 'the claude materializer must run for claude');
  assert.strictEqual(ocCalled, false, 'the opencode materializer must NOT run for claude');
});
