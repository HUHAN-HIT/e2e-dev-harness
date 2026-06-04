"""Execution packet domain facade.

The legacy implementation still lives in coordinator_flow.py while the
enterprise package shape is introduced incrementally.
"""

from __future__ import annotations

from typing import Any

import coordinator_flow


def for_lifecycle(lifecycle: str, action: dict[str, Any] | None = None, primary_command: str = "") -> dict:
    return coordinator_flow.execution_packet_for_lifecycle(lifecycle, action or {}, primary_command)

