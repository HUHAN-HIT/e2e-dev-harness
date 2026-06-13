"""Agent-team profile registry."""
from __future__ import annotations

from pathlib import Path

from e2e_harness.adapters.agent_team import schema

_SKILL_ROOT = Path(__file__).resolve().parents[4]
_BUNDLED_DIR = _SKILL_ROOT / "agent-teams"


def _profile_paths(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")], key=lambda p: p.name)


def load_bundled_profiles() -> list[dict]:
    return [schema.load_profile_file(path) for path in _profile_paths(_BUNDLED_DIR)]


def load_profiles(repo_root: str | Path | None = None) -> list[dict]:
    return load_bundled_profiles()


def load_profile(name: str, repo_root: str | Path | None = None) -> dict:
    wanted = str(name or "").strip()
    if not wanted:
        raise KeyError("profile name is required")
    for profile in load_bundled_profiles():
        if profile.get("name") == wanted:
            return profile
    if repo_root is not None:
        local = Path(repo_root) / ".e2e" / "agent-teams" / f"{wanted}.yaml"
        if local.is_file():
            return schema.load_profile_file(local)
    raise KeyError(f"unknown agent team profile: {wanted}")
