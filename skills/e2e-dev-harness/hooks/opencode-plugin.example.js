// e2e-dev-harness opencode plugin (example template).
// The installer (`e2e-harness init --runtime opencode`, or
// install-e2e-dev-harness.mjs --target opencode --with-hooks --runtime opencode)
// rewrites __HARNESS_SCRIPTS__ to the installed skill's absolute scripts dir and
// drops this file into <project>/.opencode/plugins/e2e-dev-harness.js.
//
// Two guards bridge to the SAME stdlib Python adapters the Claude Code hooks use:
//
//   tool.execute.before -> phase_guard.py : HARD phase-lock on code writes.
//     opencode lets a plugin throw to block the tool call — full parity with
//     Claude Code's PreToolUse `permissionDecision: deny`.
//
//   event "session.idle" -> stop_guard.py : SOFT continue-until-VERIFIED reminder.
//     opencode has NO veto-the-stop primitive — `session.idle` is observe-only and
//     there is no Claude Code `Stop`-style "block and force continuation". So this
//     CANNOT force the agent to keep going; it surfaces the stop guard's reason as
//     a warning via client.app.log. The run-to-VERIFIED guarantee is therefore
//     ADVISORY under opencode, not enforced. (See https://opencode.ai/docs/plugins/)
const { spawnSync } = require("child_process");

const PHASE_GUARD = "__HARNESS_SCRIPTS__/e2e_harness/adapters/hooks/phase_guard.py";
const STOP_GUARD = "__HARNESS_SCRIPTS__/e2e_harness/adapters/hooks/stop_guard.py";

function runGuard(script, payload) {
  const res = spawnSync("python", [script, "--repo", ".", "--hook-input", "-"], {
    input: payload,
    encoding: "utf-8",
  });
  try {
    return JSON.parse(res.stdout || "{}");
  } catch (e) {
    return {}; // fail-open on parse error
  }
}

module.exports.E2eDevHarnessPlugin = async ({ client }) => ({
  "tool.execute.before": async (input, output) => {
    const parsed = runGuard(
      PHASE_GUARD,
      JSON.stringify({ tool_name: input.tool, tool_input: output.args }),
    );
    const decision = (parsed.hookSpecificOutput || {}).permissionDecision;
    if (decision === "deny") {
      throw new Error(
        (parsed.hookSpecificOutput || {}).permissionDecisionReason
          || "phase_guard denied this write",
      );
    }
  },

  event: async ({ event }) => {
    // SOFT reminder only — opencode cannot block session.idle (see header).
    if (event.type !== "session.idle") return;
    const parsed = runGuard(STOP_GUARD, "{}");
    if (parsed.decision === "block" && client && client.app && client.app.log) {
      await client.app.log({
        body: {
          service: "e2e-dev-harness",
          level: "warn",
          message: parsed.reason || "run is not yet VERIFIED",
        },
      });
    }
  },
});
