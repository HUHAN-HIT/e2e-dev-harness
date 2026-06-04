"""Generic scanner adapter contract."""

from __future__ import annotations

from pathlib import Path


def discover_scope(repo: Path, request: dict | None = None) -> dict:
    return {
        "schema": "e2e-dev-harness.scanner-scope.v1",
        "ready": True,
        "scanner": "generic",
        "repo": str(repo),
        "request": request or {},
        "services": [],
        "dependencies": [],
        "warnings": [],
    }

