"""Pipeline config: declarative pipelines loaded from `pipelines/*.yaml`.

Hybrid schema — each `phases` entry is either a bare catalog phase name
(inherits `lifecycle._CATALOG` defaults) or a mapping `{phase, ...overrides}`.
Public API (`build_spine`, `active_phase_names`) is preserved; built-in tier
names resolve to shipped yaml with no special privilege.
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import yaml

from e2e_harness.core import lifecycle, module_plan, multitrack
from e2e_harness.core.lifecycle import Phase

_PIPELINES_DIR = Path(__file__).resolve().parents[2] / "pipelines"
_OVERRIDE_FIELDS = ("worker_role", "worker_skill", "produces", "exit_gate", "allows_code_write")


def is_path(name_or_path: str) -> bool:
    """A custom pipeline reference is a path (vs a built-in name)."""
    return name_or_path.endswith((".yaml", ".yml")) or os.sep in name_or_path or "/" in name_or_path


def load_spec(name_or_path: str) -> dict:
    """Resolve a built-in name to `pipelines/<name>.yaml`, or read a file path."""
    if is_path(name_or_path):
        p = Path(name_or_path)
        if not p.is_file():
            raise FileNotFoundError(f"pipeline file not found: {name_or_path}")
    else:
        p = _PIPELINES_DIR / f"{name_or_path}.yaml"
        if not p.is_file():
            raise KeyError(f"unknown pipeline: {name_or_path}")
    spec = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError(f"pipeline spec must be a mapping: {name_or_path}")
    return spec


def _entry_name_and_overrides(entry) -> tuple[str, dict]:
    if isinstance(entry, str):
        return entry, {}
    if not isinstance(entry, dict) or "phase" not in entry:
        raise ValueError(f"invalid phase entry: {entry!r}")
    overrides = {}
    for k in _OVERRIDE_FIELDS:
        if k in entry:
            overrides[k] = tuple(entry[k]) if k in ("produces", "exit_gate") else entry[k]
    return entry["phase"], overrides


def spec_to_spine(spec: dict) -> list[Phase]:
    catalog = lifecycle.catalog()
    parsed = [_entry_name_and_overrides(e) for e in spec["phases"]]
    names = [n for n, _ in parsed]
    spine: list[Phase] = []
    for i, (name, overrides) in enumerate(parsed):
        nxt = names[i + 1] if i + 1 < len(names) else None
        if name in catalog:
            spine.append(replace(catalog[name], next_phase=nxt, **overrides))
        else:  # non-catalog phase: must be fully specified (validation enforces)
            spine.append(Phase(
                name=name,
                worker_role=overrides["worker_role"],
                worker_skill=overrides["worker_skill"],
                produces=overrides["produces"],
                exit_gate=overrides["exit_gate"],
                next_phase=nxt,
                allows_code_write=overrides.get("allows_code_write", False),
            ))
    return spine


def active_phase_names(pipeline: str) -> list[str]:
    return [n for n, _ in (_entry_name_and_overrides(e) for e in load_spec(pipeline)["phases"])]


def build_spine(pipeline: str) -> list[Phase]:
    return spec_to_spine(load_spec(pipeline))


def _base_spine(state: dict) -> list[Phase]:
    spec = state.get("pipeline_spec")
    if spec:
        return spec_to_spine(spec)
    return build_spine(state.get("pipeline", "minimal"))


def _module_plan_from_state(state: dict, repo_root) -> dict | None:
    """Parsed+valid module plan from PLANNED evidence, else None (needs repo_root
    to resolve the artifact path; missing/invalid plan -> single track)."""
    if repo_root is None:
        return None
    entry = (state.get("phases", {}).get("PLANNED", {})
             .get("evidence", {}).get("module_plan"))
    if not entry:
        return None
    rel = entry["path"] if isinstance(entry, dict) else entry
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel
    try:
        obj = json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok, _ = module_plan.validate_module_plan(obj)
    return obj if ok else None


def spine_for_state(state: dict, repo_root=None) -> list[Phase]:
    """Single seam for the CLI: embedded spec (hermetic custom run) else named
    built-in; expanded into per-module tracks (B2) when PLANNED carries a valid
    module plan with >=2 modules and repo_root is given to resolve it."""
    base = _base_spine(state)
    mplan = _module_plan_from_state(state, repo_root)
    if mplan is not None:
        return multitrack.expand(base, mplan)
    return base


def can_write_code(state: dict) -> bool:
    """True iff state['current_phase'] resolves to a spine phase declaring allows_code_write.

    Single source of phase code-write authority — reused by the PreToolUse hook
    and any CLI that needs the same answer. Multi-track phases (`IMPLEMENTED#auth`)
    inherit their base phase's authority. Conservative: unknown / missing → False.
    """
    current = state.get("current_phase")
    if not current:
        return False
    base_name = multitrack.base_phase_name(current)
    for phase in _base_spine(state):
        if phase.name == base_name:
            return bool(phase.allows_code_write)
    return False
