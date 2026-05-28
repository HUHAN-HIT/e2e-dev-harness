#!/usr/bin/env python3
"""Record phase timing, decisions, and optional token usage for harness runs."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "e2e-dev-harness.execution-trace.v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(tmp_name).unlink(missing_ok=True)
        raise


def repo_path(repo: Path, path: Path) -> Path:
    root = repo.resolve()
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"Execution trace path resolves outside repository: {path}") from error
    return resolved


def empty_trace() -> dict:
    return {"schema": SCHEMA, "events": [], "summary": {}}


def read_trace(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return empty_trace(), ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return empty_trace(), f"Execution trace is invalid JSON and was not modified: {path}: {error}"
    except (OSError, UnicodeDecodeError) as error:
        return empty_trace(), f"Execution trace could not be read and was not modified: {path}: {error}"
    if not isinstance(data, dict):
        return empty_trace(), f"Execution trace root must be a JSON object and was not modified: {path}"
    data.setdefault("schema", SCHEMA)
    data.setdefault("events", [])
    data.setdefault("summary", {})
    return data, ""


def load_trace(path: Path) -> dict:
    trace, _error = read_trace(path)
    return trace


def summarize(events: list[dict]) -> dict:
    elapsed_by_phase: dict[str, int] = {}
    status_by_phase: dict[str, str] = {}
    token_input = 0
    token_output = 0
    for event in events:
        phase = str(event.get("phase") or "unknown")
        elapsed = event.get("elapsed_ms")
        if isinstance(elapsed, int):
            elapsed_by_phase[phase] = elapsed_by_phase.get(phase, 0) + elapsed
        status = str(event.get("status") or "")
        if status:
            status_by_phase[phase] = status
        tokens = event.get("tokens") if isinstance(event.get("tokens"), dict) else {}
        if isinstance(tokens.get("input"), int):
            token_input += tokens["input"]
        if isinstance(tokens.get("output"), int):
            token_output += tokens["output"]
    return {
        "event_count": len(events),
        "elapsed_ms_total": sum(elapsed_by_phase.values()),
        "elapsed_ms_by_phase": elapsed_by_phase,
        "status_by_phase": status_by_phase,
        "tokens": {
            "input": token_input,
            "output": token_output,
            "total": token_input + token_output,
        },
    }


def append_event(
    repo: Path,
    trace_path: Path,
    phase: str,
    event: str,
    status: str = "",
    elapsed_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    agent: str = "",
    decision: str = "",
    artifacts: list[str] | None = None,
) -> dict:
    target = repo_path(repo, trace_path)
    trace, error = read_trace(target)
    if error:
        return {"ready": False, "blocked_reasons": [error], "warnings": [], "trace": str(target), "summary": {}}
    if trace.get("schema") != SCHEMA:
        return {
            "ready": False,
            "blocked_reasons": [f"Execution trace schema must be {SCHEMA}; existing trace was not modified: {target}"],
            "warnings": [],
            "trace": str(target),
            "summary": trace.get("summary", {}),
        }
    if not isinstance(trace.get("events"), list):
        return {
            "ready": False,
            "blocked_reasons": [f"Execution trace events must be a list; existing trace was not modified: {target}"],
            "warnings": [],
            "trace": str(target),
            "summary": trace.get("summary", {}),
        }
    entry = {
        "timestamp": now_iso(),
        "phase": phase,
        "event": event,
        "status": status,
    }
    if elapsed_ms is not None:
        entry["elapsed_ms"] = elapsed_ms
    if input_tokens is not None or output_tokens is not None:
        entry["tokens"] = {"input": input_tokens or 0, "output": output_tokens or 0}
    if agent:
        entry["agent"] = agent
    if decision:
        entry["decision"] = decision
    if artifacts:
        entry["artifacts"] = artifacts
    trace["events"].append(entry)
    trace["summary"] = summarize(trace["events"])
    atomic_write_text(target, json.dumps(trace, indent=2, ensure_ascii=False) + "\n")
    return {"ready": True, "trace": str(target), "event": entry, "summary": trace["summary"]}


def validate_trace(repo: Path, trace_path: Path, required_phases: list[str] | None = None) -> dict:
    target = repo_path(repo, trace_path)
    blocked: list[str] = []
    warnings: list[str] = []
    trace, error = read_trace(target)
    if not target.exists():
        blocked.append(f"Execution trace not found: {target}")
    if error:
        blocked.append(error)
    if trace.get("schema") != SCHEMA:
        blocked.append(f"Execution trace schema must be {SCHEMA}.")
    events = trace.get("events", [])
    if not isinstance(events, list) or not events:
        blocked.append("Execution trace must include at least one event.")
        events = []
    phases = {str(event.get("phase") or "") for event in events if isinstance(event, dict)}
    for phase in required_phases or []:
        if phase not in phases:
            blocked.append(f"Execution trace missing required phase: {phase}")
    if trace.get("summary", {}).get("elapsed_ms_total", 0) == 0:
        warnings.append("Execution trace has no elapsed timing data.")
    return {
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "trace": str(target),
        "summary": trace.get("summary", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--phase")
    parser.add_argument("--event", default="finish")
    parser.add_argument("--status", default="")
    parser.add_argument("--elapsed-ms", type=int)
    parser.add_argument("--input-tokens", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument("--agent", default="")
    parser.add_argument("--decision", default="")
    parser.add_argument("--artifact", action="append")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--required-phase", action="append")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if args.validate:
            result = validate_trace(args.repo, args.trace, args.required_phase)
        else:
            if not args.phase:
                raise ValueError("--phase is required unless --validate is used.")
            result = append_event(
                args.repo,
                args.trace,
                args.phase,
                args.event,
                args.status,
                args.elapsed_ms,
                args.input_tokens,
                args.output_tokens,
                args.agent,
                args.decision,
                args.artifact,
            )
    except ValueError as error:
        result = {"ready": False, "blocked_reasons": [str(error)], "warnings": []}
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Execution trace: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result.get("blocked_reasons", []):
            print(f"- {reason}")
        for warning in result.get("warnings", []):
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
