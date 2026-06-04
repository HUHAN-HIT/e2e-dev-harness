"""Gate runner facade for the enterprise engine package."""

from __future__ import annotations

import implementation_gate


def run(request) -> dict:
    return implementation_gate.validate_gate_request(request)

