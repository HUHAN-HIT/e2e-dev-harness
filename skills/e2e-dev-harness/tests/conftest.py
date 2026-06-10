import os
import random
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# --- Seedable, dependency-free isolation guard ---------------------------------
# Set E2E_TEST_SEED=<int> to randomize collection order reproducibly. This makes
# cross-test state leakage observable without adding a third-party plugin
# (the project's zero-runtime-dependency property is a feature). A failing run
# prints its seed so it can be reproduced exactly.


def _seeded_order(items, seed):
    """Pure, deterministic permutation of items for a given integer seed."""
    ordered = list(items)
    random.Random(seed).shuffle(ordered)
    return ordered


def _active_seed():
    raw = os.environ.get("E2E_TEST_SEED")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def pytest_collection_modifyitems(session, config, items):
    seed = _active_seed()
    if seed is None:
        return
    items[:] = _seeded_order(items, seed)


def pytest_report_header(config):
    seed = _active_seed()
    if seed is not None:
        return f"e2e-test-seed: {seed} (reproduce failures with E2E_TEST_SEED={seed})"
    return None
