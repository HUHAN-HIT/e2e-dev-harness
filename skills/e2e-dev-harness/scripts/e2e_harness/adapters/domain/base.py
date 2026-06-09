"""DomainAdapter Protocol + pure spec-merge helper (domain layer, not core)."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Protocol, runtime_checkable

_OVERRIDE_FIELDS = ("worker_role", "worker_skill", "produces", "exit_gate")


@runtime_checkable
class DomainAdapter(Protocol):
    name: str
    test_runner: str
    review_profile: str

    def detect(self, repo: Path) -> bool: ...
    def scan(self, repo: Path, request: str) -> dict | None: ...
    def pipeline_overrides(self) -> dict: ...


def merge_overrides(spec: dict, overrides: dict) -> dict:
    """Return a copy of `spec` with per-phase `overrides` applied. Bare-string
    phase entries are promoted to `{phase, ...}` mappings. Identity when empty."""
    if not overrides:
        return spec
    out = copy.deepcopy(spec)
    new_phases = []
    for entry in out["phases"]:
        name = entry if isinstance(entry, str) else entry["phase"]
        ov = overrides.get(name)
        if not ov:
            new_phases.append(entry)
            continue
        merged = {"phase": name} if isinstance(entry, str) else dict(entry)
        for k in _OVERRIDE_FIELDS:
            if k in ov:
                merged[k] = ov[k]
        new_phases.append(merged)
    out["phases"] = new_phases
    return out


def domain_block(adapter: "DomainAdapter") -> dict:
    return {"name": adapter.name, "test_runner": adapter.test_runner,
            "review_profile": adapter.review_profile}
