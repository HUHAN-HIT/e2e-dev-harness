"""Frontend domain adapter — detects a JS/TS UI repo (package.json + framework
or a vite/vitest config) and routes scope discovery to the frontend scanner."""
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.adapters import scanner

_FW = ("react", "vue", "svelte", "@angular/core")


class FrontendAdapter:
    name = "frontend"
    test_runner = "vitest"
    review_profile = "frontend-default"

    def __init__(self, repo: Path | None = None):
        self.repo = Path(repo) if repo else None

    @classmethod
    def detect(cls, repo: Path) -> bool:
        repo = Path(repo)
        pkg = repo / "package.json"
        if not pkg.exists():
            return False
        if (repo / "vite.config.ts").exists() or (repo / "vite.config.js").exists() \
           or (repo / "vitest.config.ts").exists() or (repo / "vitest.config.js").exists():
            return True
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except Exception:
            return False
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        return any(fw in deps for fw in _FW)

    def scan(self, repo, request) -> dict | None:
        return scanner.scan_frontend(repo)

    def pipeline_overrides(self) -> dict:
        return {}
