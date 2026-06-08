"""start: create the one run-state (after validating its pipeline)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from harness_v2.core import run_state, pipeline_validate
from harness_v2 import pipeline


def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.feature
    tier = args.tier
    reasons: list[str] = []
    if tier == "auto":
        from harness_v2.adapters.tier import classify
        tier, reasons = classify.classify_tier(args.request)

    pipeline_ref = getattr(args, "pipeline", None) or tier
    spec = pipeline.load_spec(pipeline_ref)  # load/parse error -> main.py emits error JSON (exit 2)
    ok, errors = pipeline_validate.validate_spec(spec)
    if not ok:
        return 2, {"error": "invalid pipeline", "pipeline": pipeline_ref, "errors": errors}

    custom = pipeline.is_path(pipeline_ref)
    rel = Path("docs/agent-runs") / run_id / "run-state.json"
    path = repo / rel
    st = run_state.new_run_state(
        run_id, args.feature, args.request, tier=tier, pipeline=pipeline_ref,
        pipeline_spec=spec if custom else None)
    run_state.save(path, st)
    return 0, {"schema": "e2e-dev-harness-v2.start.v1", "run_id": run_id,
               "run_state": str(path), "current_phase": "CREATED",
               "tier": tier, "pipeline": pipeline_ref, "tier_reasons": reasons}
