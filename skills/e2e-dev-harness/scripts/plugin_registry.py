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
        sys.modules.pop(module_name, None)
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


def provider_health(repo: Path, registry: dict | None = None) -> list[dict]:
    active_registry = registry or load_registry(repo)
    health: list[dict] = []
    for extension_point in sorted(LIST_KEYS):
        loaded = load_providers(repo, extension_point, active_registry)
        warnings = list(loaded.get("warnings", []) or [])
        health.append(
            {
                "extension_point": extension_point,
                "ready": not warnings,
                "provider_count": len(loaded.get("providers", []) or []),
                "warnings": warnings,
            }
        )
    return health


def _provider_body(provider: object) -> object:
    if isinstance(provider, dict) and "provider" in provider:
        return provider["provider"]
    return provider


def provider_name(provider: object, fallback: str = "provider") -> str:
    body = _provider_body(provider)
    if not isinstance(body, dict):
        name = str(getattr(body, "name", "") or "")
        if name:
            return name
    if isinstance(provider, dict):
        return str(provider.get("name") or fallback)
    return str(getattr(body, "name", fallback) or fallback)


def _provider_phases(provider: object) -> list[str]:
    body = _provider_body(provider)
    values = body.get("phases", []) if isinstance(body, dict) else getattr(body, "phases", [])
    if isinstance(values, str):
        return [values] if values else []
    return [str(item) for item in values or []]


def _provider_languages(provider: object) -> list[str]:
    body = _provider_body(provider)
    values = body.get("languages", []) if isinstance(body, dict) else getattr(body, "languages", [])
    if isinstance(values, str):
        return [values] if values else []
    return [str(item) for item in values or []]


def _normalized_provider_result(provider: object, method: str, result: object) -> dict:
    if isinstance(result, dict):
        normalized = dict(result)
        normalized.setdefault("ready", not normalized.get("blocked_reasons"))
        normalized.setdefault("blocked_reasons", [])
        normalized.setdefault("warnings", [])
        return normalized
    ready = bool(result)
    return {
        "ready": ready,
        "blocked_reasons": [] if ready else [f"Provider {provider_name(provider)} returned a blocking result from {method}()."],
        "warnings": [],
    }


def _call_provider_method(provider: object, method: str, *args) -> dict:
    body = _provider_body(provider)
    target = body.get(method) if isinstance(body, dict) else getattr(body, method, None)
    if not callable(target):
        return {
            "ready": False,
            "blocked_reasons": [f"Provider {provider_name(provider)} does not implement {method}()."],
            "warnings": [],
        }
    result = target(*args)
    return _normalized_provider_result(provider, method, result)


def run_custom_gates(repo: Path, request, registry: dict | None = None) -> dict:
    loaded = load_providers(repo, "custom_gates", registry)
    phase = str(getattr(request, "phase", "") or "")
    results: list[dict] = []
    blocked: list[str] = []
    warnings = list(loaded.get("warnings", []) or [])
    for provider in loaded.get("providers", []) or []:
        name = provider_name(provider, "custom-gate")
        phases = _provider_phases(provider)
        if phases and phase not in phases:
            continue
        result = _call_provider_method(provider, "validate", request)
        results.append({"name": name, "phases": phases, "result": result})
        blocked.extend(f"Custom gate {name}: {reason}" for reason in result.get("blocked_reasons", []) or [])
        warnings.extend(f"Custom gate {name}: {warning}" for warning in result.get("warnings", []) or [])
    return {
        "ready": not blocked,
        "providers": results,
        "blocked_reasons": blocked,
        "warnings": warnings,
    }


def run_scanners(repo: Path, request: dict | None = None, registry: dict | None = None) -> dict:
    loaded = load_providers(repo, "scanners", registry)
    results: list[dict] = []
    blocked: list[str] = []
    warnings = list(loaded.get("warnings", []) or [])
    for provider in loaded.get("providers", []) or []:
        name = provider_name(provider, "scanner")
        languages = _provider_languages(provider)
        result = _call_provider_method(provider, "discover_scope", repo, request or {})
        results.append({"name": name, "languages": languages, "result": result})
        blocked.extend(f"Scanner {name}: {reason}" for reason in result.get("blocked_reasons", []) or [])
        warnings.extend(str(warning) for warning in result.get("warnings", []) or [])
    return {
        "ready": not blocked,
        "providers": results,
        "blocked_reasons": blocked,
        "warnings": warnings,
    }


def apply_policy_packs(repo: Path, request: dict, registry: dict | None = None) -> dict:
    loaded = load_providers(repo, "policy_packs", registry)
    result = dict(request)
    warnings = list(loaded.get("warnings", []) or [])
    blocked: list[str] = []
    applied: list[str] = []
    for provider in loaded.get("providers", []) or []:
        name = provider_name(provider, "policy")
        policy = _call_provider_method(provider, "apply", dict(result))
        if policy.get("blocked_reasons"):
            blocked.extend(f"Policy {name}: {reason}" for reason in policy.get("blocked_reasons", []) or [])
        warnings.extend(f"Policy {name}: {warning}" for warning in policy.get("warnings", []) or [])
        for key in ("forbidden_actions", "required_evidence"):
            existing = list(result.get(key, []) or [])
            additions = [str(item) for item in policy.get(key, []) or []]
            result[key] = list(dict.fromkeys(existing + additions))
        if policy.get("allowed_writes"):
            current = set(str(item) for item in result.get("allowed_writes", []) or [])
            proposed = set(str(item) for item in policy.get("allowed_writes", []) or [])
            result["allowed_writes"] = sorted(current & proposed) if current else sorted(proposed)
        applied.append(name)
    return {"ready": not blocked, "request": result, "applied": applied, "blocked_reasons": blocked, "warnings": warnings}


def resolve_template(repo: Path, template_path: str, default_text: str = "", registry: dict | None = None) -> dict:
    active_registry = registry or load_registry(repo)
    override_dir = str(active_registry.get("template_override_dir", "") or "").strip()
    normalized = template_path.replace("\\", "/").lstrip("/")
    if override_dir:
        candidate = repo / override_dir / normalized
        if candidate.exists() and candidate.is_file():
            return {
                "schema": "e2e-dev-harness.template.v1",
                "path": str((Path(override_dir) / normalized)).replace("\\", "/"),
                "text": candidate.read_text(encoding="utf-8"),
                "overridden": True,
                "warnings": [],
            }
    return {
        "schema": "e2e-dev-harness.template.v1",
        "path": normalized,
        "text": default_text,
        "overridden": False,
        "warnings": [],
    }
