"""Single-source-of-truth agent role registry.

These tests pin the declarative contract of `agent_roles`:
- the seven canonical role keys exist with complete template bodies;
- `template_text` renders the same section markers the harness already requires;
- `resolve_role_key` reproduces the legacy name->key substring semantics;
- `PHASE_ROLE_GROUPS` covers every workflow phase;
- declarative `skills` / `subagent_kind` / `runtime_subagent_type` metadata is present for consumers.
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
        # Regression: a code-developer agent for a service whose slug contains
        # "test" must still resolve to code-developer, not test-case-developer.
        "code-developer-notification-test": "code-developer",
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


class PhaseRegistryTest(unittest.TestCase):
    """`PHASE_REGISTRY` is the single source of phase ordering knowledge."""

    EXPECTED_DEPENDS = {
        "clarify": [],
        "design": ["clarify"],
        "r1-review": ["design"],
        "plan": ["r1-review"],
        "tdd-red": ["design", "r1-review", "plan"],
        "r2-review": ["tdd-red"],
        "implement": ["tdd-red", "r2-review"],
        "r3-review": ["implement"],
        "completion": ["r3-review"],
    }
    EXPECTED_CANONICAL_ROLE = {
        "clarify": "requirements-clarifier",
        "design": "use-case-designer",
        "r1-review": "semantic-reviewer",
        "plan": "implementation-planner",
        "tdd-red": "test-case-developer",
        "r2-review": "semantic-reviewer",
        "implement": "code-developer",
        "r3-review": "semantic-reviewer",
        "completion": "coverage-reviewer",
    }

    def test_registry_covers_nine_phases(self) -> None:
        self.assertEqual(set(self.EXPECTED_DEPENDS), set(agent_roles.PHASE_REGISTRY))

    def test_each_phase_has_order_role_group_depends_on(self) -> None:
        for phase, meta in agent_roles.PHASE_REGISTRY.items():
            self.assertIsInstance(meta.get("order"), int, phase)
            self.assertTrue(str(meta.get("role_group", "")).strip(), phase)
            self.assertIsInstance(meta.get("depends_on"), list, phase)

    def test_depends_on_for_phase_matches_legacy(self) -> None:
        for phase, deps in self.EXPECTED_DEPENDS.items():
            self.assertEqual(deps, agent_roles.depends_on_for_phase(phase), phase)

    def test_depends_on_for_phase_unknown_defaults_to_plan(self) -> None:
        self.assertEqual(["plan"], agent_roles.depends_on_for_phase("nonexistent"))

    def test_depends_on_for_phase_returns_fresh_copies(self) -> None:
        first = agent_roles.depends_on_for_phase("tdd-red")
        first.append("mutated")
        self.assertEqual(
            ["design", "r1-review", "plan"], agent_roles.depends_on_for_phase("tdd-red")
        )

    def test_phase_role_group_matches_shared_table(self) -> None:
        for phase, group in PhaseRoleGroupTest.EXPECTED.items():
            self.assertEqual(group, agent_roles.phase_role_group(phase), phase)

    def test_phase_role_groups_table_is_derived_from_registry(self) -> None:
        self.assertEqual(
            {phase: meta["role_group"] for phase, meta in agent_roles.PHASE_REGISTRY.items()},
            dict(agent_roles.PHASE_ROLE_GROUPS),
        )

    def test_canonical_role_per_phase(self) -> None:
        for phase, role in self.EXPECTED_CANONICAL_ROLE.items():
            self.assertEqual(role, agent_roles.PHASE_REGISTRY[phase]["canonical_role"], phase)
            self.assertIn(role, agent_roles.ROLE_REGISTRY)

    def test_order_is_a_topological_linearization(self) -> None:
        order = {phase: meta["order"] for phase, meta in agent_roles.PHASE_REGISTRY.items()}
        for phase, deps in self.EXPECTED_DEPENDS.items():
            for dep in deps:
                self.assertLess(order[dep], order[phase], f"{dep} must order before {phase}")


class PhaseSubagentKindTest(unittest.TestCase):
    """Declared `subagent_kind` is the single source of runtime review routing."""

    EXPECTED = {
        "clarify": "general",
        "design": "general",
        "plan": "general",
        "tdd-red": "general",
        "implement": "general",
        "r1-review": "reviewer",
        "r2-review": "reviewer",
        "r3-review": "reviewer",
        "completion": "reviewer",
    }

    def test_phase_subagent_kind_matches_expected(self) -> None:
        for phase, kind in self.EXPECTED.items():
            self.assertEqual(kind, agent_roles.phase_subagent_kind(phase), phase)

    def test_phase_subagent_kind_unknown_is_empty(self) -> None:
        self.assertEqual("", agent_roles.phase_subagent_kind("nonexistent"))

    def test_reviewer_kind_is_self_consistent_with_role_group(self) -> None:
        # Declaration (subagent_kind) and routing (role_group) must agree:
        # a phase routes to a reviewer iff its group is review/coverage.
        for phase in agent_roles.PHASE_REGISTRY:
            is_reviewer = agent_roles.phase_subagent_kind(phase) == "reviewer"
            in_review_group = agent_roles.PHASE_ROLE_GROUPS[phase] in {"review", "coverage"}
            self.assertEqual(in_review_group, is_reviewer, phase)


class PhaseRuntimeSubagentTypeTest(unittest.TestCase):
    """Role declarations can route phases to concrete runtime subagent types."""

    EXPECTED = {
        "clarify": "requirements-clarifier",
        "design": "use-case-designer",
        "plan": "implementation-planner",
        "tdd-red": "test-case-developer",
        "implement": "code-developer",
        "r1-review": "semantic-reviewer",
        "r2-review": "semantic-reviewer",
        "r3-review": "semantic-reviewer",
        "completion": "coverage-reviewer",
    }

    def test_phase_runtime_subagent_type_matches_role_declaration(self) -> None:
        for phase, expected in self.EXPECTED.items():
            self.assertEqual(expected, agent_roles.phase_runtime_subagent_type(phase), phase)

    def test_phase_runtime_subagent_type_unknown_is_empty(self) -> None:
        self.assertEqual("", agent_roles.phase_runtime_subagent_type("nonexistent"))


class RoleToPhaseTest(unittest.TestCase):
    EXPECTED = {
        "requirements-clarifier": "clarify",
        "use-case-designer": "design",
        "implementation-planner": "plan",
        "test-case-developer": "tdd-red",
        "code-developer": "implement",
        "coverage-reviewer": "completion",
        # semantic-reviewer owns r1/r2/r3; canonical = lowest-order phase it owns.
        "semantic-reviewer": "r1-review",
        "": "",
        "totally-unknown": "",
    }

    def test_role_to_phase(self) -> None:
        for role, phase in self.EXPECTED.items():
            self.assertEqual(phase, agent_roles.role_to_phase(role), role)


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

    def test_roles_declare_runtime_subagent_type(self) -> None:
        for key in CANONICAL_KEYS:
            self.assertEqual(key, agent_roles.ROLE_REGISTRY[key]["runtime_subagent_type"], key)


class RoleAssetLoadingTest(unittest.TestCase):
    """Default role/team declarations live in files, with Python as facade."""

    def test_default_role_assets_back_registry(self) -> None:
        assets = agent_roles.role_asset_paths()
        self.assertEqual(CANONICAL_KEYS, set(assets))
        for key, path in assets.items():
            self.assertTrue(path.exists(), key)

        loaded = agent_roles.load_role_registry()

        self.assertEqual(CANONICAL_KEYS, set(loaded))
        self.assertEqual(agent_roles.ROLE_REGISTRY, loaded)

    def test_team_registry_defines_bootstrap_and_multi_service_presets(self) -> None:
        self.assertIn("bootstrap", agent_roles.TEAM_REGISTRY)
        self.assertIn("multi-service", agent_roles.TEAM_REGISTRY)

        bootstrap = agent_roles.TEAM_REGISTRY["bootstrap"]
        self.assertEqual(["requirements-clarifier"], bootstrap["roles"])
        self.assertEqual("dispatcher-confirmed", bootstrap["completion_mode"])

        multi = agent_roles.TEAM_REGISTRY["multi-service"]
        self.assertEqual("multi", multi["agent_mode"])
        self.assertEqual(CANONICAL_KEYS, set(multi["roles"]))
        self.assertEqual("dispatcher-confirmed", multi["completion_mode"])


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
        "code-developer-notification-test",
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
