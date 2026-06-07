"""Skill documentation and superpowers-probe compatibility."""
from __future__ import annotations

import sys
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import superpowers_probe  # noqa: E402
import reviewer_gate  # noqa: E402


class SkillDocumentationTests(unittest.TestCase):
    def test_skill_files_do_not_use_utf8_bom(self) -> None:
        skill_dir = ROOT / "skills" / "e2e-dev-harness"
        offenders = [
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in skill_dir.rglob("*")
            if path.is_file() and path.read_bytes().startswith(b"\xef\xbb\xbf")
        ]

        self.assertEqual([], offenders)

    def test_skill_points_non_codex_agents_to_platform_compatibility_reference(self) -> None:
        skill_text = (ROOT / "skills" / "e2e-dev-harness" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Claude Code", skill_text)
        self.assertIn("Codex", skill_text)
        self.assertIn("Gemini", skill_text)
        self.assertIn("references/platform-compatibility.md", skill_text)

    def test_skill_declares_custom_review_profile_reference(self) -> None:
        skill_text = (ROOT / "skills" / "e2e-dev-harness" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("references/review-profiles.md", skill_text)
        self.assertIn("common-review-issues.md", skill_text)
        self.assertIn("references/requirements-archive.md", skill_text)

    def test_requirements_archive_reference_documents_completion_summary(self) -> None:
        reference = ROOT / "skills" / "e2e-dev-harness" / "references" / "requirements-archive.md"
        text = reference.read_text(encoding="utf-8")

        self.assertIn("docs/agent-runs/<run>/requirements-archive.md", text)
        self.assertIn("Acceptance Criteria Status", text)
        self.assertIn("Promoted Memory Entries", text)
        self.assertIn("--requirements-archive", text)

    def test_review_profile_reference_documents_project_discovery_and_extends(self) -> None:
        reference = ROOT / "skills" / "e2e-dev-harness" / "references" / "review-profiles.md"
        text = reference.read_text(encoding="utf-8")

        self.assertIn(".e2e/review-profile.json", text)
        self.assertIn("docs/review-profile.json", text)
        self.assertIn("extends", text)
        self.assertIn("severity", text)
        self.assertIn("security-heavy", text)
        self.assertIn("api-first", text)

    def test_common_review_issues_reference_exists(self) -> None:
        reference = ROOT / "skills" / "e2e-dev-harness" / "references" / "common-review-issues.md"
        text = reference.read_text(encoding="utf-8")

        self.assertIn("Issue ID", text)
        self.assertIn("Criteria", text)
        self.assertIn("Examples", text)
        self.assertIn("code-path-trace-gap", text)
        self.assertIn("weak-completion-evidence", text)
        self.assertIn("impact-summary-overload", text)
        self.assertNotRegex(text, r"[\u4e00-\u9fff]")

    def test_readme_documents_hook_configuration(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Hook Configuration", text)
        self.assertIn("claude-code-settings.example.json", text)
        self.assertIn("codex-pre-action.example.json", text)
        self.assertIn("gemini-pre-action.example.json", text)
        self.assertIn("opencode-plugin.example.js", text)
        self.assertIn(".opencode/plugins", text)
        self.assertIn("phase_guard.py", text)
        self.assertIn(".phase-lock", text)
        self.assertIn("templates", text)

    def test_orchestration_reference_documents_l0_serial_isolated_dispatch(self) -> None:
        text = (ROOT / "skills" / "e2e-dev-harness" / "references" / "agent-orchestration.md").read_text(encoding="utf-8")

        self.assertIn("L0 Serial Isolated Dispatch", text)
        self.assertIn("fresh runtime context", text)
        self.assertIn("agent-task", text)
        self.assertIn("claim", text)
        self.assertIn("complete", text)

    def test_orchestration_docs_define_coordinator_context_budget_strategy(self) -> None:
        skill_text = (ROOT / "skills" / "e2e-dev-harness" / "SKILL.md").read_text(encoding="utf-8")
        orchestration = (ROOT / "skills" / "e2e-dev-harness" / "references" / "agent-orchestration.md").read_text(encoding="utf-8")
        execution_control = (ROOT / "skills" / "e2e-dev-harness" / "references" / "execution-control.md").read_text(encoding="utf-8")

        self.assertIn("Coordinator minimal reading set", skill_text)
        self.assertIn("keep full CLI JSON in evidence files", skill_text)
        self.assertIn("Coordinator write budget", skill_text)
        self.assertIn("command-evidence", skill_text)
        self.assertIn("Coordinator Context Budget", orchestration)
        self.assertIn("Coordinator write actions are budgeted too", orchestration)
        self.assertIn("High-output shell commands are blocked", orchestration)
        self.assertIn("coordinator-tool-events", orchestration)
        self.assertIn("Coordinator write budget warning", orchestration)
        self.assertIn("coordinator context handoff point", orchestration)
        self.assertIn("session-checkpoint.json", orchestration)
        self.assertIn("coordinator_context_budget.handoff_recommended", orchestration)
        self.assertIn("bytes under `evidence/`", orchestration)
        self.assertIn("coordinator context handoff point", execution_control)
        self.assertIn("WAITING_DISPATCH", execution_control)

    def test_clarification_docs_require_user_confirmation_provenance(self) -> None:
        skill_text = (ROOT / "skills" / "e2e-dev-harness" / "SKILL.md").read_text(encoding="utf-8")
        clarification = (ROOT / "skills" / "e2e-dev-harness" / "references" / "clarification-gate.md").read_text(encoding="utf-8")

        self.assertIn("user confirmation provenance", skill_text)
        self.assertIn("confirmed-by: user", clarification)
        self.assertIn("--no-require-user-confirmation", clarification)
        self.assertIn("Do not mark Open Questions as `None`", clarification)

    def test_github_actions_harness_is_windows_first(self) -> None:
        text = (ROOT / "skills" / "e2e-dev-harness" / "ci" / "github-actions-harness.yml").read_text(encoding="utf-8")

        self.assertIn("runs-on: windows-latest", text)
        self.assertIn("shell: pwsh", text)
        self.assertNotIn("ubuntu-latest", text)

    def test_bundled_review_profiles_have_guidance_metadata(self) -> None:
        for name in ("default", "security-heavy", "api-first"):
            with self.subTest(profile=name):
                profile, blocked, path, source, chain = reviewer_gate.load_review_profile(ROOT, name)

                self.assertEqual([], blocked)
                self.assertTrue(path and path.replace("\\", "/").endswith(f"{name}.json"))
                self.assertEqual("explicit", source)
                self.assertTrue(chain)
                for phase, items in profile["required_checklist"].items():
                    self.assertTrue(items, phase)
                    for item in items:
                        self.assertIn("description", item)
                        self.assertIn("severity", item)
                        self.assertIn("references", item)

    def test_tdd_reference_documents_audit_field_template(self) -> None:
        text = (ROOT / "skills" / "e2e-dev-harness" / "references" / "tdd-java-spring.md").read_text(encoding="utf-8")

        self.assertIn("createdAt", text)
        self.assertIn("updatedAt", text)
        self.assertIn("createdBy", text)

    def test_skill_body_is_concise_for_progressive_disclosure(self) -> None:
        skill_text = (ROOT / "skills" / "e2e-dev-harness" / "SKILL.md").read_text(encoding="utf-8")
        body = skill_text.split("---", 2)[-1]
        words = body.split()
        long_lines = [
            line
            for line in body.splitlines()
            if len(line) > 240 and not line.startswith("description:")
        ]

        self.assertLessEqual(len(words), 2200)
        self.assertEqual([], long_lines)

    def test_compacted_skill_keeps_hard_gate_navigation(self) -> None:
        skill_text = (ROOT / "skills" / "e2e-dev-harness" / "SKILL.md").read_text(encoding="utf-8")

        required_terms = [
            "Superpowers",
            "GitNexus",
            "Graphify",
            "R1/R2/R3",
            "Coverage Reviewer",
            "single-review",
            "rework",
            "memory",
            "agent-instructions.md",
            "agent-orchestration.md",
            "implementation-gates.md",
            "kg-tool-selection.md",
            "memory-integration.md",
            "tdd-java-spring.md",
        ]

        for term in required_terms:
            with self.subTest(term=term):
                self.assertIn(term, skill_text)




class SuperpowersProbeCompatibilityTests(unittest.TestCase):
    def test_discovers_superpowers_in_claude_code_skills_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            skills = home / ".claude" / "skills"
            for name in (
                "using-superpowers",
                "brainstorming",
                "writing-plans",
                "test-driven-development",
            ):
                path = skills / name / "SKILL.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"---\nname: {name}\ndescription: test\n---\n", encoding="utf-8")

            with (
                patch.dict(superpowers_probe.os.environ, {"SUPERPOWERS_SKILLS_DIR": "", "SUPERPOWERS_ROOT": ""}, clear=False),
                patch.object(superpowers_probe.Path, "home", return_value=home),
            ):
                result = superpowers_probe.discover()

        self.assertTrue(result["available"], result)
        self.assertTrue(any(".claude" in path.replace("\\", "/") for path in result["found"].values()))




if __name__ == "__main__":
    unittest.main()
