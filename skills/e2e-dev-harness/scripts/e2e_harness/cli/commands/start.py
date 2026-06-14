"""start: select a domain adapter, then create the one run-state (after
validating the adapter-merged pipeline).

The DomainAdapter seam lives entirely here (CLI layer) — core stays untouched:
the adapter contributes pipeline-spec overrides and a self-describing `domain`
block. Backend is the default adapter and emits neither, so a backend run is
byte-identical to pre-U5 (parity)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from e2e_harness.core import run_state, pipeline_validate, text_input
from e2e_harness import pipeline


def _preview_result(*, feature: str, adapter_name: str, tier_recommendation: dict,
                    pipeline_ref: str, pipeline_override: bool) -> dict:
    # F1: the hard signals track `blocked` (is a user choice still needed?), not
    # merely `requested_below` (is this a downgrade?). A confirmed downgrade has
    # blocked=False, so preview correctly reports must_ask_user=False.
    blocked = tier_recommendation["downgrade"]["blocked"]
    return {
        "schema": "e2e-dev-harness.tier-preview.v1",
        "feature": feature,
        "domain": adapter_name,
        "run_will_be_created": False,
        "recommended_tier": tier_recommendation["recommended_tier"],
        "selected_tier": tier_recommendation["selected_tier"],
        "selection_source": tier_recommendation["selection_source"],
        "tier_reasons": tier_recommendation["reasons"],
        "tier_recommendation": tier_recommendation,
        "pipeline": pipeline_ref,
        "pipeline_override": pipeline_override,
        "tier_controls_pipeline": not pipeline_override,
        "confirmation": {
            # A1: hard machine signals so a coordinator RULE can stop and ask the user
            # before a real downgrade start — no longer prose-only guidance.
            "confirmation_required": blocked,
            "allowed_without_user_choice": not blocked,
            "must_ask_user": blocked,
            "recommended_start_args": [
                "start",
                "--tier",
                tier_recommendation["recommended_tier"],
            ],
            "choice_arg": "--tier <minimal|standard|critical|audited>",
        },
    }


def _seed_event_log(path: Path, st: dict, run_id: str, *, force: bool = False) -> None:
    """Slice 1: fix the run's witness once, at creation. Default (env unset) seeds
    `events.jsonl` (+ `.head` anchor) with the FULL initial transition — run.started
    plus phase.submitted(CREATED), derived from the same projection `mutate` uses —
    so the chain covers the run from birth and the projection already carries
    current_phase (no false drift before the first `next`). E2E_HARNESS_DISABLE_EVENTS=1
    leaves the run permanently event-free (CI / perf opt-out); the four forward
    commands then see no sibling and skip emission.

    Best-effort: the witness must never veto run creation. run-state.json is already
    saved (authoritative); a seeding failure warns, drops any partial sidecar so no
    half-chain can read as drift, and leaves the run event-free."""
    if os.environ.get("E2E_HARNESS_DISABLE_EVENTS") == "1" and not force:
        return
    from e2e_harness.core import event_log, state_store
    events_path = run_state.events_path_for(path)
    try:
        for event in state_store.derive_events({}, st):
            event_log.append_event(events_path, event)
    except Exception as exc:  # noqa: BLE001 — never crash `start` over the witness
        for stray in (events_path, Path(str(events_path) + ".head")):
            try:
                stray.unlink()
            except OSError:
                pass
        print(f"[e2e-dev-harness] WARNING: could not seed event witness for "
              f"{run_id} ({type(exc).__name__}: {exc}); run is event-free",
              file=sys.stderr)


def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    # Resolve inline-or-file and reject console-mangled (U+FFFD) text loudly,
    # before it can silently under-tier or be persisted into the run-state.
    feature = text_input.read_text_arg(
        inline=args.feature, file_path=getattr(args, "feature_file", None), name="feature")
    request = text_input.read_text_arg(
        inline=args.request, file_path=getattr(args, "request_file", None), name="request")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + feature

    from e2e_harness.adapters.domain import select, merge_overrides, domain_block
    adapter = select(repo, explicit=getattr(args, "adapter", None))  # KeyError -> main.py exit 2

    from e2e_harness.adapters.tier import recommend
    scope = adapter.scan(repo, request) if getattr(args, "scan", False) else None
    # A1: build the downgrade-confirmation token from the explicit CLI flags. The
    # reason IS the audit anchor, so an empty/missing reason is not a valid
    # confirmation — it leaves `confirmation` None and the downgrade stays blocked.
    confirmation = None
    if getattr(args, "confirm_downgrade", False):
        _reason = (getattr(args, "downgrade_reason", None) or "").strip()
        if _reason:
            confirmation = {"reason": _reason,
                            "source": getattr(args, "downgrade_source", None) or "user"}
    tier_recommendation = recommend.recommend_tier(
        request, scope, selected_tier=args.tier, confirmation=confirmation)
    tier = tier_recommendation["selected_tier"]
    reasons = tier_recommendation["reasons"]

    pipeline_ref = getattr(args, "pipeline", None) or tier
    custom = pipeline.is_path(pipeline_ref)

    # preview is a read-only dry run: it only SIGNALS (including a still-needed
    # downgrade choice) and never exits 2, so it returns BEFORE any pipeline
    # load/validate and before the blocked backstop. It needs only pipeline_ref +
    # custom, never the resolved spec — so an invalid --pipeline does not turn a
    # preview into an error.
    if getattr(args, "preview_tier", False):
        return 0, _preview_result(
            feature=feature,
            adapter_name=adapter.name,
            tier_recommendation=tier_recommendation,
            pipeline_ref=str(pipeline_ref),
            pipeline_override=custom,
        )

    # A1/F3: authoritative backstop, enforced BEFORE pipeline load/validate. The
    # downgrade gate depends ONLY on the tier recommendation, not on the pipeline, so
    # it must out-rank the "invalid pipeline" error — both exit 2, and if pipeline
    # validation ran first an invalid --pipeline would MASK the downgrade-blocked
    # signal, leaving the coordinator unaware it has to ask the user. A
    # below-recommended tier with no valid confirmation is BLOCKED here; the run is
    # never created, so a coordinator cannot turn a historical preference into a
    # current downgrade. preview (above) never reaches this branch; it only signals.
    downgrade = tier_recommendation["downgrade"]
    if downgrade["blocked"]:
        return 2, {
            "schema": "e2e-dev-harness.tier-downgrade-blocked.v1",
            "error": "selected tier is below the recommended tier and requires explicit user confirmation",
            "feature": feature,
            "recommended_tier": tier_recommendation["recommended_tier"],
            "selected_tier": tier_recommendation["selected_tier"],
            "remediation": ("re-run start with --confirm-downgrade --downgrade-reason "
                            "\"<why the user chose a lower tier>\", or use --tier "
                            + tier_recommendation["recommended_tier"]),
            "tier_recommendation": tier_recommendation,
        }

    spec = pipeline.load_spec(pipeline_ref)  # load/parse error -> main.py emits error JSON (exit 2)
    merged = merge_overrides(spec, adapter.pipeline_overrides())
    ok, errors = pipeline_validate.validate_spec(merged)
    if not ok:
        # F4: same self-describing error envelope as the tier-downgrade-blocked
        # sibling — a `schema` so consumers route on it, not on the `error` string.
        return 2, {"schema": "e2e-dev-harness.invalid-pipeline.v1",
                   "error": "invalid pipeline", "pipeline": pipeline_ref, "errors": errors}

    # Embed the resolved spec when the run is non-default in any way (custom
    # pipeline, adapter overrides, or a non-backend domain). Backend + built-in
    # stays lean (name only) — that is the parity contract.
    non_default = custom or bool(adapter.pipeline_overrides()) or adapter.name != "backend"
    dom = domain_block(adapter) if adapter.name != "backend" else None

    rel = Path("docs/agent-runs") / run_id / "run-state.json"
    path = repo / rel
    from e2e_harness.adapters.language import profile as language_profile
    language_doc = language_profile.resolve_language_profile(
        repo, domain_hint=adapter.name, explicit=getattr(args, "language_profile", None))
    language_binding, _profile_path = language_profile.persist_profile(repo, path.parent, language_doc)
    st = run_state.new_run_state(
        run_id, feature, request, tier=tier, pipeline=pipeline_ref,
        pipeline_spec=merged if non_default else None, domain=dom)
    st["language"] = language_binding
    st["tier_recommendation"] = tier_recommendation
    # A1: settle the confirmed downgrade ONCE, in run-state (mirror of
    # approvals.impact_degradation): an auditable anchor carrying the user's reason,
    # not a fact the coordinator can re-derive later.
    if downgrade["confirmed"]:
        st.setdefault("approvals", {})["tier_downgrade"] = {
            "confirmed_tier": tier,
            "recommended_tier": tier_recommendation["recommended_tier"],
            "reason": confirmation["reason"],
            "source": confirmation["source"],
            "recorded_by": "coordinator",
        }
    # GitNexus impact assessment mode (design). Default `auto` => impact is on; an
    # unverifiable assessment blocks with a degrade offer rather than stalling.
    st["impact"] = {"mode": getattr(args, "impact_mode", "auto") or "auto"}
    run_state.save(path, st)
    _seed_event_log(path, st, run_id, force=tier == "audited")
    return 0, {"schema": "e2e-dev-harness.start.v1", "run_id": run_id,
               "run_state": str(path), "current_phase": "CREATED",
               "tier": tier, "pipeline": pipeline_ref, "tier_reasons": reasons,
               "tier_recommendation": tier_recommendation,
               "domain": adapter.name}
