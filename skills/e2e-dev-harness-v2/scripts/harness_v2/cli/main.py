"""Unified v2 CLI: 6 verbs."""
from __future__ import annotations

import argparse
import json
import sys

from harness_v2.cli.commands import start, next as next_cmd, dispatch, submit, gate, status, validate_pipeline

_COMMANDS = {
    "start": start.run, "next": next_cmd.run, "dispatch": dispatch.run,
    "submit": submit.run, "gate": gate.run, "status": status.run,
    # 7th verb — deliberate design §6 exception for the M3 config layer (U4).
    "validate-pipeline": validate_pipeline.run,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="e2e-harness-v2")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("start"); s.add_argument("--repo", default=".")
    s.add_argument("--feature", required=True); s.add_argument("--request", required=True)
    s.add_argument("--tier", choices=["auto", "minimal", "standard", "critical", "audited"], default="minimal")
    s.add_argument("--pipeline", default=None,
                   help="built-in name or path to a custom pipeline yaml (overrides --tier's spine)")
    s.add_argument("--adapter", default=None, help="force domain adapter (backend|frontend)")
    s.add_argument("--scan", action="store_true", help="run adapter scan to raise tier floor")

    for verb in ("next", "status"):
        sp = sub.add_parser(verb); sp.add_argument("--state", required=True); sp.add_argument("--repo", default=".")

    d = sub.add_parser("dispatch"); d.add_argument("--state", required=True); d.add_argument("--repo", default=".")
    d.add_argument("--runtime", default="codex")

    sm = sub.add_parser("submit"); sm.add_argument("--state", required=True); sm.add_argument("--repo", default=".")
    sm.add_argument("--phase", required=True); sm.add_argument("--key", default=None); sm.add_argument("--path", default=None)
    sm.add_argument("--status", choices=["done", "failed"], default="done")
    sm.add_argument("--reason", default=None)

    g = sub.add_parser("gate"); g.add_argument("--state", required=True); g.add_argument("--repo", default=".")
    g.add_argument("--phase", default=None)

    vp = sub.add_parser("validate-pipeline"); vp.add_argument("--pipeline", required=True)
    return p


def main(argv=None) -> int:
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
