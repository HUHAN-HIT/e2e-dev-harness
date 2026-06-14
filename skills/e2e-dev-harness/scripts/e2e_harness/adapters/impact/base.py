"""Narrow impact-provider interface (design: Components).

The lifecycle depends on this Protocol, not on GitNexus-specific details, so future
providers can be added without changing the control plane. Index status, refresh,
seed resolution and assessment are separate methods because they fail and degrade
differently.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ImpactProvider(Protocol):
    name: str

    def inspect_index(self, repo: Path) -> dict: ...
    def refresh_index(self, repo: Path) -> dict: ...
    def resolve_seeds(self, repo: Path, request: dict) -> dict: ...
    def assess(self, repo: Path, request: dict) -> dict: ...
