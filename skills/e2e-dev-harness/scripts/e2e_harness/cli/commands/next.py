"""next: advance spine or return single blocker + navigation map."""
from __future__ import annotations

from pathlib import Path

from e2e_harness.core import run_state, engine, navigation
from e2e_harness.adapters.evidence import scope as scope_ev
from e2e_harness.adapters.evidence import clarification
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    spine = pipeline.spine_for_state(run_state.load(args.state), repo)
    holder: dict = {}

    def _advance(state):
        state["_run_state_path"] = str(args.state)
        res = engine.evaluate(spine, state, repo)
        holder["res"] = res
        # link ②: on completion, label the run COMPLETE vs PARTIAL from the
        # grounded scope manifest so a subset delivery is never a silent VERIFIED.
        if res.get("complete"):
            status, undelivered = scope_ev.label_delivery(state, repo)
            if status is not None:
                state["delivery"] = status
                state["undelivered"] = undelivered
                res["delivery"] = status
                res["undelivered"] = undelivered
        state.pop("_run_state_path", None)

    # Slice 1: extend the chain iff this run has one (started with emission on).
    state = run_state.mutate(args.state, _advance,
                             events_path=run_state.events_path_if_active(args.state))
    res = holder["res"]
    # fix A3: when CLARIFIED is the blocker, name the still-open questions so the
    # re-clarify loop is actionable (ask -> user answers -> resubmit -> advance)
    # instead of an opaque "acceptance_contract missing".
    if res.get("blocked_phase") == "CLARIFIED":
        pending = clarification.pending_from_state(state, repo)
        if pending:
            res["open_questions"] = pending
            ids = ", ".join(q["id"] for q in pending)
            res["blocker"] = f"{len(pending)} open question(s) awaiting user confirmation: {ids}"
        # When the blocker is an unverified GitNexus impact, surface the degrade
        # option so the coordinator can ask the user to resolve OR approve degradation
        # (impact is on by default; a problem must not silently stall the run).
        # strict 模式无降级路径(impact_bridge 拥有该策略并把 degradation_available
        # 盖在 binding 上);next 纯数据驱动,绝不宣传 bridge 会拒绝的 approval。
        binding = state.get("impact_assessment")
        if binding and binding.get("status") == "blocked":
            if binding.get("degradation_available", True):
                res["impact"] = {
                    "status": "blocked",
                    "degradation_available": True,
                    "approve_with": "approve-impact-degradation",
                    "message": ("GitNexus impact analysis could not be verified. Resolve "
                                "the open questions, or ask the user to approve degradation."),
                }
            else:
                res["impact"] = {
                    "status": "blocked",
                    "degradation_available": False,
                    "message": ("strict 模式无降级路径:请解决 IQ-* 问题"
                                "(修订验收契约触发重评)。"),
                }
    res["navigation_map"] = navigation.navigation_map(spine, state, repo)
    res["run_state"] = str(args.state)
    return 0, res
