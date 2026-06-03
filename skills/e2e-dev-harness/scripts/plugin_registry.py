#!/usr/bin/env python3
"""Config-backed extension registry for enterprise harness customization."""

from __future__ import annotations

import importlib
import inspect
import sys
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


def provider_search_paths(repo: Path) -> list[Path]:
    return [repo / ".e2e" / "providers", repo]


def _split_provider_spec(spec: str) -> tuple[str, str]:
    text = spec.strip()
    if ":" in text:
        module_name, attr_name = text.split(":", 1)
        return module_name.strip(), attr_name.strip()
    module_name, dot, attr_name = text.rpartition(".")
    return module_name.strip(), attr_name.strip() if dot else ""


def load_provider(repo: Path, spec: str) -> dict:
    module_name, attr_name = _split_provider_spec(spec)
    if not module_name or not attr_name:
        raise ValueError(f"Provider spec must use module:attribute or module.attribute form: {spec}")
    paths = [str(path) for path in provider_search_paths(repo) if path.exists()]
    original_path = list(sys.path)
    try:
        for path in reversed(paths):
            if path not in sys.path:
                sys.path.insert(0, path)
        importlib.invalidate_caches()
        module = importlib.import_module(module_name)
        provider = getattr(module, attr_name)
        if callable(provider) and not inspect.signature(provider).parameters:
            provider = provider()
        if isinstance(provider, dict):
            return dict(provider)
        return {"name": attr_name, "provider": provider}
    finally:
        sys.path[:] = original_path


def load_providers(repo: Path, extension_point: str, registry: dict | None = None) -> dict:
    active_registry = registry or load_registry(repo)
    specs = active_registry.get(extension_point, [])
    result = {"extension_point": extension_point, "providers": [], "warnings": []}
    if not isinstance(specs, list):
        result["warnings"].append(f"Extension point {extension_point} is not a provider list.")
        return result
    for spec in specs:
        try:
            result["providers"].append(load_provider(repo, str(spec)))
        except (AttributeError, ImportError, OSError, ValueError) as error:
            result["warnings"].append(f"Could not load provider {spec}: {error}")
    return result
