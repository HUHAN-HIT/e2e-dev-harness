from e2e_harness.adapters.evidence import impact


def _verified():
    return {
        "schema": impact.SCHEMA,
        "status": "verified",
        "tool": "gitnexus",
        "seeds": [{"kind": "symbol", "name": "_phase_request",
                   "file_path": "x.py", "reason": "r"}],
        "impact": [{"seed": "_phase_request", "direction": "upstream", "risk": "LOW",
                    "summary": {"direct": 1, "processes_affected": 1, "modules_affected": 1},
                    "affected_processes": [{"name": "run", "file_path": "x.py"}],
                    "affected_modules": ["Commands"]}],
        "planning_constraints": [], "open_questions": [], "degradation": None, "approval": None,
    }


def test_verified_artifact_passes():
    ok, reason = impact.validate_impact_assessment(_verified())
    assert ok is True and reason is None


def test_not_applicable_passes():
    obj = {"schema": impact.SCHEMA, "status": "not_applicable",
           "seeds": [], "impact": [], "open_questions": []}
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is True and reason is None


def test_not_object_rejected():
    ok, reason = impact.validate_impact_assessment(["nope"])
    assert ok is False and reason == "not-object"


def test_bad_schema_rejected():
    obj = _verified(); obj["schema"] = "wrong"
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is False and reason == "bad-schema"


def test_bad_status_rejected():
    obj = _verified(); obj["status"] = "maybe"
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is False and reason.startswith("bad-status")


# --- Task 1.2: edge cases (blocked / degraded / verified rigor) ---

def test_blocked_without_open_questions_fails():
    obj = {"schema": impact.SCHEMA, "status": "blocked", "seeds": [], "impact": [],
           "open_questions": []}
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is False and reason == "blocked-without-open-questions"


def test_blocked_with_open_questions_passes():
    obj = {"schema": impact.SCHEMA, "status": "blocked", "seeds": [], "impact": [],
           "open_questions": [{"id": "IQ-001", "question": "Which handler?", "status": "open"}]}
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is True and reason is None
    assert impact.open_questions(obj) == [{"id": "IQ-001", "question": "Which handler?"}]


def test_degraded_without_approval_fails():
    obj = {"schema": impact.SCHEMA, "status": "degraded", "seeds": [], "impact": [],
           "approval": None}
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is False and reason == "degraded-without-approval"


def test_verified_high_risk_without_processes_fails():
    obj = _verified()
    obj["impact"][0]["risk"] = "HIGH"
    obj["impact"][0]["affected_processes"] = []
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is False and reason.startswith("high-risk-without-processes")


def test_verified_seed_without_impact_fails():
    obj = _verified()
    obj["seeds"].append({"kind": "symbol", "name": "orphan", "file_path": "y.py", "reason": "r"})
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is False and reason == "seed-without-impact:orphan"


def test_max_seed_risk_picks_highest():
    obj = _verified()
    obj["impact"].append({"seed": "_phase_request", "direction": "upstream", "risk": "CRITICAL",
                          "summary": {}, "affected_processes": [{"name": "x"}], "affected_modules": []})
    assert impact.max_seed_risk(obj) == "CRITICAL"


def test_approval_matches_true_and_false():
    obj = {"approval": {"sha256": "abc"}}
    assert impact.approval_matches(obj, {"approvals": {"impact_degradation": {"sha256": "abc"}}}) is True
    assert impact.approval_matches(obj, {"approvals": {"impact_degradation": {"sha256": "zzz"}}}) is False
    assert impact.approval_matches(obj, {}) is False
