const fsDefault = require('node:fs');
const path = require('node:path');
const { toShellScriptsDir } = require('./hooks');

const PLACEHOLDER = '__HARNESS_SCRIPTS__';
const TEMPLATE_REL = path.join('hooks', 'opencode-plugin.example.js');
// opencode auto-loads JS/TS files from <project>/.opencode/plugins/ at startup
// (see https://opencode.ai/docs/plugins/). Note the *plural* "plugins".
const PLUGIN_REL = path.join('.opencode', 'plugins', 'e2e-dev-harness.js');

// Materialize the opencode plugin into the project's .opencode/plugins/ dir.
// Mirrors lib/hooks.js materializeHooks, but the opencode runtime consumes a JS
// plugin file (not a settings.json merge), so this writes a single rendered file
// with __HARNESS_SCRIPTS__ rewritten to the installed skill's scripts dir.
// Idempotent: re-running with identical content is a no-op; a differing existing
// file is backed up to <plugin>.bak before being overwritten.
function materializeOpencodePlugin({ skillHome, projectRoot, dryRun = false, fsImpl = fsDefault }) {
  const fs = fsImpl;
  const scriptsDir = path.join(skillHome, 'scripts');
  const templatePath = path.join(skillHome, TEMPLATE_REL);
  // Embed the shell/Bun-safe forward-slash form so a Windows backslash path is
  // not mangled when the plugin spawns python (same rationale as hooks.js).
  const rendered = fs
    .readFileSync(templatePath, 'utf8')
    .split(PLACEHOLDER)
    .join(toShellScriptsDir(scriptsDir));

  const pluginPath = path.join(projectRoot, PLUGIN_REL);
  const exists = fs.existsSync(pluginPath);
  const current = exists ? fs.readFileSync(pluginPath, 'utf8') : null;
  const alreadyPresent = current === rendered ? 1 : 0;
  const added = alreadyPresent ? 0 : 1;

  if (dryRun) {
    return { pluginPath, scriptsDir, added, alreadyPresent, backup: null };
  }

  let backup = null;
  if (exists && current !== rendered) {
    backup = `${pluginPath}.bak`;
    fs.copyFileSync(pluginPath, backup);
  }
  if (added) {
    fs.mkdirSync(path.dirname(pluginPath), { recursive: true });
    try {
      fs.writeFileSync(pluginPath, rendered);
    } catch (err) {
      if (backup) fs.copyFileSync(backup, pluginPath);
      else if (fs.existsSync(pluginPath)) fs.rmSync(pluginPath, { force: true });
      throw err;
    }
  }
  return { pluginPath, scriptsDir, added, alreadyPresent, backup };
}

module.exports = { materializeOpencodePlugin, PLUGIN_REL };
