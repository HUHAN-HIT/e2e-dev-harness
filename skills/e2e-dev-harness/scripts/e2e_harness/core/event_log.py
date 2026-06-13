"""Tamper-evident append-only event log (UNWIRED seam, Phase 4).

Each event is canonically serialized (sorted keys, no whitespace) and chained:
`event_hash = sha256(canonical(event without event_hash))`, and every event
carries the previous event's `event_hash` plus a monotonic `sequence`. This makes
the log tamper-evident against any tamper that breaks the forward chain:
`verify_chain` re-derives both per event and detects modification (hash mismatch),
reordering, and INTERIOR deletion (a survivor's prev_event_hash/sequence stops
lining up).

KNOWN LIMITATION — the chain is self-anchored, with no external head/length
commitment, so it canNOT detect TAIL tampering: dropping the trailing event(s)
(truncation), or editing the LAST event and recomputing its hash, both leave a
self-consistent prefix that verifies clean. Likewise, an attacker who truncates
and then appends via `append_event` produces a valid forged continuation.
Closing the tail gap needs the deferred projection-drift cross-check (replay vs a
durable run-state/length anchor — design Phase 4); it is out of scope for this
unwired seam.

This module is deliberately NOT wired into `run_state.mutate`; events are the
authoritative source and `run-state.json` is the *output* of replay
(`state_store.replay_events`), a separate projection task sequenced later.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA = "e2e-dev-harness.event.v1"


def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_event(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def read_events(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def append_event(path: str | Path, payload: dict) -> dict:
    p = Path(path)
    events = read_events(p)
    prev = events[-1]["event_hash"] if events else None
    event = dict(payload)
    event["schema"] = SCHEMA
    event["sequence"] = len(events) + 1
    event["prev_event_hash"] = prev
    event["event_hash"] = _hash_event({k: v for k, v in event.items() if k != "event_hash"})
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(_canonical(event) + "\n")
    return event


def verify_chain(path: str | Path) -> tuple[bool, str | None]:
    """Re-derive each event's hash and chain link in file order.

    Returns (False, "event-hash-mismatch:<seq>") if any event's content no longer
    matches its stored `event_hash` (modification of a non-tail event), and
    (False, "event-chain-broken:<seq>") if `prev_event_hash`/`sequence` do not
    line up with file order (reordering or INTERIOR deletion). (True, None) when
    the on-disk chain is internally consistent.

    NOTE: "intact" here means "no detectable forward-chain break" — it does NOT
    rule out TAIL truncation or last-event re-hash, which this self-anchored chain
    cannot see (see module docstring). Callers must not read (True, None) as proof
    that no events were dropped from the end.
    """
    events = read_events(path)
    prev_hash: str | None = None
    for i, event in enumerate(events):
        seq = i + 1
        stored = event.get("event_hash")
        recomputed = _hash_event({k: v for k, v in event.items() if k != "event_hash"})
        if recomputed != stored:
            return False, f"event-hash-mismatch:{seq}"
        if event.get("prev_event_hash") != prev_hash or event.get("sequence") != seq:
            return False, f"event-chain-broken:{seq}"
        prev_hash = stored
    return True, None
