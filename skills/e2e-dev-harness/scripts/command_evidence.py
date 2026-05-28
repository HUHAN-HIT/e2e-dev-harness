#!/usr/bin/env python3
"""Run a command and write tamper-evident JSON evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import DEFAULT_SUBPROCESS_TIMEOUT_SECONDS, split_command  # noqa: E402


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def repo_path(repo: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    root = repo.resolve()
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"Evidence path resolves outside repository: {path}") from error
    return resolved


def run_command(repo: Path, command: str, timeout_seconds: int = DEFAULT_SUBPROCESS_TIMEOUT_SECONDS) -> dict:
    repo = repo.resolve()
    started = now_iso()
    started_perf = time.perf_counter()
    try:
        argv = split_command(command)
    except ValueError as error:
        return {
            "schema": "e2e-dev-harness.command-evidence.v1",
            "command": command,
            "argv": [],
            "cwd": str(repo),
            "started_at": started,
            "finished_at": now_iso(),
            "elapsed_ms": 0,
            "exit_code": 2,
            "stdout_tail": "",
            "stderr_tail": str(error),
            "stdout_sha256": sha256_text(""),
            "stderr_sha256": sha256_text(str(error)),
        }
    try:
        completed = subprocess.run(
            argv,
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = f"Command timed out after {timeout_seconds} seconds."
        exit_code = 124
    except OSError as error:
        stdout = ""
        stderr = str(error)
        exit_code = 127
    return {
        "schema": "e2e-dev-harness.command-evidence.v1",
        "command": command,
        "argv": argv,
        "cwd": str(repo),
        "started_at": started,
        "finished_at": now_iso(),
        "elapsed_ms": int((time.perf_counter() - started_perf) * 1000),
        "exit_code": exit_code,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "stdout_sha256": sha256_text(stdout),
        "stderr_sha256": sha256_text(stderr),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "path_entries": len(os.environ.get("PATH", "").split(os.pathsep)),
        },
    }


def write_evidence(path: Path, evidence: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--command", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_SUBPROCESS_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    try:
        output = repo_path(repo, args.output)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    result = run_command(repo, args.command, args.timeout_seconds)
    if output:
        write_evidence(output, result)
        result["evidence_path"] = str(output)
    if args.json or not output:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Command evidence written: {output}")
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
