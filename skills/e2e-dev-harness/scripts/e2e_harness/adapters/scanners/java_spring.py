"""Java/Spring scanner adapter facade."""

from __future__ import annotations

from pathlib import Path

import cross_service_dependency_scan


def discover_scope(repo: Path, request: dict | None = None) -> dict:
    if request and request.get("run_dependency_scan"):
        return cross_service_dependency_scan.scan(repo, write_reports=bool(request.get("write_reports", False)))
    return {
        "schema": "e2e-dev-harness.scanner-scope.v1",
        "ready": True,
        "scanner": "java-spring",
        "repo": str(repo),
        "request": request or {},
        "services": [],
        "dependencies": [],
        "warnings": [],
    }

