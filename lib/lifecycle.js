const fs = require('node:fs');
const path = require('node:path');

function npmBinary() {
  return process.platform === 'win32' ? 'npm.cmd' : 'npm';
}

// Pure: maps a lifecycle action to an npm spawn descriptor.
// `link`   -> `npm link` in pkgRoot, registers the global `e2e-harness` command.
// `unlink` -> `npm rm -g <pkgName>`, removes the global command.
function npmCommand(action, { pkgRoot, pkgName }) {
  if (action === 'link') return { file: npmBinary(), args: ['link'], cwd: pkgRoot };
  if (action === 'unlink') return { file: npmBinary(), args: ['rm', '-g', pkgName], cwd: pkgRoot };
  throw new Error(`unknown npm lifecycle action: ${action}`);
}

function readVersion(pkgRoot) {
  const data = JSON.parse(fs.readFileSync(path.join(pkgRoot, 'package.json'), 'utf8'));
  return { name: data.name, version: data.version };
}

function normalizePath(value) {
  return path.resolve(String(value || '')).toLowerCase();
}

function commandExtensions(platform) {
  if (platform !== 'win32') return [''];
  return ['', '.cmd', '.ps1', '.exe', '.bat'];
}

function commandMatchesFromPath(commandName, { pathValue = process.env.PATH || '', platform = process.platform } = {}) {
  const matches = [];
  const seen = new Set();
  for (const dir of String(pathValue || '').split(path.delimiter).filter(Boolean)) {
    for (const ext of commandExtensions(platform)) {
      const candidate = path.join(dir, `${commandName}${ext}`);
      const key = normalizePath(candidate);
      if (seen.has(key) || !fs.existsSync(candidate)) continue;
      seen.add(key);
      matches.push(candidate);
    }
  }
  return matches;
}

function commandOwnedByPackage(matches, { pkgRoot, npmBinDir, commandName }) {
  const first = Array.isArray(matches) ? matches.find(Boolean) : null;
  if (!first) return false;

  const normalizedFirst = normalizePath(first);
  const packageBin = normalizePath(path.join(pkgRoot, 'bin', `${commandName}.js`));
  if (normalizedFirst === packageBin) return true;

  if (!npmBinDir) return false;
  const npmRoot = normalizePath(npmBinDir);
  const basename = path.basename(normalizedFirst);
  const allowedNames = new Set([
    commandName,
    `${commandName}.cmd`,
    `${commandName}.ps1`,
  ]);
  return path.dirname(normalizedFirst) === npmRoot && allowedNames.has(basename);
}

// Remove the installed skill home. Idempotent: returns removed:false if absent.
function uninstallFromMachine({ skillsDir, home }) {
  const target = home || path.join(skillsDir, 'e2e-dev-harness');
  if (!fs.existsSync(target)) return { removed: false, home: target };
  fs.rmSync(target, { recursive: true, force: true });
  return { removed: true, home: target };
}

// Pure: build a structured diagnostic report from injected facts.
function selfCheck({ home, python, version, linkedBin, nodeVersion, homeExists }) {
  return {
    name: version && version.name,
    version: version && version.version,
    node: nodeVersion,
    python: python || null,
    home,
    homeExists: !!homeExists,
    linked: !!linkedBin,
    ok: !!homeExists && !!python,
  };
}

module.exports = {
  npmCommand,
  npmBinary,
  commandMatchesFromPath,
  commandOwnedByPackage,
  readVersion,
  uninstallFromMachine,
  selfCheck,
};
