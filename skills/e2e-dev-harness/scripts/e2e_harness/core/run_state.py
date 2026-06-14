"""SSOT run-state: one JSON file, versioned schema, atomic writes."""
from __future__ import annotations

import contextlib
import copy
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "e2e-dev-harness.run-state.v1"
WITNESS_FAILURE_SCHEMA = "e2e-dev-harness.event-write-failure.v1"


def _stamp(now: str | None = None) -> str:
    if now:
        return now
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def new_run_state(run_id: str, feature: str, request: str,
                  tier: str = "minimal", pipeline: str = "minimal",
                  pipeline_spec: dict | None = None,
                  domain: dict | None = None,
                  now: str | None = None) -> dict:
    ts = _stamp(now)
    state = {
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
    if pipeline_spec is not None:
        state["pipeline_spec"] = pipeline_spec
    if domain is not None:
        state["domain"] = domain
    return state


def events_path_for(state_path: str | Path) -> Path:
    """The chained event log that sits next to a run's `run-state.json`:
    `<run_dir>/events.jsonl`. The ONE sibling-path convention shared by recovery,
    `start`, and the four forward commands (Slice 1) so every emitter targets the
    same file."""
    return Path(state_path).parent / "events.jsonl"


def write_failed_path_for(events_path: str | Path) -> Path:
    """The sentinel a degraded witness leaves next to its log when a post-`save`
    append fails: `<events_path>.write-failed`. `doctor --state` reads it to report
    a KNOWN write failure (a precise cause) ahead of ambiguous drift (Slice 1.5)."""
    return Path(str(events_path) + ".write-failed")


def events_path_if_active(state_path: str | Path) -> Path | None:
    """The forward-path emission switch (Slice 1): the run's events log IFF it
    already exists, else None. `start` decides a run's witness once (lay it down,
    or not); the four forward commands pass this to `mutate` so they extend an
    existing chain but never bootstrap one mid-run — an old/opted-out run stays
    event-free, with no partial chain for `detect_drift` to read as drift."""
    p = events_path_for(state_path)
    return p if p.exists() else None


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
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


_LOCK_TIMEOUT_S = 10.0
_LOCK_POLL_S = 0.02


@contextlib.contextmanager
def _lock(path):
    """Exclusive advisory lock via an O_EXCL sidecar file. Cross-platform,
    stdlib only. Serializes the load->mutate->save critical section so that
    concurrent writers (e.g. parallel r1/r2/r3 reviewers calling `submit`)
    cannot clobber each other's evidence."""
    lock = Path(str(path) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    fd = None
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except (FileExistsError, PermissionError):
            # FileExistsError: another holder owns the lock.
            # PermissionError (Windows, ERRNO 13): the lock file is in a
            # "delete pending" state because a releasing thread is mid-unlink.
            # Both mean "retry shortly", not a hard failure.
            if time.monotonic() >= deadline:
                raise TimeoutError(f"run-state lock busy: {lock}")
            time.sleep(_LOCK_POLL_S)
    try:
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(str(lock))


def mutate(path: str | Path, fn, now: str | None = None,
           events_path: str | Path | None = None) -> dict:
    """Concurrency-safe load -> fn(state) (mutated in place) -> save, under an
    exclusive lock. Returns the saved state. Every mutating verb must go through
    this so parallel workers cannot lose updates (last-os.replace-wins).

    `events_path` (F-2 wiring): when given, the same load->fn->save transition is
    ALSO projected onto the tamper-evident event log via
    `state_store.derive_events` + `event_log.append_event`, INSIDE the lock so the
    sidecar chain stays consistent with run-state.json under concurrency. Default
    None keeps the byte-compatible behavior (run-state.json remains the sole
    artifact — the compatibility-projection Non-Goal); no caller passes it yet,
    so this is a wired-but-inert seam. The state write is authoritative-in-
    practice today, so event derivation runs only AFTER `save` succeeds and never
    blocks or corrupts it. (`event_log`/`state_store` are imported locally to keep
    this core module's import graph minimal.)"""
    with _lock(path):
        state = load(path)
        before = copy.deepcopy(state) if events_path is not None else None
        fn(state)
        save(path, state, now=now)
        if events_path is not None:
            # Slice 1.5 (R4): `save` already committed and is authoritative-in-
            # practice, so the witness must never veto it. A post-save append
            # failure is recorded loudly (sentinel + stderr) and SWALLOWED so the
            # command reports the success that actually happened. The chain is now
            # one (or more) behind for the run's life — reported, not silent.
            from e2e_harness.core import event_log, state_store
            event = None
            try:
                for event in state_store.derive_events(before, state):
                    event_log.append_event(events_path, event)
            except Exception as exc:  # noqa: BLE001 — witness must not crash the authority
                _record_witness_failure(events_path, state, event, exc)
        return state


def _record_witness_failure(events_path, state: dict, event, exc: Exception) -> None:
    """R4 attribution: name the first failed append in a sibling
    `events.jsonl.write-failed` sentinel and warn on stderr, then return so
    `mutate` reports the committed success. Every step is best-effort — if even
    the sentinel write fails the warning still surfaces, and `detect_drift`
    independently catches the chain lag (the sentinel is attribution, not a
    correctness crutch). Chain healing is out of Phase 1 scope (it approaches
    Option C)."""
    reason = f"{type(exc).__name__}: {exc}"
    etype = event.get("type") if isinstance(event, dict) else None
    try:
        from e2e_harness.core import event_log
        seq = len(event_log.read_events(events_path)) + 1
    except Exception:  # noqa: BLE001 — diagnostic only; never re-raise from here
        seq = None
    sentinel = write_failed_path_for(events_path)
    try:
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text(json.dumps({
            "schema": WITNESS_FAILURE_SCHEMA,
            "run_id": state.get("run_id"),
            "expected_sequence": seq,
            "type": etype,
            "reason": reason,
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001 — sentinel is best-effort; warning still fires
        pass
    print(f"[e2e-dev-harness] WARNING: event witness append failed for "
          f"{events_path} ({reason}); run-state saved (authoritative), the event "
          f"chain is now behind — see {sentinel}", file=sys.stderr)
