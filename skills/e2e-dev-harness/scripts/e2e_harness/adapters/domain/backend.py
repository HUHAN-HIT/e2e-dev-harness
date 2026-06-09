"""Backend domain adapter — the default. Emits no pipeline overrides and no
domain block, so a backend run stays byte-identical to pre-U5 (parity)."""
from __future__ import annotations

from pathlib import Path

from e2e_harness.adapters import scanner

_MARKERS = ("pom.xml", "build.gradle", "build.gradle.kts", "pyproject.toml", "setup.py", "go.mod")
_JAVA = ("pom.xml", "build.gradle", "build.gradle.kts")


class BackendAdapter:
    name = "backend"
    review_profile = "backend-default"

    def __init__(self, repo: Path | None = None):
        self.repo = Path(repo) if repo else None

    @classmethod
    def detect(cls, repo: Path) -> bool:
        return any((Path(repo) / m).exists() for m in _MARKERS)

    @property
    def test_runner(self) -> str:
        return "maven" if self.repo and any((self.repo / m).exists() for m in _JAVA) else "pytest"

    def scan(self, repo, request) -> dict | None:
        repo = Path(repo)
        try:
            if any((repo / m).exists() for m in _JAVA):
                return scanner.discover_scope_java_spring(str(repo))
            return scanner.discover_scope(str(repo))
        except Exception:
            return None

    def pipeline_overrides(self) -> dict:
        return {}
