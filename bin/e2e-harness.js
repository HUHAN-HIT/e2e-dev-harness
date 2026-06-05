#!/usr/bin/env node
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const { skillHome, resolvePython, detectPython } = require('../lib/paths');
const { installToMachine } = require('../lib/install');
const { resolveCommand } = require('../lib/resolve');

const PKG_ROOT = path.join(__dirname, '..');

function main() {
  const argv = process.argv.slice(2);
  const cmd = argv[0];

  if (!cmd || cmd === '--help' || cmd === '-h') {
    console.log('Usage: e2e-harness <install|init|status|next|dispatch|exec <script.py>|...> [project] [opts]');
    process.exit(cmd ? 0 : 1);
  }

  if (cmd === 'install') {
    const skillsDir = path.join(os.homedir(), '.claude', 'skills');
    const python = process.env.E2E_HARNESS_PYTHON || detectPython();
    const { home, backup } = installToMachine({ pkgRoot: PKG_ROOT, skillsDir, python });
    console.log(`Installed harness to ${home} (python=${python || 'NOT FOUND'})`);
    if (backup) console.log(`Previous install backed up to ${backup}`);
    process.exit(0);
  }

  const home = skillHome();
  if (!fs.existsSync(home)) {
    console.error(`Harness not installed at ${home}. Run: e2e-harness install`);
    process.exit(3);
  }
  const py = resolvePython(home);
  if (!py) { console.error('No Python interpreter found. Set E2E_HARNESS_PYTHON.'); process.exit(3); }

  let spec;
  try {
    spec = resolveCommand(home, py, argv);
  } catch (e) {
    console.error(e.message);
    process.exit(2);
  }
  const r = spawnSync(spec.file, spec.args, { stdio: 'inherit' });
  process.exit(r.status === null ? 1 : r.status);
}

main();
