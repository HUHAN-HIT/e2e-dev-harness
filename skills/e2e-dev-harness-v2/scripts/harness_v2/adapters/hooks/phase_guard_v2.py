"""v2 PreToolUse hook: phase-lock code writes (thin shell over run-state).

Reuses ported path logic (adapters.hooks.paths) and the declarative
pipeline.can_write_code gate. Stdlib only. See design §3.2.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[3]  # .../scripts
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from harness_v2 import pipeline                       # noqa: E402
from harness_v2.core import run_state                 # noqa: E402
from harness_v2.adapters.hooks import paths as hook_paths  # noqa: E402

_REDIRECT_TOKENS = (">", ">>", "tee", "set-content", "add-content", "out-file")


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
                f"Direct write to control file {p.name} is not allowed; the harness "
                "CLI owns run-state.json. Use `next` / `gate` / `submit` instead."
            )
        if hook_paths.is_hook_config_path(repo, p):
            return _deny("Direct edit of hook config is not allowed (would bypass the phase guard).")
    low = command.lower()
    if "run-state.json" in low and any(tok in low for tok in _REDIRECT_TOKENS):
        return _deny("Shell redirect into run-state.json is not allowed; the harness CLI owns it.")

    code_paths = [p for p in paths if hook_paths.is_code_path(repo, p)]
    if not code_paths:
        return _allow()

    if run_state_path is None or not Path(run_state_path).is_file():
        return _allow()  # no active run — require-active-run deferred (design §7)

    state = run_state.load(run_state_path)
    if pipeline.can_write_code(state):
        return _allow()
    phase = state.get("current_phase", "<unknown>")
    return _deny(
        f"Code write blocked: phase {phase} does not allow code writes. Advance the run "
        f"with `python -m harness_v2 next --state {run_state_path}` (then `gate` to satisfy "
        "the exit gate) until an implementation phase is active."
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
