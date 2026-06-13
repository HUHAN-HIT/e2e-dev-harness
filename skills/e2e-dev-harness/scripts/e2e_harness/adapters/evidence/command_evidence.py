"""Narrow command-evidence leaf (ported from legacy command_evidence.run_command).

Runs a command and returns tamper-evident JSON (exit code + stdout/stderr hashes).
"""
from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

COMMAND_EVIDENCE_SCHEMA = "e2e-dev-harness.command-evidence.v1"
DEFAULT_TIMEOUT_SECONDS = 600

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def record_command(repo: str | Path, command: str,
                   timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    repo = Path(repo).resolve()
    started = _now_iso()
    started_perf = time.perf_counter()
    try:
        # posix=True parses our controlled, quoted command strings consistently on
        # Windows and POSIX (Windows native quoting would leave literal quotes in argv).
        argv = shlex.split(command, posix=True)
    except ValueError as error:
        return {
            "schema": COMMAND_EVIDENCE_SCHEMA, "command": command, "argv": [],
            "cwd": str(repo), "started_at": started, "finished_at": _now_iso(),
            "elapsed_ms": 0, "exit_code": 2, "stdout_tail": "", "stderr_tail": str(error),
            "stdout_sha256": _sha256_text(""), "stderr_sha256": _sha256_text(str(error)),
        }
    try:
        completed = subprocess.run(argv, cwd=repo, text=True, capture_output=True,
                                   check=False, timeout=timeout)
        stdout, stderr, exit_code = completed.stdout or "", completed.stderr or "", completed.returncode
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = f"Command timed out after {timeout} seconds."
        exit_code = 124
    except OSError as error:
        stdout, stderr, exit_code = "", str(error), 127
    return {
        "schema": COMMAND_EVIDENCE_SCHEMA, "command": command, "argv": argv,
        "cwd": str(repo), "started_at": started, "finished_at": _now_iso(),
        "elapsed_ms": int((time.perf_counter() - started_perf) * 1000),
        "exit_code": exit_code,
        "stdout_tail": stdout[-4000:], "stderr_tail": stderr[-4000:],
        "stdout_sha256": _sha256_text(stdout), "stderr_sha256": _sha256_text(stderr),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
    }


def is_command_evidence(obj) -> bool:
    return (
        isinstance(obj, dict)
        and obj.get("schema") == COMMAND_EVIDENCE_SCHEMA
        and "exit_code" in obj
    )


def is_genuine_command_evidence(obj) -> bool:
    """True only for records that bear record_command's tamper-evident structure: an
    `environment` block and 64-hex content hashes. Rejects forged JSON with
    placeholder hashes. Defined here (next to is_command_evidence) so both the
    evidence validator and the audit-replay validator can reuse it without a cycle."""
    if not isinstance(obj, dict) or not isinstance(obj.get("environment"), dict):
        return False
    for hash_key in ("stdout_sha256", "stderr_sha256"):
        value = obj.get(hash_key)
        if not isinstance(value, str) or not _HEX64.match(value):
            return False
    return True
