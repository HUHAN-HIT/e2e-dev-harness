const fs = require('node:fs');
const path = require('node:path');

// Back up the previous install OUTSIDE skillsDir so the backup is not
// re-discovered by the agent runtime as a duplicate skill.
function defaultBackupDir(skillsDir) {
  return path.join(path.dirname(skillsDir), 'skill-backups');
}

function installToMachine({ pkgRoot, skillsDir, python, backupDir }) {
  const src = path.join(pkgRoot, 'skills', 'e2e-dev-harness');
  if (!fs.existsSync(src)) throw new Error(`bundled skill not found: ${src}`);
  fs.mkdirSync(skillsDir, { recursive: true });
  const home = path.join(skillsDir, 'e2e-dev-harness');
  let backup = null;
  if (fs.existsSync(home)) {
    const dir = backupDir || defaultBackupDir(skillsDir);
    fs.mkdirSync(dir, { recursive: true });
    backup = path.join(dir, 'e2e-dev-harness');
    fs.rmSync(backup, { recursive: true, force: true });
    fs.renameSync(home, backup);
  }
  fs.cpSync(src, home, { recursive: true });
  if (python) {
    fs.writeFileSync(
      path.join(home, '.harness-env.json'),
      JSON.stringify({ python }, null, 2) + '\n'
    );
  }
  return { home, backup };
}

module.exports = { installToMachine, defaultBackupDir };
