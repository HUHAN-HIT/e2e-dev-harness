"""start: select a domain adapter, then create the one run-state (after
validating the adapter-merged pipeline).

The DomainAdapter seam lives entirely here (CLI layer) — core stays untouched:
the adapter contributes pipeline-spec overrides and a self-describing `domain`
block. Backend is the default adapter and emits neither, so a backend run is
byte-identical to pre-U5 (parity)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from e2e_harness.core import run_state, pipeline_validate
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.feature

    from e2e_harness.adapters.domain import select, merge_overrides, domain_block
    adapter = select(repo, explicit=getattr(args, "adapter", None))  # KeyError -> main.py exit 2

    tier = args.tier
    reasons: list[str] = []
    if tier == "auto":
        from e2e_harness.adapters.tier import classify
        scope = adapter.scan(repo, args.request) if getattr(args, "scan", False) else None
        tier, reasons = classify.classify_tier(args.request, scope)

    pipeline_ref = getattr(args, "pipeline", None) or tier
    spec = pipeline.load_spec(pipeline_ref)  # load/parse error -> main.py emits error JSON (exit 2)
    merged = merge_overrides(spec, adapter.pipeline_overrides())
    ok, errors = pipeline_validate.validate_spec(merged)
    if not ok:
        return 2, {"error": "invalid pipeline", "pipeline": pipeline_ref, "errors": errors}

    custom = pipeline.is_path(pipeline_ref)
    # Embed the resolved spec when the run is non-default in any way (custom
    # pipeline, adapter overrides, or a non-backend domain). Backend + built-in
    # stays lean (name only) — that is the parity contract.
    non_default = custom or bool(adapter.pipeline_overrides()) or adapter.name != "backend"
    dom = domain_block(adapter) if adapter.name != "backend" else None

    rel = Path("docs/agent-runs") / run_id / "run-state.json"
    path = repo / rel
    st = run_state.new_run_state(
        run_id, args.feature, args.request, tier=tier, pipeline=pipeline_ref,
        pipeline_spec=merged if non_default else None, domain=dom)
    run_state.save(path, st)
    return 0, {"schema": "e2e-dev-harness.start.v1", "run_id": run_id,
               "run_state": str(path), "current_phase": "CREATED",
               "tier": tier, "pipeline": pipeline_ref, "tier_reasons": reasons,
               "domain": adapter.name}
