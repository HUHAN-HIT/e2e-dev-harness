"""Stop hook: keep going while a run is active and not VERIFIED.

Thin version of legacy harness_stop_guard — reads only run-state.current_phase.
Stdlib only. See design §3.3.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[3]  # .../scripts
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from e2e_harness.core import run_state                 # noqa: E402
from e2e_harness.adapters.hooks import paths as hook_paths  # noqa: E402

TERMINAL_PHASES = {"VERIFIED"}


def decide(run_state_path) -> dict:
    if run_state_path is None or not Path(run_state_path).is_file():
        return {"decision": "allow", "reason": ""}
    try:
        state = run_state.load(run_state_path)
    except (ValueError, OSError, json.JSONDecodeError):
        return {"decision": "allow", "reason": ""}
    phase = state.get("current_phase", "")
    if phase in TERMINAL_PHASES:
        return {"decision": "allow", "reason": ""}
    run_id = state.get("run_id", "")
    return {
        "decision": "block",
        "reason": (
            f"Do not stop yet: run '{run_id}' is at phase {phase}, not VERIFIED.\n"
            "WHY: the harness guarantees every run reaches VERIFIED; stopping now leaves the "
            "change unverified (tests / review / verification still incomplete).\n"
            f"CONTINUE: run `e2e-dev-harness next --state {run_state_path}` for the single next "
            "action; if it returns a blocker, `dispatch` the worker, `submit` its evidence, then "
            f"`gate`. Repeat until VERIFIED. Inspect progress: "
            f"`e2e-dev-harness status --state {run_state_path}`."
        ),
    }


def _emit(result: dict) -> None:
    if result["decision"] == "block":
        print(json.dumps({"decision": "block", "reason": result["reason"]}, ensure_ascii=False))
    else:
        print(json.dumps({}, ensure_ascii=False))


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--state", default=None)
    parser.add_argument("--hook-input", default="-", help="JSON hook input, or '-' for stdin.")
    args = parser.parse_args(argv)
    if args.hook_input == "-":
        try:
            sys.stdin.read()
        except (OSError, ValueError):
            pass
    repo = Path(args.repo)
    rsp = Path(args.state) if args.state else hook_paths.discover_run_state(repo)
    _emit(decide(rsp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
