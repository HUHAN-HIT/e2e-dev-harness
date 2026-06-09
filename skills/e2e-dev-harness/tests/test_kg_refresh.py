"""Knowledge-graph refresh and probe integration."""
from __future__ import annotations

import sys
import json
import subprocess
import tempfile
import textwrap
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "e2e_harness" / "adapters" / "kg" / "_legacy"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kg_refresh  # noqa: E402


class KnowledgeGraphRefreshTests(unittest.TestCase):
    def test_detect_finds_maven_service_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "pom.xml").write_text(
                textwrap.dedent(
                    """
                    <project xmlns="http://maven.apache.org/POM/4.0.0">
                      <modelVersion>4.0.0</modelVersion>
                      <modules>
                        <module>services/order-service</module>
                      </modules>
                    </project>
                    """
                ).strip(),
                encoding="utf-8",
            )
            service = repo / "services" / "order-service"
            (service / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
            (service / "pom.xml").write_text("<project />", encoding="utf-8")
            (service / "src" / "main" / "java" / "com" / "example" / "AppConfig.java").write_text(
                "@Configuration\npublic class AppConfig {}\n",
                encoding="utf-8",
            )

            result = kg_refresh.detect(repo)

        self.assertEqual(["services/order-service"], result["service_candidates"])
        self.assertIn("gitnexus", kg_refresh.choose_tools("auto", result))

    def test_detect_gitnexus_index_reports_freshness_and_fts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            kg_refresh.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="def456\n", stderr=""),
        ):
            repo = Path(tmp)
            meta = repo / ".gitnexus" / "meta.json"
            meta.parent.mkdir(parents=True)
            meta.write_text(
                json.dumps(
                    {
                        "repoPath": str(repo),
                        "lastCommit": "abc123",
                        "indexedAt": "2026-06-04T17:17:52.858Z",
                        "stats": {"files": 9, "nodes": 12, "edges": 34, "processes": 5},
                        "capabilities": {
                            "graph": {"status": "available"},
                            "fts": {"status": "available"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = kg_refresh.detect_gitnexus_index(repo)

        self.assertEqual("abc123", result["last_commit"])
        self.assertEqual("def456", result["current_head"])
        self.assertTrue(result["is_stale"])
        self.assertEqual(9, result["files"])
        self.assertEqual("available", result["fts_status"])
        self.assertEqual("gitnexus analyze .", result["recommended_refresh_command"])

    def test_run_command_rejects_shell_control_operators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = kg_refresh.run_command("graphify update . && echo unsafe", Path(tmp))

        self.assertEqual(2, result["exit_code"])
        self.assertIn("Shell control operators", result["stderr_tail"])

    def test_run_command_reports_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            kg_refresh.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["gitnexus", "analyze", "."], 600, output="partial"),
        ):
            result = kg_refresh.run_command("gitnexus analyze .", Path(tmp))

        self.assertEqual(124, result["exit_code"])
        self.assertIn("timed out", result["stderr_tail"])




if __name__ == "__main__":
    unittest.main()
