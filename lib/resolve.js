const path = require('node:path');

// e2e-dev-harness verbs (e2e_harness/cli/main.py). Passed through verbatim
// to the v2 argparse CLI; unknown verbs are rejected by argparse downstream.
const V2_VERBS = new Set([
  'start', 'next', 'dispatch', 'submit', 'gate', 'status', 'validate-pipeline',
]);

// Pure: maps argv to a { file, args } spawn descriptor. No spawning, no fs.
// `install` and `--help` are handled directly in bin (need fs / detection).
function resolveCommand(home, python, argv) {
  const [cmd, ...rest] = argv;
  if (cmd === 'exec') {
    const [script, ...sargs] = rest;
    if (!script) throw new Error('exec requires a script name');
    const base = path.basename(script);
    if (base !== script || !base.endsWith('.py')) {
      throw new Error(`invalid script (must be a bare *.py name): ${script}`);
    }
    return { file: python, args: [path.join(home, 'scripts', base), ...sargs] };
  }
  return {
    file: python,
    args: [path.join(home, 'scripts', 'e2e_dev_harness.py'), cmd, ...rest],
  };
}

module.exports = { resolveCommand, V2_VERBS };
