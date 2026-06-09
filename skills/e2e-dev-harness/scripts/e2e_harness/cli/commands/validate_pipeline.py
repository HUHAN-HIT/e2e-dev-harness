"""validate-pipeline: preflight I1/I2 check on a pipeline (name or path)."""
from __future__ import annotations

from e2e_harness import pipeline
from e2e_harness.core import pipeline_validate


def run(args) -> tuple[int, dict]:
    spec = pipeline.load_spec(args.pipeline)  # load/parse error -> main.py emits error JSON (exit 2)
    ok, errors = pipeline_validate.validate_spec(spec)
    return (0 if ok else 1), {
        "schema": "e2e-dev-harness-v2.validate-pipeline.v1",
        "ok": ok,
        "pipeline": args.pipeline,
        "errors": errors,
    }
