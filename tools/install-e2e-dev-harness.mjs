#!/usr/bin/env node
import childProcess from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const SKILL_NAME = "e2e-dev-harness";
const SCRIPT_PATH = fileURLToPath(import.meta.url);
const REPO_ROOT = path.resolve(path.dirname(SCRIPT_PATH), "..");
const TARGETS = {
  codex: [".codex", "skills", SKILL_NAME],
  claude: [".claude", "skills", SKILL_NAME],
  agents: [".agents", "skills", SKILL_NAME],
};

function parseArgs(argv) {
  const args = {
    repo: process.cwd(),
    installRoot: os.homedir(),
    sourceSkillDir: null,
    target: "codex",
    yes: false,
    json: false,
    skipPythonCli: false,
    skipExternal: false,
    installExternal: false,
    withHooks: false,
    runtime: "claude",
    strictSuperpowers: false,
    superpowersDir: null,
    checkOnly: false,
    extras: ["dev", "ast"],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const value = () => {
      index += 1;
      if (index >= argv.length) throw new Error(`${arg} requires a value`);
      return argv[index];
    };

    if (arg === "--repo") args.repo = value();
    else if (arg === "--install-root") args.installRoot = value();
    else if (arg === "--source-skill-dir") args.sourceSkillDir = value();
    else if (arg === "--target") args.target = value().toLowerCase();
    else if (arg === "--yes") args.yes = true;
    else if (arg === "--json") args.json = true;
    else if (arg === "--skip-python-cli") args.skipPythonCli = true;
    else if (arg === "--skip-external") args.skipExternal = true;
    else if (arg === "--install-external") args.installExternal = true;
    else if (arg === "--with-hooks") args.withHooks = true;
    else if (arg === "--runtime") args.runtime = value().toLowerCase();
    else if (arg === "--strict-superpowers") args.strictSuperpowers = true;
    else if (arg === "--superpowers-dir") args.superpowersDir = value();
    else if (arg === "--check-only") args.checkOnly = true;
    else if (arg === "--no-dev") args.extras = args.extras.filter((item) => item !== "dev");
    else if (arg === "--no-ast") args.extras = args.extras.filter((item) => item !== "ast");
    else if (arg === "--help" || arg === "-h") args.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }

  if (!["codex", "claude", "agents", "all"].includes(args.target)) {
    throw new Error("--target must be codex, claude, agents, or all");
  }
  if (args.installExternal && args.skipExternal) {
    throw new Error("--install-external and --skip-external cannot be used together");
  }
  return args;
}

function helpText() {
  return [
    "Usage: node tools/install-e2e-dev-harness.mjs [options]",
    "",
    "Options:",
    "  --target codex|claude|agents|all   Runtime skill target (default: codex)",
    "  --install-root <path>              Root that contains .codex/.claude/.agents",
    "  --repo <path>                      Repository root for CLI and hook commands",
    "  --yes                              Execute planned writes and commands",
    "  --json                             Print JSON",
    "  --skip-python-cli                  Do not install editable Python CLI",
    "  --install-external                 Install missing GitNexus/Graphify",
    "  --skip-external                    Check external dependencies only",
    "  --with-hooks --runtime claude      Install runtime hooks",
    "  --strict-superpowers               Fail when required Superpowers skills are missing",
    "  --superpowers-dir <path>           Check a provided Superpowers skills directory",
    "  --check-only                       Run checks without planning writes",
  ].join("\n");
}

function resolveTargets(target) {
  return target === "all" ? ["codex", "claude", "agents"] : [target];
}

function findCommand(command) {
  const locator = process.platform === "win32" ? "where" : "which";
  const completed = childProcess.spawnSync(locator, [command], { encoding: "utf8" });
  if (completed.status !== 0) return "";
  return completed.stdout.split(/\r?\n/).map((line) => line.trim()).find(Boolean) || "";
}

