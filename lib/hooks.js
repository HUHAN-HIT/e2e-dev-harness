const fsDefault = require('node:fs');
const path = require('node:path');

const PLACEHOLDER = '__HARNESS_V2_SCRIPTS__';
const TEMPLATE_REL = path.join('hooks', 'claude-code-settings.example.json');

// Replace the placeholder ONLY inside string leaves. The template is parsed as
// JSON first, then walked, because substituting a Windows path (with
// backslashes) into raw JSON text would break a later JSON.parse.
function substituteScriptsDir(value, scriptsDir) {
  if (typeof value === 'string') return value.split(PLACEHOLDER).join(scriptsDir);
  if (Array.isArray(value)) return value.map((v) => substituteScriptsDir(v, scriptsDir));
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, substituteScriptsDir(v, scriptsDir)])
    );
  }
  return value;
}

function commandsOf(groups) {
  const set = new Set();
  for (const group of groups || []) {
    for (const hook of group.hooks || []) {
      if (hook && typeof hook.command === 'string') set.add(hook.command);
    }
  }
  return set;
}

// Merge the template's hook groups into existing settings, skipping any command
// already present (idempotent). Returns the merged object and counters.
function mergeHooks(existing, templateHooks) {
  const merged = { ...existing, hooks: { ...(existing.hooks || {}) } };
  let added = 0;
  let alreadyPresent = 0;

  for (const [event, incomingGroups] of Object.entries(templateHooks || {})) {
    const current = Array.isArray(merged.hooks[event]) ? merged.hooks[event].slice() : [];
    const present = commandsOf(current);
    for (const group of incomingGroups) {
      const incoming = (group.hooks || []).map((h) => h.command);
      const fresh = (group.hooks || []).filter((h) => !present.has(h.command));
      added += fresh.length;
      alreadyPresent += incoming.length - fresh.length;
      if (fresh.length) {
        current.push({ ...group, hooks: fresh });
        for (const h of fresh) present.add(h.command);
      }
    }
    merged.hooks[event] = current;
  }
  return { merged, added, alreadyPresent };
}

function readJsonOrEmpty(fs, file) {
  if (!fs.existsSync(file)) return { value: {}, existed: false };
  try {
    return { value: JSON.parse(fs.readFileSync(file, 'utf8')), existed: true };
  } catch {
    // Unparseable settings are treated as empty; the original is preserved in
    // the backup we take before writing.
    return { value: {}, existed: true };
  }
}

function materializeHooks({ skillHome, projectRoot, dryRun = false, fsImpl = fsDefault }) {
  const fs = fsImpl;
  const scriptsDir = path.join(skillHome, 'scripts');
  const templatePath = path.join(skillHome, TEMPLATE_REL);
  const template = substituteScriptsDir(
    JSON.parse(fs.readFileSync(templatePath, 'utf8')),
    scriptsDir
  );

  const settingsPath = path.join(projectRoot, '.claude', 'settings.json');
  const { value: existing, existed } = readJsonOrEmpty(fs, settingsPath);
  const { merged, added, alreadyPresent } = mergeHooks(existing, template.hooks);

  if (dryRun) {
    return { settingsPath, scriptsDir, added, alreadyPresent, backup: null };
  }

  let backup = null;
  if (existed) {
    backup = `${settingsPath}.bak`;
    fs.copyFileSync(settingsPath, backup);
  } else {
    fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
  }

  try {
    fs.writeFileSync(settingsPath, JSON.stringify(merged, null, 2) + '\n');
  } catch (err) {
    if (backup) {
      fs.copyFileSync(backup, settingsPath);
    } else if (fs.existsSync(settingsPath)) {
      fs.rmSync(settingsPath, { force: true });
    }
    throw err;
  }

  return { settingsPath, scriptsDir, added, alreadyPresent, backup };
}

module.exports = { materializeHooks, substituteScriptsDir, mergeHooks };
