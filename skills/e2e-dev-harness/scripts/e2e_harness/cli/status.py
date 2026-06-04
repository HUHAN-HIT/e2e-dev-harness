"""Shared CLI status-file helpers."""

from __future__ import annotations

import json
from pathlib import Path


def write_status(path: Path | None, result: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
