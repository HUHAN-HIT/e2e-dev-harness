"""Validation for agent-team profile files."""
from __future__ import annotations

from pathlib import Path

import yaml

PROFILE_SCHEMA = "e2e-dev-harness.agent-team-profile.v1"


class ProfileValidationError(ValueError):
    """Raised when a profile file is malformed."""

    def __init__(self, path: Path, field: str, reason: str) -> None:
        self.path = Path(path)
        self.field = field
        self.reason = reason
        super().__init__(f"{self.path}: {field}: {reason}")


def _fail(path: Path, field: str, reason: str) -> None:
    raise ProfileValidationError(path, field, reason)


def _require_str(path: Path, obj: dict, field: str) -> None:
    if not isinstance(obj.get(field), str) or not obj[field].strip():
        _fail(path, field, "must be a non-empty string")


def _require_list(path: Path, obj: dict, field: str) -> None:
    if not isinstance(obj.get(field), list):
        _fail(path, field, "must be a list")


def validate_profile(profile: dict, path: str | Path = "<memory>") -> dict:
    source = Path(path)
    if not isinstance(profile, dict):
        _fail(source, "<root>", "must be a mapping")
    if profile.get("schema") != PROFILE_SCHEMA:
        _fail(source, "schema", f"must be {PROFILE_SCHEMA}")
    _require_str(source, profile, "name")
    roles = profile.get("roles")
    if not isinstance(roles, dict) or not roles:
        _fail(source, "roles", "must be a non-empty mapping")
    for role, spec in roles.items():
        prefix = f"roles.{role}"
        if not isinstance(spec, dict):
            _fail(source, prefix, "must be a mapping")
        _require_str(source, spec, f"{prefix}.skill" if "skill" not in spec else "skill")
        if "runtime_subagent_type" in spec and not isinstance(spec["runtime_subagent_type"], str):
            _fail(source, f"{prefix}.runtime_subagent_type", "must be a string")
        if "max_workers" in spec:
            value = spec["max_workers"]
            if not isinstance(value, int) or value < 1:
                _fail(source, f"{prefix}.max_workers", "must be a positive integer")
    phases = profile.get("phases", {}) or {}
    if not isinstance(phases, dict):
        _fail(source, "phases", "must be a mapping")
    for phase_name, phase in phases.items():
        prefix = f"phases.{phase_name}"
        if not isinstance(phase, dict):
            _fail(source, prefix, "must be a mapping")
        if "strategy" in phase and not isinstance(phase["strategy"], str):
            _fail(source, f"{prefix}.strategy", "must be a string")
        if "workers" in phase:
            _require_list(source, phase, "workers")
            for i, worker in enumerate(phase["workers"]):
                wp = f"{prefix}.workers.{i}"
                if not isinstance(worker, dict):
                    _fail(source, wp, "must be a mapping")
                _require_list(source, worker, "expected_outputs")
    return profile


def load_profile_file(path: str | Path) -> dict:
    source = Path(path)
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    return validate_profile(data, source)
