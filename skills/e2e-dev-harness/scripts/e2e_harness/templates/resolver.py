"""Template resolver facade over extension registry overrides."""

from __future__ import annotations

from pathlib import Path

import plugin_registry


def resolve_template(repo: Path, template_path: str, default_text: str = "", registry: dict | None = None) -> dict:
    return plugin_registry.resolve_template(repo, template_path, default_text=default_text, registry=registry)
