#!/usr/bin/env python3
"""Shared helpers for e2e-dev-harness scripts."""

from __future__ import annotations

import os
import shlex
import xml.etree.ElementTree as ET
from pathlib import Path


SKIP_DIRS = {".git", ".idea", ".vscode", "target", "build", "node_modules", ".gradle", "graphify-out", "agent-runs"}
SHELL_CONTROL_TOKENS = {"&&", "||", "|", ";", "<", ">", ">>", "2>", "2>>", "&"}


def posix(pathlike) -> str:
    return str(pathlike).replace("\\", "/")


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
