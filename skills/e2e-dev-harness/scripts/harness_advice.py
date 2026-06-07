#!/usr/bin/env python3
"""Pre-action harness guidance for SessionStart / UserPromptSubmit hooks.

``phase_guard.py`` runs on ``PreToolUse`` — it is *reactive*: it can only judge a
tool call the coordinator has already decided to make, so the next harness step
is discovered only *after* a write is blocked. That is why a coordinator tends to
try writing a worker-owned output (impact-summary.md, impact-analysis.json, a
design doc, an R1/R2/R3 report) first and bounce off the gate before spawning the
worker.

This advice hook runs *before* the coordinator acts. On SessionStart and on every
UserPromptSubmit it injects the current lifecycle and the single next action into
context, so the coordinator spawns/acknowledges the pending worker instead of
discovering it through a block.

It is advisory only:

* it never blocks — ``main`` always returns ``0`` and any failure degrades to
  silence;
* it stays silent when there is no active harness run, so non-harness sessions
  see no noise;
* it reuses ``phase_guard``'s guidance computation verbatim
  (``guidance_from_lock`` + ``compact_guidance_result``) so there is exactly one
  source of truth for "what is the next harness step".
"""

from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

import phase_guard


ADVICE_SCHEMA = "e2e-dev-harness.harness-advice.v1"
WORKER_OUTPUT_REMINDER = (
    "Reminder: worker-owned scheduled outputs (design docs, "
    "evidence/impact-summary.md, evidence/impact-analysis.json, R1/R2/R3 reports) "
    "must be written by the dispatched worker, not the coordinator. Spawn or "
    "acknowledge the worker first; do not write them directly."
)
CREATED_REQUIREMENTS_RELAY_REMINDER = (
    "CREATED clarification boundary: the coordinator only dispatches, acknowledges, "
    "and relays worker output; it must not write or repair the requirements handoff locally."
)


def _inactive() -> dict:
    return {"schema": ADVICE_SCHEMA, "active_run": False}


def advice_for_repo(repo: Path, lock_path: Path | None = None, run_dir: Path | None = None) -> dict:
    """Compute pre-action guidance for ``repo`` from the most recent harness run.

    Returns ``{"active_run": False}`` (silent) when there is no discoverable run
    or when guidance computation fails for any reason — an advisory hook must
    never raise into a session.
    """
    repo = repo.resolve()
    try:
        lock = phase_guard.discover_lock(repo, lock_path, run_dir)
        if not lock or not lock.exists():
            return _inactive()
        guidance = phase_guard.compact_guidance_result(phase_guard.guidance_from_lock(repo, lock))
    except Exception:
        return _inactive()
    lifecycle = str(guidance.get("lifecycle", "") or "")
    if not lifecycle or lifecycle == "<missing>":
        # An unreadable/empty lifecycle means there is nothing specific to say;
        # stay silent rather than inject a "<missing>" block. phase_guard still
        # blocks writes, so corrupt state is caught reactively without noise.
        return _inactive()
    pending = guidance.get("pending_dispatch")
    return {
        "schema": ADVICE_SCHEMA,
        "active_run": True,
        "lifecycle": lifecycle,
        "run_state": str(guidance.get("run_state", "") or ""),
        "next_single_action": str(guidance.get("next_single_action", "") or ""),
        "phase_guidance": str(guidance.get("phase_guidance", "") or ""),
        "pending_dispatch": pending if isinstance(pending, dict) else {},
    }


def format_advice(result: dict) -> str:
    """Render advice as a short context block, or ``""`` when there is no run."""
    if not result.get("active_run"):
        return ""
    lifecycle = result.get("lifecycle") or "<missing>"
    run_state = result.get("run_state") or "docs/agent-runs/<run>/run-state.json"
    lines = [f"[e2e-dev-harness] Active run - lifecycle: {lifecycle} | run-state: {run_state}"]
    phase_guidance = str(result.get("phase_guidance") or "").strip()
    if phase_guidance:
        lines.append(phase_guidance)
    next_action = str(result.get("next_single_action") or "").strip()
    if next_action:
        lines.append("Next single action: " + next_action)
    pending = result.get("pending_dispatch") if isinstance(result.get("pending_dispatch"), dict) else {}
    if pending:
        task_id = str(pending.get("task_id", "")).strip()
        agent = str(pending.get("agent", "")).strip()
        spawn_request = str(pending.get("spawn_request", "")).strip()
        ack_command = str(pending.get("ack_command", "")).strip()
        header = f"Pending dispatch {task_id}".rstrip()
        if agent:
            header += f" ({agent})"
        lines.append(header + " awaits a runtime worker spawn:")
        if spawn_request:
            lines.append("  - Spawn the dispatcher-generated Task from: " + spawn_request)
        if ack_command:
            lines.append("  - Then record: " + ack_command)
    if lifecycle == "CREATED":
        lines.append(CREATED_REQUIREMENTS_RELAY_REMINDER)
    lines.append(WORKER_OUTPUT_REMINDER)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--hook-input", help="JSON hook input, or '-' for stdin (drained, not required).")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    # Drain stdin when a runtime feeds it so the caller never sees a broken pipe.
    if args.hook_input == "-":
        try:
            sys.stdin.read()
        except Exception:
            pass

    result = advice_for_repo(args.repo, args.lock, args.run_dir)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        text = format_advice(result)
        if text:
            print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
