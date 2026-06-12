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
