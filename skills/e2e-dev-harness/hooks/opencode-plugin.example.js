import { spawnSync } from "node:child_process";

const PYTHON = __E2E_DEV_HARNESS_PYTHON__;
// install_hooks.py replaces this with an absolute phase_guard.py path.
const PHASE_GUARD = __E2E_DEV_HARNESS_PHASE_GUARD__;
const TARGET_REPO = __E2E_DEV_HARNESS_TARGET_REPO__;

// Read-only exploration tools take the fast lane: phase_guard does not gate
// them, so pure exploration never triggers the harness gate tug-of-war.
const READ_ONLY_TOOLS = new Set(["read", "read_file", "grep", "glob", "list", "ls"]);

function normalizeToolInput(args = {}) {
  const input = { ...args };
  if (input.filePath && !input.file_path) input.file_path = input.filePath;
  if (input.patchText && !input.patch) input.patch = input.patchText;
  return input;
}

function guard(tool, args) {
  const payload = JSON.stringify({
    tool,
    tool_name: tool,
    tool_input: normalizeToolInput(args),
  });
  const result = spawnSync(
    PYTHON,
    [
      PHASE_GUARD,
      TARGET_REPO,
      "--hook-input",
      "-",
      "--require-active-run-for-read",
      "--require-session-checkpoint",
      "--checkpoint-max-age-minutes",
      "30",
      "--compact-guidance",
      "--json",
    ],
    { input: payload, encoding: "utf-8" },
  );
  if (result.status !== 0) {
    const detail = result.stdout || result.stderr || `phase_guard.py exited ${result.status}`;
    throw new Error(`e2e-dev-harness blocked ${tool}: ${detail}`);
  }
}

export const E2EDevHarnessPhaseGuard = async () => ({
  "tool.execute.before": async (input, output) => {
    const tool = input?.tool || input?.toolID || output?.tool || "unknown";
    if (READ_ONLY_TOOLS.has(String(tool).toLowerCase())) return;
    const args = output?.args || input?.args || input?.tool_input || {};
    guard(tool, args);
  },
});
