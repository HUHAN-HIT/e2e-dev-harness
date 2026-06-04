"""Runtime adapter domain facade over the legacy runtime_adapters module."""

from __future__ import annotations

from runtime_adapters import (  # noqa: F401
    RUNTIME_STATUS_SEQUENCE,
    RuntimeActionResult,
    RuntimeAdapter,
    RuntimeCapabilities,
    SpawnResult,
    adapter_for,
    normalize_runtime,
)
