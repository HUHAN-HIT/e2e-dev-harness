// e2e-dev-harness opencode plugin (example template).
// U6 installer rewrites __HARNESS_SCRIPTS__ to the installed absolute scripts dir.
const { spawnSync } = require("child_process");

const PHASE_GUARD = "__HARNESS_SCRIPTS__/e2e_harness/adapters/hooks/phase_guard.py";

module.exports = {
  "tool.execute.before": async (input, output) => {
    const payload = JSON.stringify({ tool_name: input.tool, tool_input: output.args });
    const res = spawnSync("python", [PHASE_GUARD, "--repo", ".", "--hook-input", "-"], {
      input: payload,
      encoding: "utf-8",
    });
    let parsed;
    try {
      parsed = JSON.parse(res.stdout || "{}");
    } catch (e) {
      return; // fail-open on parse error
    }
    const decision = (parsed.hookSpecificOutput || {}).permissionDecision;
    if (decision === "deny") {
      throw new Error((parsed.hookSpecificOutput || {}).permissionDecisionReason || "phase_guard denied this write");
    }
  },
};
