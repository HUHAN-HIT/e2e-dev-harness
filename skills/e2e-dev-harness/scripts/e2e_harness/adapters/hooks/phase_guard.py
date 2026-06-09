"""v2 PreToolUse hook: phase-lock code writes (thin shell over run-state).

Reuses ported path logic (adapters.hooks.paths) and the declarative
pipeline.can_write_code gate. Stdlib only. See design §3.2.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[3]  # .../scripts
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from e2e_harness import pipeline                       # noqa: E402
from e2e_harness.core import run_state                 # noqa: E402
from e2e_harness.adapters.hooks import paths as hook_paths  # noqa: E402

_REDIRECT_TOKENS = (">", ">>", "tee", "set-content", "add-content", "out-file")
_REDIRECT_TARGET_RE = re.compile(r"(?:^|\s)(?:>>|>)\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s;&|]+))")


def paths_from_shell_command(command: str) -> list[str]:
    paths: list[str] = []
    for match in _REDIRECT_TARGET_RE.finditer(command):
        target = next((part for part in match.groups() if part), "")
        if target:
            paths.append(target)
    return paths


def parse_hook_input(text: str) -> tuple[str, list[str], str]:
    if not text.strip():
        return "", [], ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return "", [], ""
    tool = str(data.get("tool_name") or data.get("tool") or "")
    tin = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else data
    paths: list[str] = []
    command = ""
    if isinstance(tin, dict):
        for key in ("file_path", "filePath", "path", "notebook_path", "notebookPath"):
            value = tin.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(value)
        cmd = tin.get("command")
        if isinstance(cmd, str):
            command = cmd
            paths.extend(paths_from_shell_command(cmd))
    return tool, paths, command


def _allow() -> dict:
    return {"decision": "allow", "reason": ""}


def _deny(reason: str) -> dict:
    return {"decision": "deny", "reason": reason}


def decide(hook_text: str, repo, run_state_path) -> dict:
    repo = Path(repo)
    _tool, raw_paths, command = parse_hook_input(hook_text)
    paths = [Path(p) for p in raw_paths]

    # Control-file / hook-config direct writes are always denied (bypass guard).
    for p in paths:
        if hook_paths.is_control_file_path(repo, p):
            return _deny(
                f"Blocked: direct write to control file '{p.name}'.\n"
                "WHY: this file is the harness single source of truth (SSOT), owned exclusively "
                "by the CLI — hand-editing it corrupts run-state and skips gate evidence.\n"
                f"RECOVER: never edit run-state.json by hand. Inspect the current allowed action "
                f"with `e2e-harness-v2 status --state {run_state_path}`, then mutate state only "
                "through `next` / `gate` / `submit`."
            )
        if hook_paths.is_hook_config_path(repo, p):
            return _deny(
                "Blocked: direct edit of hook configuration.\n"
                "WHY: editing the hook config during a run would disable the phase guard itself "
                "(enforcement bypass).\n"
                "RECOVER: change hook wiring via the installer "
                "(`install-e2e-dev-harness --with-hooks --runtime <claude|opencode>`), not by "
                "editing .claude/settings.json mid-run."
            )
    low = command.lower()
    if "run-state.json" in low and any(tok in low for tok in _REDIRECT_TOKENS):
        return _deny(
            "Blocked: shell redirect into run-state.json.\n"
            "WHY: run-state.json is the CLI-owned SSOT; a raw redirect bypasses its schema and "
            "the gate evidence trail.\n"
            "RECOVER: use `submit` to record evidence and `next` / `gate` to advance — never "
            "redirect into run-state.json."
        )

    code_paths = [p for p in paths if hook_paths.is_code_path(repo, p)]
    if not code_paths:
        return _allow()

    if run_state_path is None or not Path(run_state_path).is_file():
        return _allow()  # no active run — require-active-run deferred (design §7)

    state = run_state.load(run_state_path)
    if pipeline.can_write_code(state):
        return _allow()
    phase = state.get("current_phase", "<unknown>")
    run_id = state.get("run_id", "")
    pipeline_name = state.get("pipeline") or state.get("tier") or "<pipeline>"
    names = ", ".join(sorted({p.name for p in code_paths}))
    return _deny(
        f"Blocked: code write to {names} is phase-locked.\n"
        f"WHY: run '{run_id}' is at phase {phase} (pipeline '{pipeline_name}'). Production-code "
        "writes are permitted only in phases declared `allows_code_write` (e.g. IMPLEMENTED); "
        "the current phase must produce its own evidence first.\n"
        f"RECOVER: 1) see the whole journey + the single next action: "
        f"`e2e-harness-v2 status --state {run_state_path}`; "
        f"2) finish this phase's expected_outputs and record them: "
        f"`e2e-harness-v2 submit --state {run_state_path} --phase {phase} --key <k> --path <p>`; "
        f"3) advance with `e2e-harness-v2 next --state {run_state_path}` (and `gate` to clear the "
        "exit gate) until a code-write phase is active, then retry this edit. "
        f"If {names} is NOT production code, write it under an allowed path (docs/, test evidence)."
    )


def _emit(result: dict) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": result["decision"],
            "permissionDecisionReason": result["reason"],
        }
    }, ensure_ascii=False))


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--state", default=None)
    parser.add_argument("--hook-input", default="-", help="JSON hook input, or '-' for stdin.")
    args = parser.parse_args(argv)
    text = sys.stdin.read() if args.hook_input == "-" else args.hook_input
    repo = Path(args.repo)
    rsp = Path(args.state) if args.state else hook_paths.discover_run_state(repo)
    _emit(decide(text, repo, rsp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
