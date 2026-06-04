"""Shared argparse helpers for the e2e-dev-harness CLI."""

from __future__ import annotations

import argparse


def add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json-full",
        "--full-json",
        dest="json_full",
        action="store_true",
        help="Print the complete JSON result to stdout.",
    )
    parser.add_argument("--compact-output", action="store_true", help="Print compact coordinator-safe stdout; this is the default.")
