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
    recover,
    approve_impact_degradation,
)

_COMMANDS = {
    "start": start.run, "next": next_cmd.run, "dispatch": dispatch.run,
    "submit": submit.run, "gate": gate.run, "status": status.run,
    # 7th verb — deliberate design §6 exception for the M3 config layer (U4).
    "validate-pipeline": validate_pipeline.run,
    "doctor": doctor.run,
    # F2: one-shot legacy-run contract back-fill (Hybrid model).
    "migrate": migrate.run,
    # F-1: approval-gated, auditable control-plane recovery (design Phase 3).
    "recover": recover.run,
    # GitNexus impact analysis: coordinator records the degradation trust anchor.
    "approve-impact-degradation": approve_impact_degradation.run,
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
    s.add_argument("--language-profile", default=None,
                   help="force language profile by name or path to .e2e/language-profile.json")
    s.add_argument("--scan", action="store_true", help="run adapter scan to raise tier floor")
    s.add_argument("--preview-tier", action="store_true",
                   help="compute tier recommendation/options without creating a run")
    # GitNexus impact assessment mode for this run. Default `auto` turns impact on:
    # the CLARIFIED->PLANNED gate runs, and an unverifiable assessment blocks with a
    # degrade offer (coordinator asks the user). `off` opts a run out entirely.
    s.add_argument("--impact-mode", choices=["off", "auto", "strict"], default="auto",
                   help="GitNexus impact assessment mode for this run (default auto = on)")
    # A1: a tier below the recommendation is a downgrade that must be confirmed by the
    # user. --confirm-downgrade carries a required --downgrade-reason (the audit anchor
    # written into run-state.approvals.tier_downgrade). Without a valid confirmation,
    # `start` refuses to create the run (exit 2) — the downgrade fact is never settled
    # by coordinator interpretation.
    s.add_argument("--confirm-downgrade", action="store_true",
                   help="confirm a tier below the recommendation (requires --downgrade-reason)")
    s.add_argument("--downgrade-reason", default=None,
                   help="why the user chose a tier below the recommendation (audit anchor)")
    s.add_argument("--downgrade-source", default=None,
                   help="provenance of the downgrade confirmation (default: user)")

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
    sm.add_argument("--worker-id", dest="worker_id", default=None,
                    help="OWN1 namespace guard: reject evidence whose #module differs "
                         "from the worker's (defense-in-depth; self-supplied)")

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

    # F-1 recover: two-step, approval-gated control-plane repair (design Phase 3).
    # --plan is read-only; --apply requires --approval and is the ONLY path that
    # may flip coordinator_may_write_worker_outputs (under explicit approval).
    rc = sub.add_parser("recover"); rc.add_argument("--state", required=True); rc.add_argument("--repo", default=".")
    rc.add_argument("--plan", action="store_true", help="read-only: emit a recovery plan (default)")
    rc.add_argument("--apply", action="store_true", help="apply the approved narrow repair")
    rc.add_argument("--approval", default=None, help="path to a recovery-approval.v1 file (required for --apply)")

    # Coordinator records the impact-degradation trust anchor (design: Degraded Approval).
    ai = sub.add_parser("approve-impact-degradation")
    ai.add_argument("--state", required=True)
    ai.add_argument("--approval", required=True)
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
