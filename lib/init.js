const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const paths = require('./paths');
const { installToMachine } = require('./install');
const hooks = require('./hooks');
const lifecycle = require('./lifecycle');

const PKG_ROOT = path.join(__dirname, '..');
const REQUIRED_SKILL_FILES = [
  'SKILL.md',
  path.join('hooks', 'claude-code-settings.example.json'),
  path.join('scripts', 'e2e_harness', 'adapters', 'hooks', 'phase_guard.py'),
  path.join('scripts', 'e2e_harness', 'adapters', 'hooks', 'stop_guard.py'),
];

function fail(message, exitCode) {
  const err = new Error(message);
  err.exitCode = exitCode;
  return err;
}

// The canonical harness ships only the claude settings.json hook template, so init always targets
// claude. Detection is informational: surface a warning when the project looks
// like a non-claude runtime so the operator is not surprised by .claude/.
function detectRuntime({ projectRoot, runtime }) {
  if (runtime && runtime !== 'auto') return { runtime, warning: null };
  const has = (dir) => fs.existsSync(path.join(projectRoot, dir));
  if (has('.claude')) return { runtime: 'claude', warning: null };
  if (has('.codex')) {
    return {
      runtime: 'claude',
      warning: 'project has .codex but no .claude; the canonical CLI installs claude-format hooks into .claude/settings.json. For OpenCode, wire the opencode-plugin example instead.',
    };
  }
  return { runtime: 'claude', warning: null };
}

function defaultEnsureSkillInstalled(skillHomeFn) {
  const home = skillHomeFn();
  const hasRequiredFiles = fs.existsSync(home)
    && REQUIRED_SKILL_FILES.every((file) => fs.existsSync(path.join(home, file)));
  if (hasRequiredFiles) return { home, installed: false };
  const skillsDir = path.dirname(home);
  const python = paths.resolvePython(home);
  const res = installToMachine({ pkgRoot: PKG_ROOT, skillsDir, python });
  return { home: res.home, installed: true };
}

function runInit({ projectRoot, runtime = 'auto', dryRun = false, doctor = true, force = false, deps = {} }) {
  const d = {
    skillHome: paths.skillHome,
    resolvePython: paths.resolvePython,
    ensureSkillInstalled: () => defaultEnsureSkillInstalled(deps.skillHome || paths.skillHome),
    materializeHooks: hooks.materializeHooks,
    selfCheck: lifecycle.selfCheck,
    ...deps,
  };

  if (!projectRoot || !fs.existsSync(projectRoot) || !fs.statSync(projectRoot).isDirectory()) {
    throw fail(`project root is not a directory: ${projectRoot}`, 2);
  }

  const { runtime: resolvedRuntime, warning } = detectRuntime({ projectRoot, runtime });
  const skill = d.ensureSkillInstalled();
  const python = d.resolvePython(skill.home);
  if (!python && !force) {
    throw fail('no Python interpreter found; hooks need python at runtime. Set E2E_HARNESS_PYTHON, or re-run with --force to wire hooks anyway.', 3);
  }

  const hookResult = d.materializeHooks({ skillHome: skill.home, projectRoot, dryRun });

  let doctorResult = null;
  if (doctor) {
    doctorResult = d.selfCheck({
      home: skill.home,
      python,
      homeExists: fs.existsSync(skill.home),
      settingsPath: hookResult.settingsPath,
    });
  }

  return {
    runtime: resolvedRuntime,
    warning,
    skill,
    python,
    dryRun,
    hooks: hookResult,
    doctor: doctorResult,
  };
}

function parseInitArgs(argv) {
  const out = { projectDir: null, runtime: 'auto', dryRun: false, doctor: true, force: false };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--runtime') { out.runtime = argv[++i]; }
    else if (arg === '--dry-run') { out.dryRun = true; }
    else if (arg === '--no-doctor') { out.doctor = false; }
    else if (arg === '--force') { out.force = true; }
    else if (arg.startsWith('--')) { throw new Error(`unknown init flag: ${arg}`); }
    else if (out.projectDir === null) { out.projectDir = arg; }
    else { throw new Error(`unexpected init argument: ${arg}`); }
  }
  return out;
}

module.exports = { runInit, detectRuntime, parseInitArgs };
