#!/usr/bin/env python3
"""Create and validate run-state checkpoints for resumed agent sessions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_state  # noqa: E402
import coordinator_summary  # noqa: E402
from common import atomic_write_json, now_iso  # noqa: E402

SCHEMA = "e2e-dev-harness.session-checkpoint.v1"
FILENAME = "session-checkpoint.json"


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def state_fingerprint(state: dict) -> str:
    payload = {
        "run_id": state.get("run_id", ""),
        "lifecycle": state.get("lifecycle", ""),
        "selected_mode": state.get("selected_mode", ""),
        "services": state.get("services", []),
        "gates": state.get("gates", {}),
        "owners": state.get("owners", {}),
        "updated_at": state.get("updated_at", ""),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def checkpoint_path(state_path: Path) -> Path:
    return state_path.parent / FILENAME


def create(
    repo: Path,
    state_path: Path,
    next_action: dict | None = None,
    agent: str = "",
    role: str = "",
) -> dict:
    repo = repo.resolve()
    resolved_state = resolve(repo, state_path)
    state = load_json(resolved_state)
    if not state:
        return {
            "ready": False,
            "blocked_reasons": [f"Run state not found or invalid: {resolved_state}"],
            "warnings": [],
            "checkpoint": str(checkpoint_path(resolved_state)),
        }
    data = {
        "schema": SCHEMA,
        "run_id": state.get("run_id", ""),
        "lifecycle": state.get("lifecycle", ""),
        "state_updated_at": state.get("updated_at", ""),
        "state_fingerprint": state_fingerprint(state),
        "next": next_action or {},
        "agent": agent,
        "role": role,
        "created_at": now_iso(),
        "instruction": "Resume from this checkpoint and perform only the next phase allowed by run-state.",
    }
    target = checkpoint_path(resolved_state)
    atomic_write_json(target, data)
    return {
        "ready": True,
        "blocked_reasons": [],
        "warnings": [],
        "checkpoint": str(target),
        "lifecycle": data["lifecycle"],
        "next": data["next"],
    }


def create_coordinator_summary(
    repo: Path,
    state_path: Path,
    result: dict,
    full_result_path: str = "",
) -> dict:
    repo = repo.resolve()
    resolved_state = resolve(repo, state_path)
    state = load_json(resolved_state)
    return coordinator_summary.write(repo, resolved_state, state, result, full_result_path)


def parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate(repo: Path, state_path: Path, max_age_minutes: int = 30) -> dict:
    repo = repo.resolve()
    resolved_state = resolve(repo, state_path)
    state = load_json(resolved_state)
    target = checkpoint_path(resolved_state)
    data = load_json(target)
    blocked: list[str] = []
    warnings: list[str] = []
    if not state:
        blocked.append(f"Run state not found or invalid: {resolved_state}")
    if not data:
        blocked.append(f"Session checkpoint missing or invalid: {target}")
    elif data.get("schema") != SCHEMA:
        blocked.append(f"Session checkpoint schema must be {SCHEMA}.")
    if state and data:
        if data.get("run_id") != state.get("run_id"):
            blocked.append("Session checkpoint run_id does not match run-state.")
        if data.get("lifecycle") != state.get("lifecycle"):
            blocked.append("Session checkpoint lifecycle is stale; run e2e_dev_harness.py next or resume.")
        if data.get("state_fingerprint") != state_fingerprint(state):
            blocked.append("Session checkpoint fingerprint is stale; run e2e_dev_harness.py next or resume.")
        created = parse_time(str(data.get("created_at", "")))
        if not created:
            blocked.append("Session checkpoint created_at is missing or invalid.")
        elif max_age_minutes > 0 and (now_dt() - created).total_seconds() > max_age_minutes * 60:
            blocked.append(
                f"Session checkpoint is older than {max_age_minutes} minutes; rerun e2e_dev_harness.py next or resume."
            )
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "run_state": str(resolved_state),
        "checkpoint": str(target),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--agent", default="")
    parser.add_argument("--role", default="")
    parser.add_argument("--max-age-minutes", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = create(args.repo, args.state, agent=args.agent, role=args.role) if args.create else validate(
        args.repo,
        args.state,
        args.max_age_minutes,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Session checkpoint: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
