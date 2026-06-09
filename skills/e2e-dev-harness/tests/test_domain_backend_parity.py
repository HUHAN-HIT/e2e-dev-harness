"""Backend is the default adapter: it contributes no pipeline overrides, so the
merged spec is byte-identical to the named built-in for every tier (parity)."""
from pathlib import Path

from harness_v2.adapters.domain import select, merge_overrides
from harness_v2 import pipeline


def test_backend_overrides_empty_and_spec_identity():
    a = select(Path("."), explicit="backend")
    assert a.pipeline_overrides() == {}
    for tier in ("minimal", "standard", "critical", "audited"):
        spec = pipeline.load_spec(tier)
        assert merge_overrides(spec, a.pipeline_overrides()) == spec
