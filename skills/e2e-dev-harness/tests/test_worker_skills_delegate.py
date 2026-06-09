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
# every v2 worker skill must reference the v2 CLI, never the legacy one
NO_LEGACY_CLI = tuple(MAP)
LEGACY_CLI = "skills/e2e-dev-harness/scripts/e2e_dev_harness.py"


def test_worker_skills_delegate_and_declare_outputs():
    for skill, sp in MAP.items():
        text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert sp in text, f"{skill} missing delegation to {sp}"
        assert OUTPUTS[skill] in text, f"{skill} missing output {OUTPUTS[skill]}"
        assert "expected_outputs" in text, f"{skill} missing output contract section"


def test_reworked_skills_drop_legacy_cli():
    for skill in NO_LEGACY_CLI:
        text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert LEGACY_CLI not in text, f"{skill} still references legacy CLI"
        assert "e2e_dev_harness_v2.py" in text, f"{skill} missing v2 CLI reference"
