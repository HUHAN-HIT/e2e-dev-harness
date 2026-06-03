"""Lease, heartbeat, and stale-claim reclaim behavior for agent_scheduler."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import agent_scheduler as sched

T0 = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)


def write_schedule(repo: Path, task: dict) -> Path:
    path = repo / "agent-schedule.json"
    path.write_text(
        json.dumps(
            {"schema": "e2e-dev-harness.agent-schedule.v1", "tasks": [task]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def base_task() -> dict:
    return {"id": "t1", "service": "services/orders", "phase": "implement", "status": "planned"}


def load_task(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["tasks"][0]


def test_claim_records_lease_and_heartbeat(tmp_path):
    path = write_schedule(tmp_path, base_task())
    result = sched.claim(tmp_path, path, "t1", "dev-a", lease_seconds=900, now=T0)
    assert result["ready"], result["blocked_reasons"]
    task = load_task(path)
    assert task["owner"] == "dev-a"
    assert task["status"] == "claimed"
    assert task["lease_seconds"] == 900
    assert task["heartbeat_at"] == "2026-05-30T12:00:00Z"
    assert task["claimed_at"] == "2026-05-30T12:00:00Z"


def test_active_claim_blocks_other_agent(tmp_path):
    path = write_schedule(tmp_path, base_task())
    sched.claim(tmp_path, path, "t1", "dev-a", lease_seconds=900, now=T0)
    later = T0 + timedelta(seconds=60)  # well within lease
    result = sched.claim(tmp_path, path, "t1", "dev-b", lease_seconds=900, now=later)
    assert not result["ready"]
    assert any("dev-a" in reason for reason in result["blocked_reasons"])


def test_claim_takes_over_stale_claim(tmp_path):
    path = write_schedule(tmp_path, base_task())
    sched.claim(tmp_path, path, "t1", "dev-a", lease_seconds=300, now=T0)
    expired = T0 + timedelta(seconds=400)  # past the 300s lease
    result = sched.claim(tmp_path, path, "t1", "dev-b", lease_seconds=300, now=expired)
    assert result["ready"], result["blocked_reasons"]
    task = load_task(path)
    assert task["owner"] == "dev-b"
    assert task.get("previous_owner") == "dev-a"


def test_renew_updates_heartbeat_for_owner(tmp_path):
    path = write_schedule(tmp_path, base_task())
    sched.claim(tmp_path, path, "t1", "dev-a", lease_seconds=300, now=T0)
    later = T0 + timedelta(seconds=120)
    result = sched.renew(tmp_path, path, "t1", "dev-a", now=later)
    assert result["ready"], result["blocked_reasons"]
    assert load_task(path)["heartbeat_at"] == "2026-05-30T12:02:00Z"


def test_renew_rejects_non_owner(tmp_path):
    path = write_schedule(tmp_path, base_task())
    sched.claim(tmp_path, path, "t1", "dev-a", lease_seconds=300, now=T0)
    result = sched.renew(tmp_path, path, "t1", "dev-b", now=T0 + timedelta(seconds=10))
    assert not result["ready"]


def test_reclaim_requires_force_on_active_claim(tmp_path):
    path = write_schedule(tmp_path, base_task())
    sched.claim(tmp_path, path, "t1", "dev-a", lease_seconds=900, now=T0)
    fresh = T0 + timedelta(seconds=30)
    blocked = sched.reclaim(tmp_path, path, "t1", "dev-b", force=False, now=fresh)
    assert not blocked["ready"]
    forced = sched.reclaim(tmp_path, path, "t1", "dev-b", force=True, now=fresh)
    assert forced["ready"], forced["blocked_reasons"]
    assert load_task(path)["owner"] == "dev-b"


def test_reclaim_allowed_when_stale_without_force(tmp_path):
    path = write_schedule(tmp_path, base_task())
    sched.claim(tmp_path, path, "t1", "dev-a", lease_seconds=120, now=T0)
    expired = T0 + timedelta(seconds=200)
    result = sched.reclaim(tmp_path, path, "t1", "dev-b", force=False, now=expired)
    assert result["ready"], result["blocked_reasons"]
    assert load_task(path)["owner"] == "dev-b"


def test_validate_flags_stale_claim(tmp_path):
    path = write_schedule(tmp_path, base_task())
    sched.claim(tmp_path, path, "t1", "dev-a", lease_seconds=120, now=T0)
    schedule = json.loads(path.read_text(encoding="utf-8"))
    expired = T0 + timedelta(seconds=500)
    # default: stale claim is a warning
    warn = sched.validate_schedule(schedule, ["services/orders"], now=expired)
    assert warn["ready"]
    assert any("stale" in w.lower() for w in warn["warnings"])
    # under require_claims: stale claim is a blocker
    strict = sched.validate_schedule(
        schedule, ["services/orders"], require_claims=True, now=expired
    )
    assert not strict["ready"]
    assert any("stale" in r.lower() for r in strict["blocked_reasons"])


def test_validate_fresh_claim_passes_require_claims(tmp_path):
    path = write_schedule(tmp_path, base_task())
    sched.claim(tmp_path, path, "t1", "dev-a", lease_seconds=900, now=T0)
    schedule = json.loads(path.read_text(encoding="utf-8"))
    fresh = T0 + timedelta(seconds=60)
    result = sched.validate_schedule(
        schedule, ["services/orders"], require_claims=True, now=fresh
    )
    assert result["ready"], result["blocked_reasons"]


def test_stale_uses_claimed_at_when_no_heartbeat(tmp_path):
    # backward compat: legacy schedules have claimed_at but no heartbeat_at/lease_seconds
    task = base_task()
    task.update({"status": "claimed", "owner": "dev-a", "claimed_at": "2026-05-30T12:00:00Z"})
    path = write_schedule(tmp_path, task)
    schedule = json.loads(path.read_text(encoding="utf-8"))
    expired = T0 + timedelta(seconds=sched.DEFAULT_LEASE_SECONDS + 60)
    result = sched.validate_schedule(schedule, ["services/orders"], require_claims=True, now=expired)
    assert not result["ready"]
