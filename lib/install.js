const fs = require('node:fs');
const path = require('node:path');

// Back up the previous install OUTSIDE skillsDir so the backup is not
// re-discovered by the agent runtime as a duplicate skill.
function defaultBackupDir(skillsDir) {
  return path.join(path.dirname(skillsDir), 'skill-backups');
}

// Transient build/test caches that may exist in the source tree but must never
// be copied into an install: they can be permission-locked (e.g. .pytest-tmp)
// and would bloat the installed skill.
const EXCLUDED_BASENAMES = new Set([
  '.pytest-tmp',
  '.pytest_cache',
  '__pycache__',
  '.mypy_cache',
  '.ruff_cache',
]);

function copyFilter(srcPath) {
  const base = path.basename(srcPath);
  if (EXCLUDED_BASENAMES.has(base)) return false;
  if (base.endsWith('.pyc')) return false;
  return true;
}

function installToMachine({ pkgRoot, skillsDir, python, backupDir }) {
  const src = path.join(pkgRoot, 'skills', 'e2e-dev-harness-v2');
  if (!fs.existsSync(src)) throw new Error(`bundled skill not found: ${src}`);
  fs.mkdirSync(skillsDir, { recursive: true });
  const home = path.join(skillsDir, 'e2e-dev-harness-v2');
  let backup = null;
  if (fs.existsSync(home)) {
    const dir = backupDir || defaultBackupDir(skillsDir);
    fs.mkdirSync(dir, { recursive: true });
    backup = path.join(dir, 'e2e-dev-harness-v2');
    fs.rmSync(backup, { recursive: true, force: true });
    fs.renameSync(home, backup);
  }
  fs.cpSync(src, home, { recursive: true, filter: copyFilter });
  if (python) {
    fs.writeFileSync(
      path.join(home, '.harness-env.json'),
      JSON.stringify({ python }, null, 2) + '\n'
    );
  }
  return { home, backup };
}

module.exports = { installToMachine, defaultBackupDir };
