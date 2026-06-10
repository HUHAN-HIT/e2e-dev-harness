"""Integrity-checked text input for `start` (feature/request).

Non-ASCII argv on Windows/git-bash is decoded with the console codepage
(e.g. cp936), which is lossy for UTF-8 bytes and produces U+FFFD. That
corruption is irreversible in-process, so we (a) offer a UTF-8 *file*
channel that bypasses argv entirely and (b) reject text that already
carries the replacement char instead of letting it silently mis-tier.
"""
from __future__ import annotations

from pathlib import Path

_REPLACEMENT = "�"


def is_corrupted(text: str) -> bool:
    """True if text carries the Unicode replacement char (lossy decode)."""
    return _REPLACEMENT in (text or "")


def read_text_arg(*, inline: str | None, file_path: str | None, name: str) -> str:
    """Resolve a `--<name>` / `--<name>-file` pair into clean text.

    Exactly one source must be supplied. A file is read as UTF-8. The result
    is rejected if it shows lossy-decode corruption.
    """
    if inline is not None and file_path is not None:
        raise ValueError(f"--{name} and --{name}-file are mutually exclusive (got both)")
    if inline is None and file_path is None:
        raise ValueError(f"--{name} or --{name}-file is required")

    if file_path is not None:
        text = Path(file_path).read_text(encoding="utf-8")
    else:
        text = inline  # type: ignore[assignment]

    if is_corrupted(text):
        raise ValueError(
            f"--{name} text is corrupted (U+FFFD replacement char detected) — "
            "non-ASCII argv was mangled by the console encoding. "
            f"Pass --{name}-file <utf8 file>, or re-run with PYTHONUTF8=1."
        )
    return text
