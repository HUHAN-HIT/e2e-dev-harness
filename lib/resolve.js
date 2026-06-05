const path = require('node:path');

const SUB_MAP = { status: 'doctor', dispatch: 'dispatch-status' };

// Pure: maps argv to a { file, args } spawn descriptor. No spawning, no fs.
// `install` and `--help` are handled directly in bin (need fs / detection).
function resolveCommand(home, python, argv) {
  const [cmd, ...rest] = argv;
  if (cmd === 'init') {
    return { file: python, args: [path.join(home, 'scripts', 'install_hooks.py'), ...rest] };
  }
  if (cmd === 'exec') {
    const [script, ...sargs] = rest;
    if (!script) throw new Error('exec requires a script name');
    const base = path.basename(script);
    if (base !== script || !base.endsWith('.py')) {
      throw new Error(`invalid script (must be a bare *.py name): ${script}`);
    }
    return { file: python, args: [path.join(home, 'scripts', base), ...sargs] };
  }
  const mapped = SUB_MAP[cmd] || cmd;
  return { file: python, args: [path.join(home, 'scripts', 'e2e_dev_harness.py'), mapped, ...rest] };
}

module.exports = { resolveCommand, SUB_MAP };
