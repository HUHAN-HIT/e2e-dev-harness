"""SSOT run-state: one JSON file, versioned schema, atomic writes."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "e2e-dev-harness-v2.run-state.v1"


def _stamp(now: str | None = None) -> str:
    if now:
        return now
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def new_run_state(run_id: str, feature: str, request: str,
                  tier: str = "minimal", pipeline: str = "minimal",
                  now: str | None = None) -> dict:
    ts = _stamp(now)
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "feature": feature,
        "request": request,
        "tier": tier,
        "pipeline": pipeline,
        "current_phase": "CREATED",
        "phases": {},
        "created_at": ts,
        "updated_at": ts,
    }


def load(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    got = data.get("schema")
    if got != SCHEMA:
        raise ValueError(
            f"run-state schema mismatch: expected {SCHEMA!r}, got {got!r}"
        )
    return data


def save(path: str | Path, state: dict, now: str | None = None) -> None:
    state = dict(state)
    state["updated_at"] = _stamp(now)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, indent=2, ensure_ascii=False)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)
