#!/usr/bin/env python3
"""Config-backed extension registry for enterprise harness customization."""

from __future__ import annotations

from pathlib import Path


SCHEMA = "e2e-dev-harness.registry.v1"
LIST_KEYS = {"custom_gates", "scanners", "policy_packs"}


def _default_registry(config_path: Path) -> dict:
    return {
        "schema": SCHEMA,
        "config_path": str(config_path).replace("\\", "/"),
        "custom_gates": [],
        "scanners": [],
        "policy_packs": [],
        "template_override_dir": "",
        "warnings": [],
    }


def _parse_simple_yaml(text: str) -> dict:
    data: dict[str, object] = {}
    current_list = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list:
            values = data.setdefault(current_list, [])
            if isinstance(values, list):
                values.append(stripped[2:].strip().strip("'\""))
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key in LIST_KEYS:
            data[key] = []
            current_list = key
            if value.startswith("[") and value.endswith("]"):
                items = [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
                data[key] = items
            continue
        current_list = ""
        data[key] = value
    return data


def load_registry(repo: Path, config_path: Path | None = None) -> dict:
    config = config_path or repo / ".e2e" / "config.yaml"
    registry = _default_registry(config)
    if not config.exists():
        return registry
    try:
        parsed = _parse_simple_yaml(config.read_text(encoding="utf-8"))
    except OSError as error:
        registry["warnings"].append(f"Could not read extension config: {error}")
        return registry
    for key in LIST_KEYS:
        value = parsed.get(key, [])
        registry[key] = [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []
    registry["template_override_dir"] = str(parsed.get("template_override_dir", "") or "").strip()
    return registry
