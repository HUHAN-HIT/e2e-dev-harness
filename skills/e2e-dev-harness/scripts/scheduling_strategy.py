#!/usr/bin/env python3
"""Auditable scheduling strategy for harness agent runs."""

from __future__ import annotations

import re


SCHEMA = "e2e-dev-harness.scheduling-decision.v1"
MAX_PARALLEL_WORKERS = 4
COMPLEX_REASON_MARKERS = (
    "large",
    "design-heavy",
    "contract",
    "schema",
    "database",
    "security",
    "payment",
    "refund",
    "multi-step",
)
AC_RE = re.compile(r"\bAC-?(\d+)\b", re.IGNORECASE)


def acceptance_ids(design_text: str) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for match in AC_RE.finditer(design_text or ""):
        ac_id = f"AC-{int(match.group(1))}"
        if ac_id not in seen:
            seen.add(ac_id)
            ids.append(ac_id)
    return ids


def complex_single_service(reasons: list[str], ac_ids: list[str]) -> bool:
    reason_text = " ".join(str(reason).lower() for reason in reasons)
    return len(ac_ids) > 1 or any(
        marker in reason_text for marker in COMPLEX_REASON_MARKERS
    )


def _lanes_for_acceptance(ac_ids: list[str], service: str) -> list[dict]:
    return [
        {
            "id": f"lane-{ac_id.lower()}",
            "acceptance_id": ac_id,
            "service": service,
            "parallel_group": f"task-item:{service}:{ac_id}",
            "requires_disjoint_edit_scope": True,
        }
        for ac_id in ac_ids
    ]


def decide(
    selected_mode: str,
    services: list[str] | None = None,
    reasons: list[str] | None = None,
    design_text: str = "",
) -> dict:
    service_list = list(services or [])
    reason_list = list(reasons or [])
    ac_ids = acceptance_ids(design_text)
    primary_service = service_list[0] if service_list else ""

    if selected_mode == "multi" or len(service_list) > 1:
        worker_count = min(MAX_PARALLEL_WORKERS, max(2, len(service_list)))
        return {
            "schema": SCHEMA,
            "selected_mode": selected_mode,
            "execution_model": "service-parallel",
            "max_workers": worker_count,
            "task_split": {"strategy": "service", "acceptance_ids": ac_ids},
            "implementation_lanes": [
                {
                    "id": f"service-{index + 1}",
                    "service": service,
                    "parallel_group": f"service:{service}",
                    "requires_disjoint_edit_scope": True,
                }
                for index, service in enumerate(service_list)
            ],
            "parallelism": {
                "design": "service-parallel",
                "test": "service-parallel",
                "code": "service-parallel",
                "review": "service-parallel",
            },
            "review_strategy": {
                "service_reviewers": service_list,
                "global_review": True,
                "aggregation": "service-reviews-then-global-r3",
            },
            "blocked_parallelism": [],
            "reasons": reason_list,
        }

    if selected_mode == "single-review" and complex_single_service(
        reason_list, ac_ids
    ):
        lane_ac_ids = ac_ids or ["AC-1"]
        lanes = _lanes_for_acceptance(lane_ac_ids, primary_service)
        return {
            "schema": SCHEMA,
            "selected_mode": selected_mode,
            "execution_model": "split-single",
            "max_workers": min(2, max(1, len(lanes))),
            "task_split": {
                "strategy": "acceptance-criteria",
                "acceptance_ids": lane_ac_ids,
            },
            "implementation_lanes": lanes,
            "parallelism": {
                "design": "serial",
                "test": "task-item-parallel",
                "code": "gated-by-edit-scope",
                "review": "task-item-parallel",
            },
            "review_strategy": {
                "service_reviewers": service_list,
                "global_review": True,
                "aggregation": "task-item-reviews-then-service-r3",
            },
            "blocked_parallelism": [
                "single service code lanes need non-overlapping edit scopes "
                "before concurrent code dispatch"
            ],
            "reasons": reason_list,
        }

    return {
        "schema": SCHEMA,
        "selected_mode": selected_mode,
        "execution_model": "single-worker",
        "max_workers": 1,
        "task_split": {"strategy": "single", "acceptance_ids": ac_ids},
        "implementation_lanes": [],
        "parallelism": {
            "design": "serial",
            "test": "serial",
            "code": "serial",
            "review": "serial",
        },
        "review_strategy": {
            "service_reviewers": service_list,
            "global_review": selected_mode == "single-review",
            "aggregation": (
                "single-reviewer-chain"
                if selected_mode == "single-review"
                else "minimal"
            ),
        },
        "blocked_parallelism": [],
        "reasons": reason_list,
    }
