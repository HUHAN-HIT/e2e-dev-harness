"""Agent instruction scoping and validation."""
from __future__ import annotations

import sys
import os
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_instructions  # noqa: E402
import memory_capture  # noqa: E402
import orchestration_plan  # noqa: E402
import superpowers_probe  # noqa: E402


class AgentInstructionScopeTests(unittest.TestCase):
    def test_harness_environment_variables_override_legacy_workflow_names(self) -> None:
        with patch.dict(
            os.environ,
            {
                "E2E_DEV_WORKFLOW_AGENT_INSTRUCTIONS_MODE": "off",
                "E2E_DEV_HARNESS_AGENT_INSTRUCTIONS_MODE": "strict",
                "E2E_DEV_WORKFLOW_AGENT_MODE": "single",
                "E2E_DEV_HARNESS_AGENT_MODE": "multi",
                "E2E_DEV_WORKFLOW_MEMORY_MODE": "off",
                "E2E_DEV_HARNESS_MEMORY_MODE": "auto",
                "E2E_DEV_WORKFLOW_SUPERPOWERS_MODE": "off",
                "E2E_DEV_HARNESS_SUPERPOWERS_MODE": "strict",
            },
            clear=False,
        ):
            self.assertEqual(
                "strict",
                agent_instructions.env_default(
                    "E2E_DEV_HARNESS_AGENT_INSTRUCTIONS_MODE",
                    "E2E_DEV_WORKFLOW_AGENT_INSTRUCTIONS_MODE",
                    "auto",
                ),
            )
            self.assertEqual("multi", orchestration_plan.env_default("E2E_DEV_HARNESS_AGENT_MODE", "E2E_DEV_WORKFLOW_AGENT_MODE", "auto"))
            self.assertEqual("auto", memory_capture.env_default("E2E_DEV_HARNESS_MEMORY_MODE", "E2E_DEV_WORKFLOW_MEMORY_MODE", "strict"))
            self.assertEqual("strict", superpowers_probe.env_default("E2E_DEV_HARNESS_SUPERPOWERS_MODE", "E2E_DEV_WORKFLOW_SUPERPOWERS_MODE", "auto"))

    def test_legacy_workflow_environment_variables_remain_supported(self) -> None:
        with patch.dict(os.environ, {"E2E_DEV_WORKFLOW_AGENT_MODE": "single-review"}, clear=False):
            os.environ.pop("E2E_DEV_HARNESS_AGENT_MODE", None)

            result = orchestration_plan.env_default("E2E_DEV_HARNESS_AGENT_MODE", "E2E_DEV_WORKFLOW_AGENT_MODE", "auto")

        self.assertEqual("single-review", result)

    def test_unknown_scope_loads_root_only_and_discovers_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "AGENT.md").write_text("# Root\n", encoding="utf-8")
            for service in ("a", "b", "c"):
                service_dir = repo / "services" / service
                (service_dir / "src").mkdir(parents=True)
                (service_dir / "AGENT.md").write_text(f"# Service {service}\n", encoding="utf-8")

            result = agent_instructions.scan(
                repo,
                include_content=True,
                max_chars=12000,
                paths=None,
                scope="auto",
            )

        self.assertEqual(["AGENT.md"], result["load_order"])
        self.assertEqual(["AGENT.md"], list(result["instruction_contents"]))
        self.assertEqual(
            ["services/a", "services/b", "services/c"],
            [item["service_dir"] for item in result["discovered_service_agent_files"]],
        )
        self.assertEqual([], result["service_agent_files"])
        self.assertEqual("discovery", result["resolved_scope"])

    def test_path_scoped_scan_loads_only_affected_service_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "AGENT.md").write_text("# Root\n", encoding="utf-8")
            for service in ("a", "b"):
                service_dir = repo / "services" / service
                (service_dir / "src").mkdir(parents=True)
                (service_dir / "AGENT.md").write_text(f"# Service {service}\n", encoding="utf-8")

            result = agent_instructions.scan(
                repo,
                include_content=False,
                max_chars=12000,
                paths=["services/a/src/Main.java"],
                scope="auto",
            )

        self.assertEqual(["AGENT.md", "services/a/AGENT.md"], result["load_order"])
        self.assertEqual(["services/a"], [item["service_dir"] for item in result["service_agent_files"]])
        self.assertEqual("affected", result["resolved_scope"])

    def test_all_scope_keeps_legacy_full_service_loading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "AGENT.md").write_text("# Root\n", encoding="utf-8")
            for service in ("a", "b"):
                service_dir = repo / "services" / service
                (service_dir / "src").mkdir(parents=True)
                (service_dir / "AGENT.md").write_text(f"# Service {service}\n", encoding="utf-8")

            result = agent_instructions.scan(
                repo,
                include_content=False,
                max_chars=12000,
                paths=None,
                scope="all",
            )

        self.assertEqual(["AGENT.md", "services/a/AGENT.md", "services/b/AGENT.md"], result["load_order"])
        self.assertEqual(["services/a", "services/b"], [item["service_dir"] for item in result["service_agent_files"]])
        self.assertEqual("all", result["resolved_scope"])

    def test_strict_affected_scope_blocks_unknown_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "AGENT.md").write_text("# Root\n", encoding="utf-8")
            service_dir = repo / "services" / "a"
            (service_dir / "src").mkdir(parents=True)
            (service_dir / "AGENT.md").write_text("# Service A\n", encoding="utf-8")

            result = agent_instructions.scan(
                repo,
                include_content=False,
                max_chars=12000,
                paths=None,
                scope="affected",
                services=["missing-service"],
            )

        self.assertEqual(["missing-service"], result["unresolved_requested_services"])
        self.assertIn("missing-service", result["missing"]["requested_services"])




if __name__ == "__main__":
    unittest.main()
