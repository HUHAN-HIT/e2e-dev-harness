"""Narrow scanner interface (ported from legacy scanners facade; logic unchanged).

Exposes `discover_scope(repo, request)` (generic contract) and the java_spring
AST scope discovery. The vendored `_legacy/` dir is placed on sys.path so the
legacy flat imports (`import cross_service_dependency_scan`, `from common import …`)
resolve exactly as they did in the legacy skill.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LEGACY = Path(__file__).resolve().parent / "_legacy"
if str(_LEGACY) not in sys.path:
    sys.path.insert(0, str(_LEGACY))

from scanners import generic as _generic  # noqa: E402
from scanners import java_spring as _java_spring  # noqa: E402

discover_scope = _generic.discover_scope
discover_scope_java_spring = _java_spring.discover_scope

from .frontend import scan_frontend  # noqa: E402

__all__ = ["discover_scope", "discover_scope_java_spring", "scan_frontend"]
