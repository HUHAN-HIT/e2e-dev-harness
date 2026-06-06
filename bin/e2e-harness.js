#!/usr/bin/env node
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const { skillHome, resolvePython, detectPython } = require('../lib/paths');
const { installToMachine } = require('../lib/install');
const { resolveCommand } = require('../lib/resolve');
const {
  npmBinary,
  npmCommand,
  commandMatchesFromPath,
  commandOwnedByPackage,
  readVersion,
  uninstallFromMachine,
  selfCheck,
} = require('../lib/lifecycle');

const PKG_ROOT = path.join(__dirname, '..');

const HELP = `e2e-harness <command> [args]

Tool lifecycle (this machine):
  link                 Register e2e-harness as a global command (npm link)
  unlink               Remove the global e2e-harness command
  install              Copy the bundled skill into ~/.claude/skills
  update               Re-copy the bundled skill (backs up the previous one)
  uninstall            Remove the installed skill from ~/.claude/skills
  env                  Diagnose node / python / install / link state
  version, -v          Print the package name and version

Project lifecycle (a business repo):
  init <repo> [--runtime claude]   Install harness hooks into <repo>
  status <repo>                    Doctor: hooks / index / run-state readiness
  next <repo>                      Next allowed harness action
  dispatch <repo>                  Dispatch state + open scheduled tasks
  exec <script.py> [args]          Run a bundled scripts/<script>.py`;

function skillsDir() {
  return path.join(os.homedir(), '.claude', 'skills');
}

function commandMatches(commandName) {
  const probe = process.platform === 'win32' ? 'where' : 'which';
  const r = spawnSync(probe, [commandName], { encoding: 'utf8', stdio: 'pipe' });
  const matches = r.status === 0
    ? (r.stdout || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    : [];
  return matches.length ? matches : commandMatchesFromPath(commandName);
}

function npmGlobalBinDir() {
  for (const command of [npmBinary(), 'npm']) {
    const r = spawnSync(command, ['config', 'get', 'prefix'], { encoding: 'utf8', stdio: 'pipe' });
    if (r.status !== 0) continue;
    const prefix = (r.stdout || '').split(/\r?\n/).map((line) => line.trim()).find(Boolean);
    if (prefix) return process.platform === 'win32' ? prefix : path.join(prefix, 'bin');
  }
  return null;
}

function isLinked() {
  const matches = commandMatches('e2e-harness');
  const npmBinDir = npmGlobalBinDir() || (matches[0] ? path.dirname(matches[0]) : null);
  return commandOwnedByPackage(matches, {
    pkgRoot: PKG_ROOT,
    npmBinDir,
    commandName: 'e2e-harness',
  });
}

function runSpec(spec) {
  const r = spawnSync(spec.file, spec.args, { cwd: spec.cwd, stdio: 'inherit' });
  return r.status === null ? 1 : r.status;
}

function main() {
  const argv = process.argv.slice(2);
  const cmd = argv[0];

  if (!cmd || cmd === '--help' || cmd === '-h') {
    console.log(HELP);
    process.exit(cmd ? 0 : 1);
  }

  if (cmd === 'version' || cmd === '--version' || cmd === '-v') {
    const v = readVersion(PKG_ROOT);
    console.log(`${v.name} ${v.version}`);
    process.exit(0);
  }

  if (cmd === 'link' || cmd === 'unlink') {
    const { name } = readVersion(PKG_ROOT);
    const code = runSpec(npmCommand(cmd, { pkgRoot: PKG_ROOT, pkgName: name }));
    if (code === 0) {
      console.log(cmd === 'link'
        ? 'Linked. The global `e2e-harness` command is now available.'
        : 'Unlinked the global `e2e-harness` command.');
    }
    process.exit(code);
  }

  if (cmd === 'install' || cmd === 'update') {
    const python = process.env.E2E_HARNESS_PYTHON || detectPython();
    const { home, backup } = installToMachine({ pkgRoot: PKG_ROOT, skillsDir: skillsDir(), python });
    console.log(`${cmd === 'update' ? 'Updated' : 'Installed'} harness at ${home} (python=${python || 'NOT FOUND'})`);
    if (backup) console.log(`Previous install backed up to ${backup}`);
    process.exit(0);
  }

  if (cmd === 'uninstall') {
    const { removed, home } = uninstallFromMachine({ skillsDir: skillsDir() });
    console.log(removed ? `Removed ${home}` : `Nothing to remove at ${home}`);
    console.log('Note: run `e2e-harness unlink` separately to remove the global command.');
    process.exit(0);
  }

  if (cmd === 'env') {
    const home = skillHome();
    const report = selfCheck({
      home,
      python: resolvePython(home),
      version: readVersion(PKG_ROOT),
      linkedBin: isLinked(),
      nodeVersion: process.version,
      homeExists: fs.existsSync(home),
    });
    console.log(JSON.stringify(report, null, 2));
    process.exit(report.ok ? 0 : 3);
  }

  // ---- project lifecycle: passthrough to bundled python scripts ----
  const home = skillHome();
  if (!fs.existsSync(home)) {
    console.error(`Harness not installed at ${home}. Run: e2e-harness install`);
    process.exit(3);
  }
  const py = resolvePython(home);
  if (!py) { console.error('No Python interpreter found. Set E2E_HARNESS_PYTHON.'); process.exit(3); }

  // Keep the bundled skills dir free of __pycache__ byproducts: bundled scripts
  // are short-lived passthroughs, so cached bytecode is pure litter. Inherited by
  // the spawned interpreter via process.env; honor an explicit operator override.
  if (process.env.PYTHONDONTWRITEBYTECODE === undefined) {
    process.env.PYTHONDONTWRITEBYTECODE = '1';
  }

  let spec;
  try {
    spec = resolveCommand(home, py, argv);
  } catch (e) {
    console.error(e.message);
    process.exit(2);
  }
  process.exit(runSpec(spec));
}

main();
