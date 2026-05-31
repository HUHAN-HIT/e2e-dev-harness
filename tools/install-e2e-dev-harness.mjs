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
    repo: REPO_ROOT,
    projectRoot: null,
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
    doctor: false,
    strictSuperpowers: false,
    superpowersDir: null,
    checkOnly: false,
    extras: ["dev", "ast"],
    full: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const value = () => {
      index += 1;
      if (index >= argv.length) throw new Error(`${arg} requires a value`);
      return argv[index];
    };

    if (arg === "--repo") args.repo = value();
    else if (arg === "--project-root" || arg === "--project" || arg === "--hook-repo") args.projectRoot = value();
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
    else if (arg === "--doctor") args.doctor = true;
    else if (arg === "--strict-superpowers") args.strictSuperpowers = true;
    else if (arg === "--superpowers-dir") args.superpowersDir = value();
    else if (arg === "--check-only") args.checkOnly = true;
    else if (arg === "--full") args.full = true;
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
  if (args.full) {
    args.target = "all";
    args.installExternal = true;
    args.withHooks = true;
    args.runtime = "claude";
    args.doctor = true;
  }
  return args;
}

function helpText() {
  return [
    "Usage: node tools/install-e2e-dev-harness.mjs [options]",
    "",
    "Options:",
    "  --full                             Preset: --target all --install-external --with-hooks --runtime claude --doctor",
    "  --target codex|claude|agents|all   Runtime skill target (default: codex)",
    "  --install-root <path>              Root that contains .codex/.claude/.agents",
    "  --repo <path>                      Harness source repository root (default: installer repo)",
    "  --project-root, --project <path>   Business project root for hooks and doctor",
    "  --yes                              Execute planned writes and commands",
    "  --json                             Print JSON",
    "  --skip-python-cli                  Do not install editable Python CLI",
    "  --install-external                 Install missing GitNexus/Graphify",
    "  --skip-external                    Check external dependencies only",
    "  --with-hooks --runtime claude      Install runtime hooks",
    "  --doctor                           Run harness doctor against project root",
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

function quoteArg(value) {
  const text = String(value);
  if (!/[\s"]/u.test(text)) return text;
  return `"${text.replace(/"/g, '\\"')}"`;
}

function pythonCommand(script, args) {
  return ["python", quoteArg(script), ...args.map(quoteArg)].join(" ");
}

function actions(options, repo, projectRoot, installRoot, sourceSkillDir, targets, status) {
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
    const hookScript = path.join(sourceSkillDir, "scripts", "install_hooks.py");
    planned.push({
      id: "install-hooks",
      description: `Install ${options.runtime} hook configuration into the project root.`,
      command: pythonCommand(hookScript, [projectRoot, "--runtime", options.runtime, "--json"]),
      cwd: repo,
      project_root: projectRoot,
    });
  }
  if (options.doctor && !options.checkOnly) {
    const cliScript = path.join(sourceSkillDir, "scripts", "e2e_dev_harness.py");
    planned.push({
      id: "doctor",
      description: "Run e2e-dev-harness doctor against the project root.",
      command: pythonCommand(cliScript, ["doctor", projectRoot, "--json"]),
      cwd: repo,
      project_root: projectRoot,
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
    project_root: payload.project_root,
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
    `Project root: ${payload.project_root}`,
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
  const projectRoot = path.resolve(options.projectRoot || options.repo);
  const installRoot = path.resolve(options.installRoot);
  const sourceSkillDir = path.resolve(options.sourceSkillDir || path.join(repo, "skills", SKILL_NAME));
  const targets = resolveTargets(options.target);
  const checkResult = checks(options, repo, sourceSkillDir);
  const plannedActions = actions(options, repo, projectRoot, installRoot, sourceSkillDir, targets, checkResult);
  const blocked = [];

  if (!fs.existsSync(repo)) blocked.push(`Repository root does not exist: ${repo}`);
  if ((options.withHooks || options.doctor) && !fs.existsSync(projectRoot)) {
    blocked.push(`Project root does not exist: ${projectRoot}`);
  }
  if (!checkResult.skill_layout.available) blocked.push(`Source skill is missing SKILL.md: ${sourceSkillDir}`);
  if (!options.skipPythonCli && !checkResult.python.available) blocked.push("Python is required to install the editable CLI.");
  if (options.withHooks && !checkResult.python.available) blocked.push("Python is required to install hooks.");
  if (options.strictSuperpowers && !checkResult.superpowers.available) blocked.push("Required Superpowers skills are missing.");

  const payload = {
    schema: "e2e-dev-harness.installer-plan.v1",
    repo,
    project_root: projectRoot,
    install_root: installRoot,
    source_skill_dir: sourceSkillDir,
    full: options.full,
    install_external: options.installExternal,
    runtime: options.runtime,
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
