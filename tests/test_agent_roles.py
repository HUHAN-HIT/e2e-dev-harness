"""Single-source-of-truth agent role registry.

These tests pin the declarative contract of `agent_roles`:
- the seven canonical role keys exist with complete template bodies;
- `template_text` renders the same section markers the harness already requires;
- `resolve_role_key` reproduces the legacy name->key substring semantics;
- `PHASE_ROLE_GROUPS` covers every workflow phase;
- declarative `skills` / `subagent_kind` metadata is present for consumers.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_roles  # noqa: E402
import orchestration_plan  # noqa: E402
from e2e_harness.cli.commands import start as start_command  # noqa: E402


CANONICAL_KEYS = {
    "requirements-clarifier",
    "use-case-designer",
    "implementation-planner",
    "test-case-developer",
    "code-developer",
    "semantic-reviewer",
    "coverage-reviewer",
}

TEMPLATE_FIELDS = ("boundary", "inputs", "forbidden", "outputs", "done")


class RoleRegistryTest(unittest.TestCase):
    def test_registry_has_seven_canonical_keys(self) -> None:
        self.assertEqual(CANONICAL_KEYS, set(agent_roles.ROLE_REGISTRY))

    def test_each_role_has_complete_template_body(self) -> None:
        for key, entry in agent_roles.ROLE_REGISTRY.items():
            template = entry["template"]
            for field in TEMPLATE_FIELDS:
                self.assertTrue(str(template.get(field, "")).strip(), f"{key}.{field}")

    def test_template_text_renders_required_markers(self) -> None:
        text = agent_roles.template_text("code-developer")
        self.assertIn("## Role Boundary", text)
        self.assertIn("## Allowed Inputs", text)
        self.assertIn("## Forbidden", text)
        self.assertIn("## Required Outputs", text)
        self.assertIn("## Done When", text)
        self.assertIn("Do not alter requirements", text)

    def test_template_text_unknown_role_falls_back_to_code_developer(self) -> None:
        self.assertEqual(
            agent_roles.template_text("code-developer"),
            agent_roles.template_text("nonexistent-role").replace(
                "nonexistent-role", "code-developer"
            ),
        )


class ResolveRoleKeyTest(unittest.TestCase):
    CASES = {
        "requirements-clarifier": "requirements-clarifier",
        "use-case-designer": "use-case-designer",
        "service-designer-order-service": "use-case-designer",
        "implementation-planner": "implementation-planner",
        "test-case-developer": "test-case-developer",
        "test-case-developer-order-service": "test-case-developer",
        "code-developer": "code-developer",
        "code-developer-order-service": "code-developer",
        "coverage-reviewer": "coverage-reviewer",
        "design-reviewer": "semantic-reviewer",
        "single-reviewer-r1-design": "semantic-reviewer",
        "test-reviewer": "semantic-reviewer",
        "implementation-reviewer-order-service": "semantic-reviewer",
        "totally-unknown": "",
    }

    def test_resolve_matches_legacy_semantics(self) -> None:
        for name, expected in self.CASES.items():
            self.assertEqual(expected, agent_roles.resolve_role_key(name), name)


class PhaseRoleGroupTest(unittest.TestCase):
    EXPECTED = {
        "clarify": "design",
        "design": "design",
        "plan": "planning",
        "tdd-red": "test",
        "implement": "code",
        "r1-review": "review",
        "r2-review": "review",
        "r3-review": "review",
        "completion": "coverage",
    }

    def test_phase_role_groups_cover_all_phases(self) -> None:
        self.assertEqual(self.EXPECTED, dict(agent_roles.PHASE_ROLE_GROUPS))


class RoleMetadataTest(unittest.TestCase):
    def test_test_case_developer_declares_tdd_skill(self) -> None:
        self.assertIn(
            "superpowers:test-driven-development",
            agent_roles.ROLE_REGISTRY["test-case-developer"]["skills"],
        )

    def test_reviewer_roles_declare_reviewer_subagent_kind(self) -> None:
        for key in ("semantic-reviewer", "coverage-reviewer"):
            self.assertEqual("reviewer", agent_roles.ROLE_REGISTRY[key]["subagent_kind"], key)
        for key in ("code-developer", "test-case-developer", "implementation-planner"):
            self.assertEqual("general", agent_roles.ROLE_REGISTRY[key]["subagent_kind"], key)


class LegacyParityTest(unittest.TestCase):
    """The registry must remain behavior-identical to the legacy consumers."""

    NAME_MATRIX = (
        "requirements-clarifier",
        "use-case-designer",
        "service-designer-order-service",
        "implementation-planner",
        "test-case-developer",
        "test-case-developer-order-service",
        "code-developer",
        "code-developer-order-service",
        "coverage-reviewer",
        "design-reviewer",
        "single-reviewer-r1-design",
        "single-reviewer-r2-test",
        "single-reviewer-r3-implementation",
        "test-reviewer",
        "implementation-reviewer",
        "implementation-reviewer-order-service",
        "totally-unknown",
    )

    def test_start_role_template_details_match_registry(self) -> None:
        for key, detail in start_command.ROLE_TEMPLATE_DETAILS.items():
            self.assertEqual(detail, agent_roles.ROLE_REGISTRY[key]["template"], key)

    def test_role_template_text_identical_for_every_key(self) -> None:
        for key in CANONICAL_KEYS:
            self.assertEqual(
                start_command.role_template_text(key), agent_roles.template_text(key), key
            )

    def test_resolve_role_key_matches_orchestration_role_template_key(self) -> None:
        for name in self.NAME_MATRIX:
            self.assertEqual(
                orchestration_plan.role_template_key(name),
                agent_roles.resolve_role_key(name),
                name,
            )

    def test_role_group_for_phase_matches_shared_table(self) -> None:
        phases = list(PhaseRoleGroupTest.EXPECTED) + ["unknown-phase"]
        for phase in phases:
            self.assertEqual(
                orchestration_plan.role_group_for_phase(phase),
                agent_roles.PHASE_ROLE_GROUPS.get(phase, "coordination"),
                phase,
            )


if __name__ == "__main__":
    unittest.main()
