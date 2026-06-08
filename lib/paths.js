const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');

function skillHome() {
  return process.env.E2E_HARNESS_HOME
    || path.join(os.homedir(), '.claude', 'skills', 'e2e-dev-harness-v2');
}

function recordedPython(home) {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(home, '.harness-env.json'), 'utf8'));
    if (data && typeof data.python === 'string') return data.python;
  } catch { /* no env file */ }
  return null;
}

function detectPython() {
  const candidates = process.platform === 'win32'
    ? ['python', 'python3', 'py']
    : ['python3', 'python'];
  for (const c of candidates) {
    try {
      execFileSync(c, ['--version'], { stdio: 'ignore' });
      return c;
    } catch { /* try next */ }
  }
  return null;
}

function resolvePython(home) {
  if (process.env.E2E_HARNESS_PYTHON) return process.env.E2E_HARNESS_PYTHON;
  return recordedPython(home) || detectPython();
}

module.exports = { skillHome, resolvePython, detectPython, recordedPython };
