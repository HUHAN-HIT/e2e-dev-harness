const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

test('clean-pack removes nested pytest temp residue before packing', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'e2e-clean-pack-'));
  const residue = path.join(root, 'skills', 'e2e-dev-harness', '.pytest-tmp');
  fs.mkdirSync(path.join(residue, 'run'), { recursive: true });
  fs.writeFileSync(path.join(residue, 'run', 'artifact.txt'), 'tmp');

  const proc = spawnSync(process.execPath, ['tools/clean-pack.mjs'], {
    cwd: path.resolve(__dirname, '..'),
    env: { ...process.env, E2E_HARNESS_PACK_ROOT: root },
    encoding: 'utf8',
  });

  assert.strictEqual(proc.status, 0, proc.stderr || proc.stdout);
  assert.strictEqual(fs.existsSync(residue), false);
});

test('clean-pack removes suffixed pytest basetemp residue (.pytest-tmp-task3, .pytest-basetemp-*)', () => {
  // Workers run `pytest --basetemp .pytest-tmp-task3` / `.pytest-basetemp-<id>`,
  // leaving suffixed dirs that exact-name matching misses. Strong-clean must purge
  // the whole `.pytest-tmp*` / `.pytest-basetemp*` family, not just `.pytest-tmp`.
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'e2e-clean-pack-'));
  const base = path.join(root, 'skills', 'e2e-dev-harness');
  const suffixed = path.join(base, '.pytest-tmp-task3');
  const basetemp = path.join(base, '.pytest-basetemp-abc123');
  for (const d of [suffixed, basetemp]) {
    fs.mkdirSync(path.join(d, 'run'), { recursive: true });
    fs.writeFileSync(path.join(d, 'run', 'artifact.txt'), 'tmp');
  }

  const proc = spawnSync(process.execPath, ['tools/clean-pack.mjs'], {
    cwd: path.resolve(__dirname, '..'),
    env: { ...process.env, E2E_HARNESS_PACK_ROOT: root },
    encoding: 'utf8',
  });

  assert.strictEqual(proc.status, 0, proc.stderr || proc.stdout);
  assert.strictEqual(fs.existsSync(suffixed), false);
  assert.strictEqual(fs.existsSync(basetemp), false);
});

test('clean-pack reports (not throws) when residue cannot be removed (EPERM)', async () => {
  // fs-failure seam: an un-deletable dir behaves differently on Windows vs POSIX, so
  // the EPERM/EACCES skip path is exercised by injecting an fs whose rmSync always
  // throws EPERM. cleanPack must count it as skipped, warn, and return normally —
  // never crash the prepack and abort the publish.
  const { cleanPack } = await import('../tools/clean-pack.mjs');
  let warned = '';
  const fakeFs = {
    readdirSync: (dir) =>
      String(dir).includes('e2e-dev-harness')
        ? [{ name: '.pytest-tmp', isDirectory: () => true }]
        : [],
    rmSync: () => {
      const error = new Error('locked');
      error.code = 'EPERM';
      throw error;
    },
    chmodSync: () => {},
  };
  const stderr = { write: (s) => { warned += s; } };

  const result = cleanPack({ root: '/clean-pack-fake-root', fs: fakeFs, stderr });

  assert.strictEqual(result.removed, 0);
  assert.strictEqual(result.skipped, 1);
  assert.match(warned, /could not purge locked residue/);
});
