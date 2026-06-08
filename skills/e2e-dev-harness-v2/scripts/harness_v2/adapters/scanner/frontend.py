"""Thin frontend scope discovery (heuristic file-walk; no framework AST)."""
from __future__ import annotations

from pathlib import Path

_EXT = (".tsx", ".jsx", ".vue", ".svelte")


def scan_frontend(repo) -> dict:
    repo = Path(repo)
    src = repo / "src"
    comps = []
    if src.is_dir():
        for f in sorted(src.rglob("*")):
            if f.suffix in _EXT and f.is_file():
                comps.append(str(f.relative_to(repo)))
    return {"schema": "scanner-scope.v1", "services": comps[:1],
            "components": comps, "dependencies": []}
