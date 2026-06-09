const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { materializeHooks, substituteScriptsDir, toShellScriptsDir } = require('../lib/hooks');

function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'e2eh-hooks-')); }

// A fake installed skill home carrying the v2 hook template with the placeholder.
function fakeSkillHome() {
  const home = tmp();
  const hooksDir = path.join(home, 'hooks');
  fs.mkdirSync(hooksDir, { recursive: true });
  const template = {
    hooks: {
      PreToolUse: [
        {
          matcher: 'Edit|Write|MultiEdit|NotebookEdit|Bash',
          hooks: [
            { type: 'command', command: 'python __HARNESS_SCRIPTS__/e2e_harness/adapters/hooks/phase_guard.py --repo . --hook-input -' },
          ],
        },
      ],
      Stop: [
        {
          hooks: [
            { type: 'command', command: 'python __HARNESS_SCRIPTS__/e2e_harness/adapters/hooks/stop_guard.py --repo . --hook-input -' },
          ],
        },
      ],
    },
  };
  fs.writeFileSync(path.join(hooksDir, 'claude-code-settings.example.json'), JSON.stringify(template, null, 2));
  return home;
}

test('substituteScriptsDir replaces placeholder only inside string leaves', () => {
  const out = substituteScriptsDir(
    { a: 'x __HARNESS_SCRIPTS__ y', b: ['__HARNESS_SCRIPTS__', 1], c: { d: 2 } },
    'C:\\skills\\scripts'
  );
  assert.strictEqual(out.a, 'x C:\\skills\\scripts y');
  assert.strictEqual(out.b[0], 'C:\\skills\\scripts');
  assert.strictEqual(out.b[1], 1);
  assert.strictEqual(out.c.d, 2);
});

test('toShellScriptsDir converts a Windows backslash path to forward slashes so bash will not strip the separators', () => {
  const win = 'C:\\Users\\14907\\.claude\\skills\\e2e-dev-harness\\scripts';
  const out = toShellScriptsDir(win);
  assert.strictEqual(out, 'C:/Users/14907/.claude/skills/e2e-dev-harness/scripts');
  assert.ok(!out.includes('\\'), 'shell-embedded scripts dir must not contain backslashes');
});

test('toShellScriptsDir leaves a POSIX path unchanged', () => {
  assert.strictEqual(toShellScriptsDir('/home/u/.claude/skills/e2e-dev-harness/scripts'), '/home/u/.claude/skills/e2e-dev-harness/scripts');
});

test('materializeHooks emits hook commands with no backslashes (bash-safe on Windows)', () => {
  const home = fakeSkillHome();
  const projectRoot = tmp();
  materializeHooks({ skillHome: home, projectRoot });

  const settings = JSON.parse(fs.readFileSync(path.join(projectRoot, '.claude', 'settings.json'), 'utf8'));
  const pre = settings.hooks.PreToolUse[0].hooks[0].command;
  const stop = settings.hooks.Stop[0].hooks[0].command;
  assert.ok(!pre.includes('\\'), `PreToolUse command must not contain backslashes: ${pre}`);
  assert.ok(!stop.includes('\\'), `Stop command must not contain backslashes: ${stop}`);
  const posixScripts = path.join(home, 'scripts').replace(/\\/g, '/');
  assert.ok(pre.includes(`${posixScripts}/e2e_harness/adapters/hooks/phase_guard.py`));
});

test('materializeHooks writes both hooks into a fresh settings.json with scripts dir substituted', () => {
  const home = fakeSkillHome();
  const projectRoot = tmp();
  const res = materializeHooks({ skillHome: home, projectRoot });

  assert.strictEqual(res.added, 2);
  assert.strictEqual(res.alreadyPresent, 0);
  assert.strictEqual(res.scriptsDir, path.join(home, 'scripts'));

  const settings = JSON.parse(fs.readFileSync(path.join(projectRoot, '.claude', 'settings.json'), 'utf8'));
  const pre = settings.hooks.PreToolUse[0].hooks[0].command;
  const stop = settings.hooks.Stop[0].hooks[0].command;
  assert.ok(pre.includes(`${toShellScriptsDir(path.join(home, 'scripts'))}/e2e_harness/adapters/hooks/phase_guard.py`));
  assert.ok(!pre.includes('__HARNESS_SCRIPTS__'));
  assert.ok(stop.includes('stop_guard.py'));
});

test('materializeHooks is idempotent: second run adds nothing', () => {
  const home = fakeSkillHome();
  const projectRoot = tmp();
  materializeHooks({ skillHome: home, projectRoot });
  const second = materializeHooks({ skillHome: home, projectRoot });
  assert.strictEqual(second.added, 0);
  assert.strictEqual(second.alreadyPresent, 2);
});

test('materializeHooks dryRun writes nothing but reports the plan', () => {
  const home = fakeSkillHome();
  const projectRoot = tmp();
  const res = materializeHooks({ skillHome: home, projectRoot, dryRun: true });
  assert.strictEqual(res.added, 2);
  assert.ok(!fs.existsSync(path.join(projectRoot, '.claude', 'settings.json')));
});

test('materializeHooks backs up an existing settings.json before merging', () => {
  const home = fakeSkillHome();
  const projectRoot = tmp();
  const claudeDir = path.join(projectRoot, '.claude');
  fs.mkdirSync(claudeDir, { recursive: true });
  fs.writeFileSync(path.join(claudeDir, 'settings.json'), JSON.stringify({ env: { KEEP: '1' } }, null, 2));

  const res = materializeHooks({ skillHome: home, projectRoot });
  assert.ok(res.backup && fs.existsSync(res.backup));
  // existing unrelated keys are preserved through the merge
  const merged = JSON.parse(fs.readFileSync(path.join(claudeDir, 'settings.json'), 'utf8'));
  assert.strictEqual(merged.env.KEEP, '1');
  assert.strictEqual(merged.hooks.PreToolUse[0].hooks[0].command.includes('phase_guard.py'), true);
  // backup holds the original content
  const backup = JSON.parse(fs.readFileSync(res.backup, 'utf8'));
  assert.strictEqual(backup.env.KEEP, '1');
  assert.ok(!backup.hooks);
});

test('materializeHooks restores the backup when the write fails', () => {
  const home = fakeSkillHome();
  const projectRoot = tmp();
  const claudeDir = path.join(projectRoot, '.claude');
  fs.mkdirSync(claudeDir, { recursive: true });
  const original = JSON.stringify({ env: { KEEP: '1' } }, null, 2);
  fs.writeFileSync(path.join(claudeDir, 'settings.json'), original);

  const failingFs = {
    ...fs,
    writeFileSync(target, data, ...rest) {
      if (String(target).endsWith('settings.json')) throw new Error('disk full');
      return fs.writeFileSync(target, data, ...rest);
    },
  };

  assert.throws(() => materializeHooks({ skillHome: home, projectRoot, fsImpl: failingFs }), /disk full/);
  // settings.json is restored to its original content, no half-written merge
  assert.strictEqual(fs.readFileSync(path.join(claudeDir, 'settings.json'), 'utf8'), original);
});
