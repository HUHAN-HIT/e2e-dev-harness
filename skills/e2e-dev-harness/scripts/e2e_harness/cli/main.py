"""Unified e2e-dev-harness CLI."""
from __future__ import annotations

import argparse
import json
import sys

from e2e_harness.cli.commands import (
    start,
    next as next_cmd,
    dispatch,
    submit,
    gate,
    status,
    validate_pipeline,
    doctor,
    migrate,
)

_COMMANDS = {
    "start": start.run, "next": next_cmd.run, "dispatch": dispatch.run,
    "submit": submit.run, "gate": gate.run, "status": status.run,
    # 7th verb — deliberate design §6 exception for the M3 config layer (U4).
    "validate-pipeline": validate_pipeline.run,
    "doctor": doctor.run,
    # F2: one-shot legacy-run contract back-fill (Hybrid model).
    "migrate": migrate.run,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="e2e-dev-harness")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("start"); s.add_argument("--repo", default=".")
    # Inline or UTF-8 file. The file channel bypasses argv so non-ASCII text is
    # never mangled by the console codepage (Windows/git-bash); resolution and
    # the mojibake guard live in start.run via core.text_input.
    s.add_argument("--feature", default=None); s.add_argument("--feature-file", default=None)
    s.add_argument("--request", default=None); s.add_argument("--request-file", default=None)
    # Default auto: the classifier is active unless a tier is pinned. (A static
    # default would leave it dormant and silently under-tier every run.)
    s.add_argument("--tier", choices=["auto", "minimal", "standard", "critical", "audited"], default="auto")
    s.add_argument("--pipeline", default=None,
                   help="built-in name or path to a custom pipeline yaml (overrides --tier's spine)")
    s.add_argument("--adapter", default=None, help="force domain adapter (backend|frontend)")
    s.add_argument("--scan", action="store_true", help="run adapter scan to raise tier floor")
    s.add_argument("--preview-tier", action="store_true",
                   help="compute tier recommendation/options without creating a run")

    for verb in ("next", "status"):
        sp = sub.add_parser(verb); sp.add_argument("--state", required=True); sp.add_argument("--repo", default=".")

    d = sub.add_parser("dispatch"); d.add_argument("--state", required=True); d.add_argument("--repo", default=".")
    d.add_argument("--runtime", default="codex")
    d.add_argument("--team-profile", default=None)
    d.add_argument("--max-workers", type=int, default=None)
    d.add_argument("--json", action="store_true", help="accepted for compatibility; output is always JSON")

    sm = sub.add_parser("submit"); sm.add_argument("--state", required=True); sm.add_argument("--repo", default=".")
    sm.add_argument("--phase", required=True); sm.add_argument("--key", default=None); sm.add_argument("--path", default=None)
    sm.add_argument("--status", choices=["done", "failed"], default="done")
    sm.add_argument("--reason", default=None)

    g = sub.add_parser("gate"); g.add_argument("--state", required=True); g.add_argument("--repo", default=".")
    g.add_argument("--phase", default=None)

    vp = sub.add_parser("validate-pipeline"); vp.add_argument("--pipeline", required=True)

    doc = sub.add_parser("doctor"); doc.add_argument("project_root", nargs="?", default=".")
    doc.add_argument("--json", action="store_true", help="accepted for installer compatibility; output is always JSON")
    doc.add_argument("--state", default=None, help="run-state path for read-only diagnostic")
    doc.add_argument("--runtime", default="claude",
                     help="hook runtime to validate in --strict mode (claude|claude-code|codex|opencode)")
    doc.add_argument("--strict", action="store_true",
                     help="promote settings/hooks readiness from informational to hard blockers")

    mg = sub.add_parser("migrate"); mg.add_argument("--state", required=True); mg.add_argument("--repo", default=".")
    return p


def _force_utf8_io() -> None:
    """Emit machine-readable JSON as UTF-8 regardless of the console codepage.

    The CLI contract is "JSON to stdout"; on a non-UTF-8 console (e.g. cp936/GBK
    on Windows) `ensure_ascii=False` output would otherwise be encoded in the
    platform codepage and fail to decode downstream. Reconfigure before any write.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def main(argv=None) -> int:
    _force_utf8_io()
    args = build_parser().parse_args(argv)
    try:
        code, result = _COMMANDS[args.command](args)
    except Exception as exc:  # noqa: BLE001 — contract: every command emits JSON
        sys.stdout.write(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
