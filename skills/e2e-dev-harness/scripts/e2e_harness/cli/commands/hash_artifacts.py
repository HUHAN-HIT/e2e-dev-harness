"""Hash command facade.

Single byte-exact source of truth for the ``sha256:<64-hex>`` values that
handoff frontmatter ``input_hashes`` / ``output_hashes`` need. Agents must call
this instead of hand-rolling ``python -c "import hashlib"`` so the digest is
guaranteed to match what ``handoff_gate`` recomputes via ``read_bytes()``.
"""

from __future__ import annotations

from pathlib import Path

import artifact_registry
from common import posix
from e2e_harness.cli.status import write_status


def _repo_relative(repo: Path, full: Path) -> str:
    try:
        return posix(full.relative_to(repo))
    except ValueError:
        return posix(full)


def run(
    repo: Path,
    paths: list[Path],
    status_file: Path | None = None,
) -> tuple[int, dict]:
    repo = Path(repo).resolve()
    entries: list[dict] = []
    blocked: list[str] = []
    for raw in paths or []:
        candidate = Path(raw)
        full = candidate if candidate.is_absolute() else repo / candidate
        full = full.resolve()
        if not full.is_file():
            blocked.append(f"File not found: {posix(candidate)}")
            continue
        ref = _repo_relative(repo, full)
        digest = artifact_registry.sha256(full)
        entries.append(
            {
                "path": ref,
                "sha256": digest,
                "frontmatter_line": f"{ref} sha256:{digest}",
            }
        )
    ready = not blocked and bool(entries)
    result = {
        "schema": "e2e-dev-harness.hash.v1",
        "ready": ready,
        "hash_entries": entries,
        "blocked_reasons": blocked,
    }
    write_status(status_file, result)
    return (0 if ready else 2), result


def run_from_args(args) -> tuple[int, dict]:
    return run(
        getattr(args, "repo"),
        getattr(args, "path", None) or [],
        status_file=getattr(args, "status_file", None),
    )
