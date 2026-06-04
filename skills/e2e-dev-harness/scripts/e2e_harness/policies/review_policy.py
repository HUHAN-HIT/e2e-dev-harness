"""Review-policy facade over project review profile discovery."""

from __future__ import annotations

from pathlib import Path

import reviewer_gate


def default_profile(repo: Path | None = None) -> dict:
    profile, blocked, profile_path, source, chain = reviewer_gate.load_review_profile(repo or Path.cwd(), None)
    return {
        "schema": "e2e-dev-harness.review-policy.v1",
        "profile": profile,
        "blocked_reasons": blocked,
        "path": profile_path,
        "source": source,
        "chain": chain,
    }

