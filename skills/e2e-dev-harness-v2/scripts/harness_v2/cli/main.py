"""Unified v2 CLI: 6 verbs."""
from __future__ import annotations

import argparse
import json
import sys

from harness_v2.cli.commands import start, next as next_cmd, dispatch, submit, gate, status

_COMMANDS = {
    "start": start.run, "next": next_cmd.run, "dispatch": dispatch.run,
    "submit": submit.run, "gate": gate.run, "status": status.run,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="e2e-harness-v2")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("start"); s.add_argument("--repo", default=".")
    s.add_argument("--feature", required=True); s.add_argument("--request", required=True)

    for verb in ("next", "dispatch", "status"):
        sp = sub.add_parser(verb); sp.add_argument("--state", required=True); sp.add_argument("--repo", default=".")

    sm = sub.add_parser("submit"); sm.add_argument("--state", required=True); sm.add_argument("--repo", default=".")
    sm.add_argument("--phase", required=True); sm.add_argument("--key", required=True); sm.add_argument("--path", required=True)

    g = sub.add_parser("gate"); g.add_argument("--state", required=True); g.add_argument("--repo", default=".")
    g.add_argument("--phase", default=None)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    code, result = _COMMANDS[args.command](args)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
