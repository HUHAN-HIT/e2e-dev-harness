"""Pre-code command facade."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path


def _legacy_cli():
    return importlib.import_module("e2e_dev_harness")


def run(
    repo: Path,
    tool: str = "Edit",
    paths: list[Path] | None = None,
    patch: Path | None = None,
    command_text: str = "",
    lock: Path | None = None,
    run_dir: Path | None = None,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    return run_from_args(
        argparse.Namespace(
            repo=repo,
            tool=tool,
            path=paths,
            patch=patch,
            command_text=command_text,
            lock=lock,
            run_dir=run_dir,
            status_file=status_file,
        )
    )


def run_from_args(args) -> tuple[int, dict]:
    legacy = _legacy_cli()
    repo = legacy.as_repo(args.repo)
    paths = list(args.path or [])
    if args.patch:
        patch_path = legacy.resolve_repo_path(repo, args.patch)
        patch_text = patch_path.read_text(encoding="utf-8", errors="replace") if patch_path and patch_path.exists() else ""
        paths.extend(Path(path) for path in legacy.phase_guard.paths_from_patch(patch_text))
    if args.command_text:
        paths.extend(Path(path) for path in legacy.phase_guard.paths_from_shell_command(args.command_text))
    result = legacy.phase_guard.validate_action(
        repo,
        args.tool,
        paths,
        args.lock,
        args.run_dir,
        command_text=args.command_text,
    )
    hook_status = legacy.runtime_hook_status(repo)
    result["pre_code"] = True
    result["tool"] = args.tool
    result["paths_checked"] = [str(path) for path in paths]
    result["hook_status"] = hook_status
    if not hook_status["ready"]:
        result["ready"] = False
        result.setdefault("blocked_reasons", []).append(
            "Runtime hook config is present but not enforcing; repair hooks with install_hooks.py or remove the broken runtime hook directory before relying on portable pre-code."
        )
    legacy.write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result
