"""Event-store facade over the legacy event_log module."""

from __future__ import annotations

from event_log import (  # noqa: F401
    SCHEMA,
    append_command_event,
    append_event,
    events_dir,
    project_run_state_snapshot,
    project_schedule_snapshot,
    read_events,
    replay_dispatch_status,
    snapshot_mismatches,
    snapshots_dir,
    write_snapshot_projections,
)

