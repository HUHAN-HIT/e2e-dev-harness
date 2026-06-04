"""Write-policy facade over phase guard enforcement."""

from __future__ import annotations

import phase_guard


def validate_action(*args, **kwargs) -> dict:
    return phase_guard.validate_action(*args, **kwargs)

