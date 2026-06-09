"""Path-agnostic classification ported from legacy phase_guard.

Canonical harness convergence: control files = {run-state.json} (no .phase-lock);
hook-config 仅 claude + opencode。除 `discover_run_state` 外皆为纯函数。
"""
from __future__ import annotations

from pathlib import Path

CODE_SUFFIXES = {
    ".java", ".kt", ".groovy", ".py", ".js", ".jsx", ".ts", ".tsx",
    ".go", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".sql",
    ".xml", ".yml", ".yaml", ".properties", ".gradle",
}
CODE_FILENAMES = {"pom.xml", "build.gradle", "settings.gradle", "Dockerfile"}
ARTIFACT_PREFIXES = ("docs/agent-runs/",)
DOC_PREFIXES = (
    "docs/design/", "docs/requirements/", "docs/review-profiles/",
    "docs/superpowers/", ".e2e/",
)
CONTROL_FILENAMES = {"run-state.json"}
HOOK_CONFIG_PATHS = {".claude/settings.json"}
HOOK_CONFIG_PREFIXES = (".opencode/plugins/", ".opencode/plugin/")


def resolve_for_repo(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def is_inside_repo(repo: Path, path: Path) -> bool:
    resolved = resolve_for_repo(repo, path)
    if not resolved.is_absolute():
        return True
    try:
        resolved.resolve().relative_to(repo.resolve())
        return True
    except ValueError:
        return False


def posix_relative(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/").lstrip("/")


def is_code_path(repo: Path, path: Path) -> bool:
    resolved = resolve_for_repo(repo, path)
    if not is_inside_repo(repo, resolved):
        return False
    relative = posix_relative(repo, resolved)
    if relative.startswith(ARTIFACT_PREFIXES):
        return False
    if relative.startswith(DOC_PREFIXES):
        return False
    return resolved.name in CODE_FILENAMES or resolved.suffix in CODE_SUFFIXES


def is_control_file_path(repo: Path, path: Path) -> bool:
    resolved = resolve_for_repo(repo, path)
    return resolved.name in CONTROL_FILENAMES


def is_hook_config_path(repo: Path, path: Path) -> bool:
    relative = posix_relative(repo, resolve_for_repo(repo, path))
    if relative in HOOK_CONFIG_PATHS:
        return True
    return relative.startswith(HOOK_CONFIG_PREFIXES)


def discover_run_state(repo: Path) -> Path | None:
    """Locate the most recently updated active run-state (the one I/O helper)."""
    runs = Path(repo) / "docs" / "agent-runs"
    if not runs.is_dir():
        return None
    matches = sorted(
        runs.glob("*/run-state.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return matches[0] if matches else None
