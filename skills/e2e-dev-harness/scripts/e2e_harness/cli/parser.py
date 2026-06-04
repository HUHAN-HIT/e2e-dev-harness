"""Shared argparse helpers for the e2e-dev-harness CLI."""

from __future__ import annotations

import argparse

from pathlib import Path

import agent_instructions
import task_tier


def add_prepare_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--design-doc", type=Path)
    parser.add_argument("--path", action="append", help="Path that may be touched; can be repeated.")
    parser.add_argument("--service", action="append", help="Affected service directory or service name; can be repeated.")
    parser.add_argument("--agent-mode", choices=["auto", "strict", "optional", "off"], default="strict")
    parser.add_argument("--agent-scope", choices=["auto", "discovery", "affected", "all"], default="auto")
    parser.add_argument("--include-agent-content", action="store_true")
    parser.add_argument("--max-agent-chars", type=int, default=12000)
    parser.add_argument("--max-discovered-services", type=int, default=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT)
    parser.add_argument("--superpowers-mode", choices=["auto", "strict", "optional", "off"], default="auto")
    parser.add_argument("--memory-mode", choices=["auto", "strict", "optional", "off"], default="auto")
    parser.add_argument("--agent-orchestration-mode", choices=["auto", "single", "single-review", "multi", "off"], default="auto")
    parser.add_argument("--service-scope", choices=["auto", "discovery", "affected", "all"], default="auto")
    parser.add_argument("--agent-run-dir", help="Archive directory for generated agent run files.")
    parser.add_argument("--run-date", help="Date prefix for default agent run directory, YYYY-MM-DD.")
    parser.add_argument("--kg-mode", choices=["auto", "gitnexus", "graphify", "both"], default="auto")
    parser.add_argument("--dependency-scan-mode", choices=["auto", "strict", "optional", "off"], default="auto")
    parser.add_argument("--dependency-output-dir", type=Path)
    parser.add_argument("--workflow-tier", choices=task_tier.TIERS, default="auto")
    parser.add_argument("--no-write-dependency-report", dest="write_dependency_report", action="store_false")
    parser.set_defaults(write_dependency_report=True)
    parser.add_argument("--status-file", type=Path)


def add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json-full",
        "--full-json",
        dest="json_full",
        action="store_true",
        help="Print the complete JSON result to stdout.",
    )
    parser.add_argument("--compact-output", action="store_true", help="Print compact coordinator-safe stdout; this is the default.")
