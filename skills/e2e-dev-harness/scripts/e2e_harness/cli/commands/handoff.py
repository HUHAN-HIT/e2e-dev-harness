"""Handoff finalize command facade.

Worker agents write the handoff body and frontmatter; ``handoff finalize`` does the
mechanical, error-prone steps in one place so they never have to be hand-assembled:

1. Normalize the ``agent_id`` / ``status: ready`` frontmatter scalars.
2. Atomically rewrite ``<handoff>.md`` (``.partial`` -> rename).
3. Write the canonical ``<handoff>.ready.json`` marker (hash, producer, status).
4. Re-run ``handoff_gate.validate`` locally and surface the exact remaining blockers.

This command is the single writer of ``.ready.json``. If validation fails it rolls
the marker back, so an incomplete handoff never keeps a ready marker (the very
"marker says ready but body is incomplete" trap that caused repeated rework).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import handoff_gate
from e2e_harness.cli.status import write_status

_SCALAR_KEYS_ORDER = ("agent_id", "status")


def _split_frontmatter(text: str) -> tuple[list[str], str, bool]:
    """Return (frontmatter_lines, remainder_text, had_frontmatter)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], text, False
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            fm = lines[1:index]
            remainder = "\n".join(lines[index + 1 :])
            return fm, remainder, True
    return [], text, False


def _apply_scalars(fm_lines: list[str], scalars: dict[str, str]) -> list[str]:
    """Set or insert ``key: value`` scalars in frontmatter lines, preserving order."""
    result = list(fm_lines)
    remaining = dict(scalars)
    for i, line in enumerate(result):
        stripped = line.lstrip()
        for key in list(remaining):
            if stripped.startswith(f"{key}:"):
                indent = line[: len(line) - len(stripped)]
                result[i] = f"{indent}{key}: {remaining.pop(key)}"
                break
    for key in _SCALAR_KEYS_ORDER:
        if key in remaining:
            result.append(f"{key}: {remaining.pop(key)}")
    for key, value in remaining.items():
        result.append(f"{key}: {value}")
    return result


def _frontmatter_scalar(fm_lines: list[str], key: str) -> str:
    needle = f"{key}:"
    for line in fm_lines:
        stripped = line.lstrip()
        if stripped.startswith(needle):
            return stripped[len(needle) :].strip()
    return ""


def _render(fm_lines: list[str], remainder: str) -> str:
    body = "---\n" + "\n".join(fm_lines) + "\n---\n"
    if remainder:
        body += remainder if remainder.startswith("\n") else "\n" + remainder
    if not body.endswith("\n"):
        body += "\n"
    return body


def _closed_open_questions_text(text: str) -> bool:
    value = text.strip()
    if handoff_gate.is_no_open_questions(value):
        return True
    lowered = " ".join(value.lower().split())
    return "no open questions" in lowered and ("remain" in lowered or "resolved" in lowered or "needed" in lowered)


def _normalize_open_questions_section(remainder: str, frontmatter_open_questions: str) -> tuple[str, bool]:
    if not handoff_gate.is_no_open_questions(frontmatter_open_questions):
        return remainder, False
    lines = remainder.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower() != "## open questions":
            continue
        end = index + 1
        while end < len(lines) and not lines[end].lstrip().startswith("## "):
            end += 1
        existing = "\n".join(lines[index + 1 : end]).strip()
        if not _closed_open_questions_text(existing):
            return remainder, False
        replacement = lines[: index + 1] + ["", "None", ""] + lines[end:]
        return "\n".join(replacement).strip() + "\n", True
    return remainder, False


def _atomic_write_text(path: Path, text: str) -> None:
    partial = path.with_name(path.name + ".partial")
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, path)


def _content_blockers(repo: Path, handoff_path: Path) -> list[str]:
    """Run handoff_gate against just this file and return its blockers."""
    result = handoff_gate.validate(repo, handoff_dirs=[handoff_path])
    return list(result.get("blocked_reasons", []))


def run_finalize(
    repo: Path,
    handoff_path: Path,
    agent: str,
    status_file: Path | None = None,
) -> dict:
    repo = Path(repo).resolve()
    handoff = handoff_path if handoff_path.is_absolute() else repo / handoff_path
    handoff = handoff.resolve()

    result: dict = {
        "schema": "e2e-dev-harness.handoff-finalize.v1",
        "ready": False,
        "blocked_reasons": [],
        "warnings": [],
        "handoff": str(handoff),
        "agent": agent,
    }

    if not str(handoff).endswith(".md"):
        result["blocked_reasons"].append(f"Handoff path must be a .md file: {handoff}")
        return result
    if not handoff.is_file():
        result["blocked_reasons"].append(f"Handoff file does not exist: {handoff}")
        return result
    agent = str(agent or "").strip()
    if not agent:
        result["blocked_reasons"].append("--agent is required to set agent_id / producer_agent.")
        return result

    fm_lines, remainder, had_fm = _split_frontmatter(handoff.read_text(encoding="utf-8"))
    if not had_fm:
        result["blocked_reasons"].append(
            f"Handoff {handoff} has no YAML frontmatter block; worker must write frontmatter + body first."
        )
        return result

    updated_fm = _apply_scalars(fm_lines, {"agent_id": agent, "status": "ready"})
    updated_remainder, normalized_open_questions = _normalize_open_questions_section(
        remainder,
        _frontmatter_scalar(updated_fm, "open_questions"),
    )
    normalized = _render(updated_fm, updated_remainder)
    _atomic_write_text(handoff, normalized)

    marker = handoff_gate.marker_path(handoff)
    digest = hashlib.sha256(handoff.read_bytes()).hexdigest()
    marker_payload = {
        "path": handoff.relative_to(repo).as_posix(),
        "sha256": digest,
        "producer_agent": agent,
        "status": "ready",
    }
    _atomic_write_text(marker, json.dumps(marker_payload, indent=2, ensure_ascii=False) + "\n")

    blockers = _content_blockers(repo, handoff)
    if blockers:
        # Roll the marker back so an incomplete handoff never keeps a ready marker.
        try:
            marker.unlink()
        except OSError:
            pass
        result["blocked_reasons"] = blockers
        result["marker_rolled_back"] = True
        result["next_hint"] = "Fix the blockers in the handoff body/frontmatter, then rerun handoff finalize."
        return result

    result["ready"] = True
    result["ready_marker"] = str(marker)
    result["sha256"] = digest
    if normalized_open_questions:
        result["normalized_open_questions"] = True
    return result


def run_from_args(args) -> tuple[int, dict]:
    result = run_finalize(
        Path(getattr(args, "repo", Path("."))),
        getattr(args, "path"),
        getattr(args, "agent", "") or "",
        status_file=getattr(args, "status_file", None),
    )
    write_status(getattr(args, "status_file", None), result)
    return (0 if result["ready"] else 2), result
