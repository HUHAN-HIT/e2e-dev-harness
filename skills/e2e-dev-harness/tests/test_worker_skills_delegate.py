from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAP = {
    "e2e-harness-clarification": "superpowers:brainstorming",
    "e2e-harness-planning": "superpowers:writing-plans",
    "e2e-harness-tdd-red": "superpowers:test-driven-development",
    "e2e-harness-implementation": "superpowers:test-driven-development",
    "e2e-harness-review": "superpowers:requesting-code-review",
    "e2e-harness-completion": "superpowers:verification-before-completion",
}
OUTPUTS = {
    "e2e-harness-clarification": "clarification",
    "e2e-harness-planning": "plan",
    "e2e-harness-tdd-red": "failing_tests",
    "e2e-harness-implementation": "passing_tests",
    "e2e-harness-review": "review",
    "e2e-harness-completion": "verification",
}
# every worker skill must reference the canonical harness CLI (retired v1 path no longer exists)
NO_LEGACY_CLI = tuple(MAP)


def test_worker_skills_delegate_and_declare_outputs():
    for skill, sp in MAP.items():
        text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert sp in text, f"{skill} missing delegation to {sp}"
        assert "external skill system" in text, f"{skill} missing Superpowers fallback note"
        assert "harness contract" in text, f"{skill} missing harness-contract fallback"
        assert OUTPUTS[skill] in text, f"{skill} missing output {OUTPUTS[skill]}"
        assert "expected_outputs" in text, f"{skill} missing output contract section"


def test_reworked_skills_drop_legacy_cli():
    for skill in NO_LEGACY_CLI:
        text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "e2e_dev_harness.py" in text, f"{skill} missing canonical CLI reference"


def test_clarification_skill_mandates_open_questions_loop():
    """A4: the clarifier must enumerate every ambiguity as an open_question and
    loop until none remain `open` — not 'ask only for ...'. The doc must teach the
    same status vocabulary the CLARIFIED gate enforces."""
    text = (ROOT / "skills" / "e2e-harness-clarification" / "SKILL.md").read_text(encoding="utf-8")
    assert "open_questions" in text, "clarification skill must describe the open_questions ledger"
    for status in ("open", "resolved", "deferred"):
        assert status in text, f"clarification skill must teach status '{status}'"
    assert "循环" in text, "clarification skill must mandate looping until questions are cleared"


def test_planning_skill_emits_structured_module_plan():
    """B5: PLANNED now demands a machine-readable module plan, so the planner skill
    must teach the module_plan evidence key, its schema, and the dependency field."""
    text = (ROOT / "skills" / "e2e-harness-planning" / "SKILL.md").read_text(encoding="utf-8")
    assert "module_plan" in text, "planning skill must declare the module_plan output"
    assert "module-plan.v1" in text, "planning skill must reference the module-plan schema id"
    assert "depends_on" in text, "planning skill must teach the dependency graph field"


def test_implementation_skill_describes_per_module_namespacing():
    """B5: in a multi-track run the implementer is dispatched per module
    (IMPLEMENTED#<module>) and must submit namespaced evidence keys."""
    text = (ROOT / "skills" / "e2e-harness-implementation" / "SKILL.md").read_text(encoding="utf-8")
    assert "#<module>" in text, "implementation skill must describe per-module key namespacing"


def test_adversarial_review_skill_contract():
    """The opt-in adversarial reviewer worker skill must follow the harness
    contract, cover all three perspectives via their evidence keys, and carry the
    canonical submit command so a fresh-context worker can self-load it and act."""
    text = (ROOT / "skills" / "e2e-harness-adversarial-review" / "SKILL.md").read_text(encoding="utf-8")
    assert "external skill system" in text, "adversarial skill missing Superpowers fallback note"
    assert "harness contract" in text, "adversarial skill missing harness-contract fallback"
    assert "expected_outputs" in text, "adversarial skill missing output contract section"
    for key in ("adversarial_code_review", "adversarial_design_review", "adversarial_test_design_review"):
        assert key in text, f"adversarial skill missing perspective key {key}"
    assert "e2e_dev_harness.py" in text, "adversarial skill missing canonical CLI reference"
    assert "submit" in text, "adversarial skill missing submit command"
    # Slice 2: the gate evidence is structured JSON, so the skill must teach the schema id
    assert "e2e-dev-harness.adversarial-review.v1" in text, "adversarial skill missing structured schema id"
