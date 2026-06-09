#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const SCRIPT_PATH = fileURLToPath(import.meta.url);
const REPO_ROOT = path.resolve(path.dirname(SCRIPT_PATH), "..");
const DEFAULT_REPO = "e2e-dev-workflow";

export function buildPlan(options = {}) {
  const repo = options.repo || DEFAULT_REPO;
  const plan = [
    { name: "git-status", command: ["git", "status", "--short", "--branch"] },
    { name: "node-tests", command: ["npm", "test"] },
    { name: "python-tests", command: ["python", "-m", "pytest", "skills/e2e-dev-harness/tests", "tests/test_node_installer.py", "-q"] },
  ];

  if (!options.skipGitNexus) {
    plan.push({
      name: "gitnexus-detect-changes",
      command: ["npx", "gitnexus", "detect-changes", "--scope", "all", "--repo", repo],
    });
  }

  return plan;
}

function commandText(command) {
  return command.map((part) => (/\s/.test(part) ? `"${part}"` : part)).join(" ");
}

function spawnStep(step, options) {
  const [file, ...args] = step.command;
  const needsWindowsShell = process.platform === "win32" && (file === "npm" || file === "npx");
  const resolvedFile = needsWindowsShell ? `${file}.cmd` : file;
  const spawnFile = needsWindowsShell ? (process.env.ComSpec || "cmd.exe") : resolvedFile;
  const spawnArgs = needsWindowsShell
    ? ["/d", "/s", "/c", commandText([resolvedFile, ...args])]
    : args;
  const completed = spawnSync(spawnFile, spawnArgs, {
    cwd: options.cwd,
    stdio: "inherit",
    shell: false,
  });
  if (completed.error) console.error(`[pre-merge-check] ${completed.error.message}`);
  return completed;
}

export function runPlan(plan, options = {}) {
  const cwd = options.cwd || REPO_ROOT;
  const runCommand = options.runCommand || spawnStep;
  const log = options.log || console.log;
  const error = options.error || console.error;
  const results = [];

  for (const step of plan) {
    log(`\n[pre-merge-check] ${step.name}: ${commandText(step.command)}`);
    const completed = runCommand(step, { cwd });
    const status = completed.status ?? 1;
    results.push({ name: step.name, status });
    if (status !== 0) {
      error(`[pre-merge-check] failed at ${step.name} (exit ${status})`);
      return { exitCode: status, results };
    }
  }

  log("\n[pre-merge-check] all checks passed");
  return { exitCode: 0, results };
}

function parseArgs(argv) {
  const options = { repo: DEFAULT_REPO, skipGitNexus: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--skip-gitnexus") options.skipGitNexus = true;
    else if (arg === "--repo") {
      index += 1;
      if (index >= argv.length) throw new Error("--repo requires a value");
      options.repo = argv[index];
    } else if (arg === "--help" || arg === "-h") {
      options.help = true;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return options;
}

function helpText() {
  return [
    "Usage: node tools/pre-merge-check.mjs [options]",
    "",
    "Runs the local checks expected before merging a development branch:",
    "  git status --short --branch",
    "  npm test",
    "  python -m pytest skills/e2e-dev-harness/tests tests/test_node_installer.py -q",
    "  npx gitnexus detect-changes --scope all --repo e2e-dev-workflow",
    "",
    "Options:",
    "  --repo <name>        GitNexus repository name (default: e2e-dev-workflow)",
    "  --skip-gitnexus      Skip GitNexus detect-changes",
    "  -h, --help           Show this help",
  ].join("\n");
}

export function main(argv = process.argv.slice(2)) {
  let options;
  try {
    options = parseArgs(argv);
  } catch (error) {
    console.error(error.message);
    console.error(helpText());
    return 2;
  }

  if (options.help) {
    console.log(helpText());
    return 0;
  }

  return runPlan(buildPlan(options), { cwd: REPO_ROOT }).exitCode;
}

if (process.argv[1] && path.resolve(process.argv[1]) === SCRIPT_PATH) {
  process.exitCode = main();
}
