"""Adapter selection: explicit name, else first detector to match (order =
specificity), else the backend default. Unknown explicit name -> KeyError."""
from __future__ import annotations

from pathlib import Path

from harness_v2.adapters.domain.frontend import FrontendAdapter
from harness_v2.adapters.domain.backend import BackendAdapter

_ORDER = [FrontendAdapter, BackendAdapter]   # frontend first (more specific)
_BY_NAME = {c.name: c for c in _ORDER}
_DEFAULT = BackendAdapter


def select(repo, explicit: str | None = None):
    repo = Path(repo)
    if explicit:
        if explicit not in _BY_NAME:
            raise KeyError(f"unknown adapter: {explicit}")
        return _BY_NAME[explicit](repo)
    for cls in _ORDER:
        if cls.detect(repo):
            return cls(repo)
    return _DEFAULT(repo)