function runCommand(command, cwd) {
  const parts = command.match(/(?:[^\s"]+|"[^"]*")+/g)?.map((part) => part.replace(/^"|"$/g, "")) || [];
  const [bin, ...args] = parts;
  const completed = childProcess.spawnSync(bin, args, {
    cwd,
    encoding: "utf8",
    shell: false,
  });
  return {
    command,
    exit_code: completed.status ?? 1,
    stdout_tail: (completed.stdout || "").slice(-4000),
    stderr_tail: (completed.stderr || completed.error?.message || "").slice(-4000),
  };
}

function pythonBin() {
  if (findCommand("python")) return "python";
  if (findCommand("py")) return "py";
  return "";
}

function copyDirectory(source, destination) {
  fs.mkdirSync(destination, { recursive: true });
  let files = 0;
  let directories = 1;
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    if (entry.name === "__pycache__" || entry.name.endsWith(".egg-info") || entry.name === ".pytest_cache") {
      continue;
    }
    const sourcePath = path.join(source, entry.name);
    const destinationPath = path.join(destination, entry.name);
    if (entry.isDirectory()) {
      const result = copyDirectory(sourcePath, destinationPath);
      files += result.files;
      directories += result.directories;
    } else if (entry.isFile()) {
      fs.mkdirSync(path.dirname(destinationPath), { recursive: true });
      fs.copyFileSync(sourcePath, destinationPath);
      files += 1;
    }
  }
  return { files, directories };
}

function backupExisting(destination, installRoot, target, timestamp) {
  if (!fs.existsSync(destination)) return null;
  const backup = path.join(installRoot, ".e2e-dev-harness-backups", timestamp, target, SKILL_NAME);
  fs.mkdirSync(path.dirname(backup), { recursive: true });
  copyDirectory(destination, backup);
  fs.rmSync(destination, { recursive: true, force: true });
  return backup;
}

function superpowersCheck(options, repo, python) {
  const required = ["using-superpowers", "brainstorming", "writing-plans", "test-driven-development"];
  if (options.superpowersDir) {
    const base = path.resolve(options.superpowersDir);
    const missing = required.filter((name) => !fs.existsSync(path.join(base, name, "SKILL.md")));
    return { available: missing.length === 0, source: "provided-dir", path: base, missing };
  }

  const probe = path.join(repo, "skills", SKILL_NAME, "scripts", "superpowers_probe.py");
  if (!python || !fs.existsSync(probe)) {
    return { available: false, source: "probe", path: probe, missing: required };
  }
  const completed = childProcess.spawnSync(python, [probe, "--json"], {
    cwd: repo,
    encoding: "utf8",
    shell: false,
  });
  if (completed.status !== 0) {
    return { available: false, source: "probe", path: probe, error: (completed.stderr || completed.stdout).slice(-2000) };
  }
  try {
    const payload = JSON.parse(completed.stdout);
    return {
      available: Boolean(payload.available),
      source: "probe",
      path: probe,
      found: payload.found || {},
      missing: payload.missing || {},
    };
  } catch (error) {
    return { available: false, source: "probe", path: probe, error: String(error) };
  }
}

function checks(options, repo, sourceSkillDir) {
  const python = pythonBin();
  return {
    node: { available: true, path: process.execPath, version: process.version },
    python: { available: Boolean(python), path: python ? findCommand(python) : "" },
    npm: { available: Boolean(findCommand("npm")), path: findCommand("npm") },
    gitnexus: { available: Boolean(findCommand("gitnexus")), path: findCommand("gitnexus") },
    graphify: { available: Boolean(findCommand("graphify")), path: findCommand("graphify") },
    maven: { available: Boolean(findCommand("mvn") || findCommand("mvn.cmd")), path: findCommand("mvn") || findCommand("mvn.cmd") },
    skill_layout: { available: fs.existsSync(path.join(sourceSkillDir, "SKILL.md")), path: sourceSkillDir },
    superpowers: superpowersCheck(options, repo, python),
  };
}

function graphifyInstallCommand() {
  if (findCommand("uv")) return "uv tool install --upgrade graphifyy";
  if (findCommand("pipx")) return "pipx install graphifyy";
  return "python -m pip install --user graphifyy";
}

function actions(options, repo, installRoot, sourceSkillDir, targets, status) {
  const planned = [];
  if (!options.checkOnly) {
    planned.push({
      id: "copy-skill",
      description: `Copy ${SKILL_NAME} into selected runtime skill directories.`,
      targets: targets.map((target) => ({
        target,
        path: path.join(installRoot, ...TARGETS[target]),
      })),
    });
  }
  if (!options.skipPythonCli && !options.checkOnly) {
    const extras = options.extras.length ? `[${options.extras.join(",")}]` : "";
    planned.push({
      id: "install-python-cli",
      description: "Install editable Python CLI.",
      command: `python -m pip install -e .${extras}`,
      cwd: repo,
    });
  }
  if (!options.skipExternal && options.installExternal) {
    if (!status.gitnexus.available) {
      planned.push({
        id: "install-gitnexus",
        description: "Install GitNexus globally with npm.",
        command: "npm install -g gitnexus",
        cwd: repo,
      });
    }
    if (!status.graphify.available) {
      planned.push({
        id: "install-graphify",
        description: "Install Graphify CLI.",
        command: graphifyInstallCommand(),
        cwd: repo,
      });
    }
  }
  if (options.withHooks && !options.checkOnly) {
    planned.push({
      id: "install-hooks",
      description: `Install ${options.runtime} hook configuration.`,
      command: `python skills/${SKILL_NAME}/scripts/install_hooks.py . --runtime ${options.runtime} --json`,
      cwd: repo,
    });
  }
  return planned;
}

function executeAction(action, context) {
  if (action.id === "copy-skill") {
    const installed = [];
    for (const target of action.targets) {
      const backup = backupExisting(target.path, context.installRoot, target.target, context.timestamp);
      const copied = copyDirectory(context.sourceSkillDir, target.path);
      installed.push({
        target: target.target,
        path: target.path,
        backup,
        files: copied.files,
        directories: copied.directories,
      });
    }
    return { action: action.id, exit_code: 0, installed_skills: installed };
  }
  return { action: action.id, ...runCommand(action.command, action.cwd || context.repo) };
}

function writeManifest(installRoot, payload) {
  const manifest = {
    schema: "e2e-dev-harness.installer.v1",
    installed_at: new Date().toISOString(),
    repo: payload.repo,
    source_skill_dir: payload.source_skill_dir,
    targets: payload.targets,
    installed_skills: payload.installed_skills,
    checks: payload.checks,
  };
  const target = path.join(installRoot, ".e2e-dev-harness-install.json");
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  return target;
}

function textOutput(payload) {
  const lines = [
    `E2E Dev Harness installer: ${payload.ready ? "READY" : "BLOCKED"}`,
    `Mode: ${payload.mode}`,
    `Targets: ${payload.targets.join(", ")}`,
    `Install root: ${payload.install_root}`,
    "",
    "Actions:",
  ];
  for (const action of payload.actions) {
    lines.push(`- ${action.id}: ${action.description}`);
    if (action.command) lines.push(`  ${action.command}`);
  }
  if (!payload.executed) lines.push("", "Dry-run only. Re-run with --yes to execute.");
  if (payload.blocked_reasons.length) {
    lines.push("", "Blocked:");
    for (const reason of payload.blocked_reasons) lines.push(`- ${reason}`);
  }
  return `${lines.join("\n")}\n`;
}

function main() {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${error.message}\n${helpText()}\n`);
    return 2;
  }
  if (options.help) {
    process.stdout.write(`${helpText()}\n`);
    return 0;
  }

  const repo = path.resolve(options.repo);
  const installRoot = path.resolve(options.installRoot);
  const sourceSkillDir = path.resolve(options.sourceSkillDir || path.join(repo, "skills", SKILL_NAME));
  const targets = resolveTargets(options.target);
  const checkResult = checks(options, repo, sourceSkillDir);
  const plannedActions = actions(options, repo, installRoot, sourceSkillDir, targets, checkResult);
  const blocked = [];

  if (!fs.existsSync(repo)) blocked.push(`Repository root does not exist: ${repo}`);
  if (!checkResult.skill_layout.available) blocked.push(`Source skill is missing SKILL.md: ${sourceSkillDir}`);
  if (!options.skipPythonCli && !checkResult.python.available) blocked.push("Python is required to install the editable CLI.");
  if (options.withHooks && !checkResult.python.available) blocked.push("Python is required to install hooks.");
  if (options.strictSuperpowers && !checkResult.superpowers.available) blocked.push("Required Superpowers skills are missing.");

  const payload = {
    schema: "e2e-dev-harness.installer-plan.v1",
    repo,
    install_root: installRoot,
    source_skill_dir: sourceSkillDir,
    mode: options.yes ? "execute" : "dry-run",
    executed: false,
    targets,
    checks: checkResult,
    actions: plannedActions,
    action_results: [],
    installed_skills: [],
    manifest: null,
    ready: blocked.length === 0,
    blocked_reasons: blocked,
  };

  if (payload.ready && options.yes) {
    fs.mkdirSync(installRoot, { recursive: true });
    const timestamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+$/, "").replace("T", "-");
    const context = { repo, installRoot, sourceSkillDir, timestamp };
    for (const action of plannedActions) {
      const result = executeAction(action, context);
      payload.action_results.push(result);
      if (result.installed_skills) payload.installed_skills.push(...result.installed_skills);
      if (result.exit_code !== 0) {
        payload.ready = false;
        payload.blocked_reasons.push(`Action failed: ${action.id}`);
        break;
      }
    }
    if (payload.ready) payload.manifest = writeManifest(installRoot, payload);
    payload.executed = true;
  }

  process.stdout.write(options.json ? `${JSON.stringify(payload, null, 2)}\n` : textOutput(payload));
  return payload.ready ? 0 : 2;
}

process.exitCode = main();
