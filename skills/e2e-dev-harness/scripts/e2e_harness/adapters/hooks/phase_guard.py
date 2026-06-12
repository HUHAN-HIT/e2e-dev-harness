"""PreToolUse hook: phase-lock code writes (thin shell over run-state).

Reuses ported path logic (adapters.hooks.paths) and the declarative
pipeline.can_write_code gate. Stdlib only. See design §3.2.
"""
from __future__ import annotations

import json
import re
import shlex
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


# --- G1/G2: writes that bypass Edit/Write -------------------------------------
# Threat model: prevent *unintentional* phase-lock / SSOT bypass — a worker
# reaching for a shell write (sed -i / cp / mv / tee / dd) or an inline program
# instead of the Edit/Write tool. We split on shell operators, then extract each
# write command's target(s) so the SAME code/control-file classification used for
# Edit/Write applies uniformly. This is deliberately NOT hardened against a
# determined adversary obfuscating argv (base64 | sh, eval, exotic quoting); that
# is out of scope (see design §3.2 — guard against accidents, not attackers).
_WRITE_HINT_RE = re.compile(
    r"\bopen\s*\(|\.write\s*\(|\.write_text\b|\bshutil\.|\bos\.replace\b|"
    r"\bjson\.dump\b|Path\([^)]*\)\.write"
)
_SEGMENT_SPLIT_RE = re.compile(r"\|\||&&|[|;&]")


def _command_name(value: str) -> str:
    name = Path(value).name.lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _segments(command: str) -> list[str]:
    """Split a shell command on control operators (| || && ; &) so a write hidden
    after a pipe/chain (`echo x | tee f.py`, `a && sed -i … f.py`) is still seen."""
    return [seg.strip() for seg in _SEGMENT_SPLIT_RE.split(command) if seg.strip()]


def _split(command: str) -> list[str] | None:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return None


def _segment_write_paths(segment: str) -> list[str]:
    argv = _split(segment)
    if not argv:
        return []
    name = _command_name(argv[0])
    args = argv[1:]
    operands = [a for a in args if not a.startswith("-")]
    if name in {"cp", "mv", "install"}:
        return operands[-1:] if operands else []   # dest = last operand
    if name == "sed":
        if not any(a == "-i" or a.startswith("-i") for a in args):
            return []                               # not in-place → reads only
        return operands[1:]                         # operands[0] is the script
    if name == "tee":
        return operands
    if name == "dd":
        return [a[len("of="):] for a in args if a.startswith("of=")]
    return []


def paths_from_write_command(command: str) -> list[str]:
    """Best-effort write *target(s)* for recognized shell write commands
    (cp/mv/install dest, sed -i files, tee files, dd of=…). Returns [] otherwise;
    opaque writes are handled by `is_opaque_write_command`."""
    out: list[str] = []
    for seg in _segments(command):
        out.extend(_segment_write_paths(seg))
    return out


def _segment_is_opaque(segment: str) -> bool:
    argv = _split(segment)
    if argv is None:
        return bool(_WRITE_HINT_RE.search(segment))
    if not argv:
        return False
    name = _command_name(argv[0])
    args = argv[1:]
    if name == "patch":
        return True
    if name == "git" and args[:1] == ["apply"]:
        return True
    if name in {"python", "python3", "py"} and "-c" in args:
        idx = args.index("-c")
        code = args[idx + 1] if idx + 1 < len(args) else ""
        return bool(_WRITE_HINT_RE.search(code))
    return False


def is_opaque_write_command(command: str) -> bool:
    """True for writes whose target cannot be resolved from argv alone: patch /
    git apply (targets live inside the diff) and `python -c <inline write>`. A
    command we cannot even tokenize but that mentions a write verb counts too.
    These are denied conservatively in non-code-write phases."""
    return any(_segment_is_opaque(seg) for seg in _segments(command))


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
            paths.extend(paths_from_write_command(cmd))
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
                f"with `e2e-dev-harness status --state {run_state_path}`, then mutate state only "
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
    opaque_write = is_opaque_write_command(command)
    if not code_paths and not opaque_write:
        return _allow()

    if run_state_path is None or not Path(run_state_path).is_file():
        return _allow()  # no active run — require-active-run deferred (design §7)

    state = run_state.load(run_state_path)
    if pipeline.can_write_code(state):
        return _allow()
    phase = state.get("current_phase", "<unknown>")
    run_id = state.get("run_id", "")
    pipeline_name = state.get("pipeline") or state.get("tier") or "<pipeline>"
    if code_paths:
        names = ", ".join(sorted({p.name for p in code_paths}))
        return _deny(
            f"Blocked: code write to {names} is phase-locked.\n"
            f"WHY: run '{run_id}' is at phase {phase} (pipeline '{pipeline_name}'). Production-code "
            "writes are permitted only in phases declared `allows_code_write` (e.g. IMPLEMENTED); "
            "the current phase must produce its own evidence first.\n"
            f"RECOVER: 1) see the whole journey + the single next action: "
            f"`e2e-dev-harness status --state {run_state_path}`; "
            f"2) finish this phase's expected_outputs and record them: "
            f"`e2e-dev-harness submit --state {run_state_path} --phase {phase} --key <k> --path <p>`; "
            f"3) advance with `e2e-dev-harness next --state {run_state_path}` (and `gate` to clear the "
            "exit gate) until a code-write phase is active, then retry this edit. "
            f"If {names} is NOT production code, write it under an allowed path (docs/, test evidence)."
        )
    # Opaque write (patch / git apply / inline `python -c` write): the target can't
    # be resolved from the command line, so deny conservatively outside code-write
    # phases rather than wave a potential code mutation through (G1).
    return _deny(
        f"Blocked: write-style shell command is phase-locked at phase {phase}.\n"
        f"WHY: run '{run_id}' is at phase {phase} (pipeline '{pipeline_name}'), which does not allow "
        "production-code writes. This command (patch / git apply / inline `python -c` write) can "
        "mutate files but its target can't be verified from the command line, so it is denied "
        "conservatively rather than waved through.\n"
        f"RECOVER: 1) see the journey + the single next action: "
        f"`e2e-dev-harness status --state {run_state_path}`; "
        f"2) finish this phase's expected_outputs and `submit` them, then advance with "
        f"`e2e-dev-harness next --state {run_state_path}` (and `gate`) until a code-write phase "
        "(e.g. IMPLEMENTED) is active, then retry. If this does not write production code, run it "
        "from an allowed path (docs/, test evidence) or use the Write tool for non-code files."
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
