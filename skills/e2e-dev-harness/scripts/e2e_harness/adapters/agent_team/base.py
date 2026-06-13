"""Provider contract for phase -> worker-packet planning."""
from __future__ import annotations

from typing import Protocol

REQUEST_SCHEMA = "e2e-dev-harness.agent-team-request.v1"
PLAN_SCHEMA = "e2e-dev-harness.agent-team-plan.v1"


class AgentTeamProvider(Protocol):
    name: str

    def capabilities(self) -> dict:
        ...

    def plan_phase(self, request: dict) -> dict:
        ...
