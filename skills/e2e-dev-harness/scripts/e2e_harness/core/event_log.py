"""Tamper-evident append-only event log (UNWIRED seam, Phase 4).

Each event is canonically serialized (sorted keys, no whitespace) and chained:
`event_hash = sha256(canonical(event without event_hash))`, and every event
carries the previous event's `event_hash` plus a monotonic `sequence`. This makes
the log tamper-evident against any tamper that breaks the forward chain:
`verify_chain` re-derives both per event and detects modification (hash mismatch),
reordering, and INTERIOR deletion (a survivor's prev_event_hash/sequence stops
lining up).

TAIL ANCHOR (F-3) — the forward chain alone is self-anchored and so blind to TAIL
tampering: dropping the trailing event(s) (truncation), or editing the LAST event
and recomputing its hash, both leave a self-consistent prefix. `append_event`
therefore also persists an external head/length anchor next to the log
(`<path>.head` = `{"length": N, "tip": <last event_hash>}`). `verify_chain`
consults it (or an explicit `expected_len`/`expected_tip` passed by a caller
holding a TRULY external commitment) and reports `event-chain-truncated:<len>` on
a length mismatch and `event-chain-tip-mismatch:<tip>` on a last-event re-hash.

RESIDUAL — an attacker who rewrites BOTH the log and the co-located `.head`
sidecar (e.g. truncate-then-append via `append_event`, which rewrites the anchor)
still produces a self-consistent pair. That last residual is closed by
`state_store.detect_drift`, which replays the events and compares them to the
INDEPENDENTLY-maintained `run-state.json` projection (design Phase 4: "detect
first projection mismatch"). The honest layering: forward chain + `.head` anchor
detect log-only tail tampering; drift detection is the cross-witness for a
co-tampered anchor.

This module is deliberately NOT wired into `run_state.mutate` by default; events
are the authoritative source and `run-state.json` is the *output* of replay
(`state_store.replay_events`). `mutate` gained an opt-in `events_path` seam, but
no caller passes it yet — turning emission on is sequenced after this drift guard.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA = "e2e-dev-harness.event.v1"
ANCHOR_SCHEMA = "e2e-dev-harness.event-anchor.v1"


def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_event(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _anchor_path(path: str | Path) -> Path:
    return Path(str(path) + ".head")


def read_anchor(path: str | Path) -> dict | None:
    """The persisted external head/length anchor for `path`, or None if absent."""
    ap = _anchor_path(path)
    if not ap.exists():
        return None
    try:
        return json.loads(ap.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_anchor(path: str | Path, length: int, tip: str | None) -> None:
    _anchor_path(path).write_text(
        _canonical({"schema": ANCHOR_SCHEMA, "length": length, "tip": tip}),
        encoding="utf-8",
    )


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
    # Persist the external head/length anchor so verify_chain can detect tail
    # truncation / last-event re-hash that the self-anchored forward chain cannot.
    _write_anchor(p, event["sequence"], event["event_hash"])
    return event


def verify_chain(path: str | Path, *, expected_len: int | None = None,
                 expected_tip: str | None = None) -> tuple[bool, str | None]:
    """Re-derive each event's hash and chain link in file order, then check the
    external head/length anchor.

    Forward-chain failures take precedence and short-circuit:
    (False, "event-hash-mismatch:<seq>") for modification of a non-tail event;
    (False, "event-chain-broken:<seq>") for reordering or INTERIOR deletion.

    When the forward chain is clean, the anchor closes the TAIL gap. The anchor is
    `expected_len`/`expected_tip` when a caller supplies them (a truly external
    commitment), otherwise the persisted `<path>.head` sidecar from `append_event`.
    A length mismatch -> (False, "event-chain-truncated:<expected_len>"); a tip
    mismatch (e.g. the last event was re-hashed) ->
    (False, "event-chain-tip-mismatch:<expected_tip>"). (True, None) only when the
    chain is internally consistent AND matches the anchor.

    With NO explicit anchor and NO persisted sidecar this degrades to the legacy
    self-anchored check, which still cannot see tail tampering — but every log
    written by `append_event` now carries a sidecar, so that path is the exception.
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
    # Resolve the anchor: explicit args win; else fall back to the persisted sidecar.
    if expected_len is None and expected_tip is None:
        anchor = read_anchor(path)
        if anchor is not None:
            expected_len = anchor.get("length")
            expected_tip = anchor.get("tip")
    if expected_len is not None and len(events) != expected_len:
        return False, f"event-chain-truncated:{expected_len}"
    if expected_tip is not None and prev_hash != expected_tip:
        return False, f"event-chain-tip-mismatch:{expected_tip}"
    return True, None
