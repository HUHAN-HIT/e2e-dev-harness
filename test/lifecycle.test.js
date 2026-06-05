const { test } = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');
const {
  npmCommand,
  commandOwnedByPackage,
  commandMatchesFromPath,
  readVersion,
  uninstallFromMachine,
  selfCheck,
} = require('../lib/lifecycle');

const PKG_ROOT = path.join(__dirname, '..');

test('npmCommand link -> `npm link` in pkgRoot', () => {
  const spec = npmCommand('link', { pkgRoot: '/p', pkgName: 'e2e-harness' });
  assert.match(spec.file, /npm/);
  assert.deepStrictEqual(spec.args, ['link']);
  assert.strictEqual(spec.cwd, '/p');
});

test('npmCommand unlink -> global remove by package name', () => {
  const spec = npmCommand('unlink', { pkgRoot: '/p', pkgName: 'e2e-harness' });
  assert.match(spec.file, /npm/);
  assert.deepStrictEqual(spec.args, ['rm', '-g', 'e2e-harness']);
});

test('npmCommand rejects unknown action', () => {
  assert.throws(() => npmCommand('frob', { pkgRoot: '/p', pkgName: 'x' }), /unknown/i);
});

test('commandOwnedByPackage rejects python console_scripts shadowing the Node command', () => {
  const pkgRoot = path.join('C:', 'repo', 'e2e');
  const npmBinDir = path.join('C:', 'Users', 'me', 'AppData', 'Roaming', 'npm');
  const matches = [
    path.join('D:', 'SOFTWARE', 'PYTHON3_13', 'Scripts', 'e2e-harness.exe'),
    path.join(npmBinDir, 'e2e-harness.cmd'),
  ];

  assert.strictEqual(commandOwnedByPackage(matches, { pkgRoot, npmBinDir, commandName: 'e2e-harness' }), false);
});

test('commandOwnedByPackage accepts npm shim or this package bin as first PATH match', () => {
  const pkgRoot = path.join('C:', 'repo', 'e2e');
  const npmBinDir = path.join('C:', 'Users', 'me', 'AppData', 'Roaming', 'npm');

  assert.strictEqual(
    commandOwnedByPackage([path.join(npmBinDir, 'e2e-harness.cmd')], { pkgRoot, npmBinDir, commandName: 'e2e-harness' }),
    true,
  );
  assert.strictEqual(
    commandOwnedByPackage([path.join(pkgRoot, 'bin', 'e2e-harness.js')], { pkgRoot, npmBinDir, commandName: 'e2e-harness' }),
    true,
  );
});

test('commandMatchesFromPath preserves PATH order and includes PowerShell shims', () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'e2e-path-'));
  const pythonScripts = path.join(tmpRoot, 'Python', 'Scripts');
  const npmBinDir = path.join(tmpRoot, 'npm');
  fs.mkdirSync(pythonScripts, { recursive: true });
  fs.mkdirSync(npmBinDir, { recursive: true });
  fs.writeFileSync(path.join(pythonScripts, 'e2e-harness.exe'), '');
  fs.writeFileSync(path.join(npmBinDir, 'e2e-harness.ps1'), '');

  const matches = commandMatchesFromPath('e2e-harness', {
    pathValue: [pythonScripts, npmBinDir].join(path.delimiter),
    platform: 'win32',
  });

  assert.deepStrictEqual(matches, [
    path.join(pythonScripts, 'e2e-harness.exe'),
    path.join(npmBinDir, 'e2e-harness.ps1'),
  ]);
  fs.rmSync(tmpRoot, { recursive: true, force: true });
});

test('commandMatchesFromPath finds npm command shim when where.exe has no match', () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'e2e-path-'));
  fs.writeFileSync(path.join(tmpRoot, 'e2e-harness.ps1'), '');

  assert.deepStrictEqual(
    commandMatchesFromPath('e2e-harness', { pathValue: tmpRoot, platform: 'win32' }),
    [path.join(tmpRoot, 'e2e-harness.ps1')],
  );
  fs.rmSync(tmpRoot, { recursive: true, force: true });
});

test('readVersion reads name + version from package.json', () => {
  const v = readVersion(PKG_ROOT);
  assert.strictEqual(v.name, 'e2e-harness');
  assert.strictEqual(typeof v.version, 'string');
  assert.match(v.version, /^\d+\.\d+\.\d+/);
});

test('uninstallFromMachine removes an existing home, idempotent', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'e2e-life-'));
  const home = path.join(tmp, 'e2e-dev-harness');
  fs.mkdirSync(home, { recursive: true });
  fs.writeFileSync(path.join(home, 'marker.txt'), 'x');

  const first = uninstallFromMachine({ skillsDir: tmp });
  assert.strictEqual(first.removed, true);
  assert.strictEqual(first.home, home);
  assert.strictEqual(fs.existsSync(home), false);

  const second = uninstallFromMachine({ skillsDir: tmp });
  assert.strictEqual(second.removed, false);

  fs.rmSync(tmp, { recursive: true, force: true });
});

test('uninstallFromMachine honors explicit home over skillsDir', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'e2e-life-'));
  const home = path.join(tmp, 'custom-home');
  fs.mkdirSync(home, { recursive: true });
  const r = uninstallFromMachine({ skillsDir: tmp, home });
  assert.strictEqual(r.removed, true);
  assert.strictEqual(r.home, home);
  fs.rmSync(tmp, { recursive: true, force: true });
});

test('selfCheck ok=true only when home exists and python found', () => {
  const v = { name: 'e2e-harness', version: '0.1.0' };
  const good = selfCheck({ home: '/h', python: 'python3', version: v, linkedBin: true, nodeVersion: 'v20', homeExists: true });
  assert.strictEqual(good.ok, true);
  assert.strictEqual(good.linked, true);
  assert.strictEqual(good.version, '0.1.0');

  const noHome = selfCheck({ home: '/h', python: 'python3', version: v, homeExists: false });
  assert.strictEqual(noHome.ok, false);

  const noPy = selfCheck({ home: '/h', python: null, version: v, homeExists: true });
  assert.strictEqual(noPy.ok, false);
  assert.strictEqual(noPy.linked, false);
});
