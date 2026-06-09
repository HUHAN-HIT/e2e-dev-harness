"""Pipeline spec validation: schema + I1 termination + I2 gate-closure.

Pure (no I/O). Built-in and custom specs alike must pass before they may run.
"""
from __future__ import annotations

from e2e_harness import pipeline
from e2e_harness.core import lifecycle, gates

_REQUIRED_FOR_CUSTOM = ("worker_role", "worker_skill", "produces", "exit_gate")


def validate_spec(spec) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(spec, dict):
        return False, ["spec must be a mapping"]

    name = spec.get("name")
    if not name or not isinstance(name, str):
        errors.append("missing or empty 'name'")

    phases = spec.get("phases")
    if not isinstance(phases, list) or not phases:
        errors.append("'phases' must be a non-empty list")
        return False, errors

    catalog = lifecycle.catalog()
    seen: set[str] = set()
    for entry in phases:
        if isinstance(entry, str):
            pname = entry
            if pname not in catalog:
                errors.append(
                    f"unknown catalog phase '{pname}' (string entries must name a catalog phase)")
        elif isinstance(entry, dict) and "phase" in entry:
            pname = entry["phase"]
            if not isinstance(pname, str) or not pname:
                errors.append(f"phase entry has empty 'phase': {entry!r}")
                continue
            if pname not in catalog:
                missing = [f for f in _REQUIRED_FOR_CUSTOM if f not in entry]
                if missing:
                    errors.append(f"custom phase '{pname}' missing required fields: {missing}")
            for k in ("produces", "exit_gate"):
                if k in entry and (not isinstance(entry[k], list)
                                   or any(not isinstance(x, str) or not x for x in entry[k])):
                    errors.append(f"phase '{pname}' field '{k}' must be a list of non-empty strings")
            if "allows_code_write" in entry and not isinstance(entry["allows_code_write"], bool):
                errors.append(f"phase '{pname}' field 'allows_code_write' must be a boolean")
        else:
            errors.append(
                f"invalid phase entry (name string or mapping with 'phase'): {entry!r}")
            continue
        if pname in seen:
            errors.append(f"duplicate phase '{pname}'")
        seen.add(pname)

    if errors:
        return False, errors

    try:
        spine = pipeline.spec_to_spine(spec)
    except Exception as exc:  # noqa: BLE001 — surface as a validation error
        return False, [f"spec not buildable: {exc}"]

    # I1 termination: linear chain with a single terminal, every next resolvable.
    spine_names = {p.name for p in spine}
    terminals = [p for p in spine if p.next_phase is None]
    if len(terminals) != 1 or spine[-1].next_phase is not None:
        errors.append("I1 termination: spine must have exactly one terminal phase")
    for p in spine:
        if p.next_phase is not None and p.next_phase not in spine_names:
            errors.append(f"I1 termination: phase '{p.name}' points to unknown next '{p.next_phase}'")

    # I2 gate-closure: every required evidence has a producer.
    ok, unmet = gates.gate_closure_ok(spine)
    if not ok:
        errors.append(f"I2 gate-closure: required evidence with no producing phase: {unmet}")

    return (not errors, errors)
