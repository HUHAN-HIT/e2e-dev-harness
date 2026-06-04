"""GitHub Actions CI adapter contract."""

from __future__ import annotations


def summarize_checks(checks: list[dict] | None = None) -> dict:
    items = list(checks or [])
    failed = [item for item in items if str(item.get("status", item.get("conclusion", ""))).lower() in {"failure", "failed", "cancelled", "timed_out"}]
    return {
        "schema": "e2e-dev-harness.github-actions-summary.v1",
        "ready": not failed,
        "total": len(items),
        "failed": len(failed),
        "checks": items,
    }

