#!/usr/bin/env python3
"""Background regeneration of ledger / 台账 artifacts for a harness run.

Spec D3: ledger artifacts (artifact-registry completeness, run-summary) are no
longer the agent's responsibility to hand-build for non-audited tiers. This Stop
hook regenerates any missing ledger artifacts for a run directory so the
completion verifier can downgrade their absence to warnings.

Hard requirement: this hook MUST NOT break the main flow. Every code path is
wrapped so that any failure is recorded to ``evidence/ledger-hook-degradation.json``
under the run directory and the process STILL returns 0.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import artifact_registry  # noqa: E402
import harness_stop_guard  # noqa: E402
import harness_verify  # noqa: E402


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def _resolve(repo: Path, value: str | None) -> Path | None:
    if not value:
        return None
    repo_root = repo.resolve()
    path = Path(value)
    resolved = (path if path.is_absolute() else repo_root / path).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        return None
    return resolved


def _write_degradation(run_dir: Path, error: str) -> None:
    """Best-effort degradation note; swallow any secondary failure."""
    try:
        evidence_dir = run_dir / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "e2e-dev-harness.ledger-hook-degradation.v1",
            "hook": "generate_ledger_hook",
            "error": error,
        }
        (evidence_dir / "ledger-hook-degradation.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 - degradation note is itself best-effort
        pass


def _regenerate(repo: Path, state_path: Path, run_dir: Path) -> None:
    """Regenerate missing ledger artifacts. May raise; caller records and recovers."""
    state_data = _load_json(state_path if state_path.is_absolute() else repo / state_path)

    # Artifact registry: rebuild only when the referenced file is missing so we
    # never clobber an agent-authored registry.
    registry_path = _resolve(repo, state_data.get("artifact_registry"))
    if registry_path and not registry_path.exists():
        registry = artifact_registry.build_registry(
            repo,
            str(state_data.get("run_id") or run_dir.name),
            {},
            str(state_data.get("selected_mode") or ""),
            list(state_data.get("services") or []),
        )
        artifact_registry.write_registry(repo, registry_path, registry)

    # Run summary: regenerate when run-summary.json is absent in the run dir.
    summary_json = run_dir / "run-summary.json"
    summary_md = run_dir / "run-summary.md"
    if not summary_json.exists():
        result = harness_verify.validate(repo, state_path)
        harness_verify.write_summary_outputs(repo, state_path, result, summary_json, summary_md)


def run(repo: Path, run_state_path: Path) -> int:
    """Regenerate ledger artifacts for the run owning ``run_state_path``.

    ALWAYS returns 0. On any failure, writes a degradation note under the run
    directory's ``evidence/`` folder and returns 0 anyway.
    """
    repo = Path(repo).resolve()
    state_path = Path(run_state_path)
    run_dir = (state_path if state_path.is_absolute() else repo / state_path).resolve().parent
    try:
        _regenerate(repo, state_path, run_dir)
    except Exception:  # noqa: BLE001 - hook must never raise into the main flow
        _write_degradation(run_dir, traceback.format_exc())
    return 0


def _drain_hook_input(source: str | None) -> None:
    """Drain stdin when the runtime feeds it; tolerate empty/garbage/no stdin."""
    if source == "-":
        try:
            sys.stdin.read()
        except Exception:  # noqa: BLE001 - draining stdin must never raise
            pass


def _discover_run_state(repo: Path, explicit: Path | None) -> Path | None:
    """Locate the active run-state path the same way the stop guard does.

    Prefers an explicit ``--state`` path; otherwise reuses
    ``harness_stop_guard.latest_run_state`` (latest ``docs/agent-runs/*/run-state.json``
    by mtime) so discovery stays a single source of truth.
    """
    if explicit:
        return explicit
    try:
        return harness_stop_guard.latest_run_state(repo)
    except Exception:  # noqa: BLE001 - discovery failure must degrade to "no run"
        return None


def main(argv: list[str] | None = None) -> int:
    """Stop-hook entry point.

    Invoked as ``generate_ledger_hook.py <target-repo> --hook-input -`` (the
    standard harness Stop/advice hook argv shape). ALWAYS returns 0 and NEVER
    raises: any error is recorded as degradation evidence under the run dir and
    the process still exits 0. When no active run-state is found, exits 0
    quietly (nothing to backfill).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--state", "--run-state", dest="state", type=Path)
    parser.add_argument(
        "--hook-input",
        help="JSON hook input, or '-' for stdin (drained, not required).",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # A Stop hook must never abort the main flow on bad argv.
        return 0

    _drain_hook_input(args.hook_input)

    try:
        repo = Path(args.repo).resolve()
        state_path = _discover_run_state(repo, args.state)
        if not state_path:
            # No active harness run-state: nothing to backfill, exit quietly.
            return 0
        return run(repo, state_path)
    except Exception:  # noqa: BLE001 - top-level guard; hook must never raise
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
