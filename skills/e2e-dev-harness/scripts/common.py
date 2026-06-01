#!/usr/bin/env python3
"""Shared helpers for e2e-dev-harness scripts."""

from __future__ import annotations

import json
import os
import shlex
import sys
import xml.etree.ElementTree as ET
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_SUBPROCESS_TIMEOUT_SECONDS = 600

SKIP_DIRS = {".git", ".idea", ".vscode", "target", "build", "node_modules", ".gradle", "graphify-out", "agent-runs"}
SHELL_CONTROL_TOKENS = {"&&", "||", "|", ";", "<", ">", ">>", "2>", "2>>", "&"}


def configure_utf8_stdio() -> None:
    """Make CLI output stable for Windows agent hooks that expect UTF-8."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def posix(pathlike) -> str:
    return str(pathlike).replace("\\", "/")


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json_object(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(tmp_name).unlink(missing_ok=True)
        raise


def parse_modules(pom: Path) -> list[str]:
    if not pom.exists():
        return []
    try:
        root = ET.fromstring(pom.read_text(encoding="utf-8"))
    except Exception:
        return []
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}", 1)[0] + "}"
    modules = root.find(f"{ns}modules")
    if modules is None:
        return []
    return [module.text.strip() for module in modules.findall(f"{ns}module") if module.text and module.text.strip()]


def split_command(command: str) -> list[str]:
    args = shlex.split(command, posix=os.name != "nt")
    cleaned = [arg[1:-1] if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in {"'", '"'} else arg for arg in args]
    if not cleaned:
        raise ValueError("Command is empty.")
    blocked = [arg for arg in cleaned if arg in SHELL_CONTROL_TOKENS]
    if blocked:
        raise ValueError("Shell control operators are not supported in graph refresh commands: " + ", ".join(blocked))
    return cleaned
