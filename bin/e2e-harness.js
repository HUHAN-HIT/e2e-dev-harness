#!/usr/bin/env node
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const { skillHome, resolvePython, detectPython } = require('../lib/paths');
const { installToMachine } = require('../lib/install');

const PKG_ROOT = path.join(__dirname, '..');
const SUB_MAP = { status: 'doctor', dispatch: 'dispatch-status' };

function runPython(home, args) {
  const py = resolvePython(home);
  if (!py) { console.error('No Python interpreter found. Set E2E_HARNESS_PYTHON.'); process.exit(3); }
  const cli = path.join(home, 'scripts', 'e2e_dev_harness.py');
  const r = spawnSync(py, [cli, ...args], { stdio: 'inherit' });
  process.exit(r.status === null ? 1 : r.status);
}

function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  if (!cmd || cmd === '--help' || cmd === '-h') {
    console.log('Usage: e2e-harness <install|init|status|next|dispatch|...> [project] [opts]');
    process.exit(cmd ? 0 : 1);
  }
  if (cmd === 'install') {
    const skillsDir = path.join(os.homedir(), '.claude', 'skills');
    const python = process.env.E2E_HARNESS_PYTHON || detectPython();
    const { home } = installToMachine({ pkgRoot: PKG_ROOT, skillsDir, python });
    console.log(`Installed harness to ${home} (python=${python || 'NOT FOUND'})`);
    process.exit(0);
  }
  const home = skillHome();
  if (!fs.existsSync(home)) {
    console.error(`Harness not installed at ${home}. Run: e2e-harness install`);
    process.exit(3);
  }
  if (cmd === 'init') {
    const py = resolvePython(home);
    const installHooks = path.join(home, 'scripts', 'install_hooks.py');
    const r = spawnSync(py, [installHooks, ...rest], { stdio: 'inherit' });
    process.exit(r.status === null ? 1 : r.status);
  }
  const mapped = SUB_MAP[cmd] || cmd;
  runPython(home, [mapped, ...rest]);
}

main();
