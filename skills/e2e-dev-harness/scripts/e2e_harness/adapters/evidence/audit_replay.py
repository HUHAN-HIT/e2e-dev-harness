"""F5: validate an `audit_replay` manifest.

The audited VERIFIED gate's `audit_replay` evidence must be a machine-checkable
manifest (schema e2e-dev-harness.audit-replay.v1) whose every claim references a
GENUINE command-evidence artifact — prose narrative ("full suite: 376 passed") can
no longer satisfy the gate.

Strength: anti-FORGERY (each backing record must bear record_command's tamper-evident
structure) but intentionally NOT anti-TAMPER — there is no exit_code replay, because
re-running full suites / installer at gate time would be slow and side-effecting. A
hand-edited exit_code on an otherwise-genuine record can therefore still pass; this is
a deliberate, weaker guarantee than `verification` (which IS replayed). Sufficient for
the goal of rejecting prose, but it must not be mistaken for verification-grade proof.

Manifest shape:
    {"schema": "e2e-dev-harness.audit-replay.v1",
     "claims": [{"name": "full local suite", "evidence": "VERIFIED-full-suite.json",
                 "expect_exit": 0}, ...]}
Each claim's `evidence` is resolved RELATIVE TO repo_root (not the record's cwd).
"""
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.adapters.evidence import command_evidence

AUDIT_REPLAY_SCHEMA = "e2e-dev-harness.audit-replay.v1"


def validate_audit_replay(obj, repo_root) -> tuple[bool, str | None]:
    if not isinstance(obj, dict) or obj.get("schema") != AUDIT_REPLAY_SCHEMA:
        return False, "bad-schema"
    claims = obj.get("claims")
    if not isinstance(claims, list) or not claims:
        return False, "no-claims"
    repo = Path(repo_root)
    for claim in claims:
        if not isinstance(claim, dict):
            return False, "bad-claim"
        name = str(claim.get("name", "?"))
        rel = claim.get("evidence")
        if not rel:
            return False, f"no-evidence-path:{name}"
        full = Path(rel)
        if not full.is_absolute():
            full = repo / rel
        if not full.is_file():
            return False, f"evidence-not-found:{name}"
        try:
            rec = json.loads(full.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False, f"evidence-not-json:{name}"
        if not command_evidence.is_command_evidence(rec):
            return False, f"not-command-evidence:{name}"
        if not command_evidence.is_genuine_command_evidence(rec):
            return False, f"forged-evidence:{name}"
        expect = claim.get("expect_exit", 0)
        if rec.get("exit_code") != expect:
            return False, f"exit-{rec.get('exit_code')}:{name}"
    return True, None
