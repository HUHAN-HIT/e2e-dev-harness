"""Memory capture and safety tests."""
from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_capture  # noqa: E402
import e2e_dev_harness  # noqa: E402


class MemoryCaptureTests(unittest.TestCase):
    def test_validate_blocks_local_paths_and_duplicate_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            (repo / "memory" / "graph-findings.md").write_text(
                textwrap.dedent(
                    """
                    # Graph Findings Memory

                    ## Entries

                    ### M-1

                    - Type: graph-finding
                    - Source: graphify
                    - Confidence: verified
                    - Text: Duplicate fact.

                    ### M-2

                    - Type: graph-finding
                    - Source: graphify
                    - Confidence: verified
                    - Text: Duplicate fact.
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = memory_capture.validate_memory(repo)

        self.assertFalse(result["ready"])
        joined = "\n".join(result["blocked_reasons"]).lower()
        self.assertIn("duplicate", joined)

    def test_validate_blocks_dirty_memory_text_outside_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            project = repo / "memory" / "project.md"
            project.write_text(
                "# Project Memory\n\n## Notes\n\nUse local tool at D:\\tools\\secret with api_key=abc123.\n",
                encoding="utf-8",
            )

            result = memory_capture.validate_memory(repo)

        joined = "\n".join(result["blocked_reasons"]).lower()
        self.assertFalse(result["ready"])
        self.assertIn("local path", joined)
        self.assertIn("secret", joined)

    def test_append_memory_blocks_existing_duplicate_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            first = memory_capture.append_memory(repo, "decision", "design", "verified", "Quote timeout is 3 seconds.")
            second = memory_capture.append_memory(repo, "decision", "design", "verified", "Quote timeout is 3 seconds.")

        self.assertIsNotNone(first["path"])
        self.assertIsNone(second["path"])
        self.assertTrue(any("duplicate" in reason.lower() for reason in second["blocked_reasons"]))

    def test_select_filters_by_phase_and_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            service_boundaries = repo / "memory" / "service-boundaries.md"
            service_boundaries.write_text(
                textwrap.dedent(
                    """
                    # Service Boundaries Memory

                    ## Entries

                    - services/order-service owns order quotes.
                    - services/payment-service owns payment capture.
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = memory_capture.select_memory(repo, "code", "services/order-service")

        snippets = "\n".join(item["text"] for item in result["snippets"])
        self.assertIn("order-service", snippets)
        self.assertNotIn("payment-service", snippets)
        self.assertIn("memory/service-boundaries.md", result["files"])

    def test_select_filters_entries_by_obsidian_service_tags_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "services" / "order-service" / "src").mkdir(parents=True)
            (repo / "services" / "payment-service" / "src").mkdir(parents=True)
            memory_capture.init_memory(repo)
            decisions = repo / "memory" / "decisions.md"
            decisions.write_text(
                textwrap.dedent(
                    """
                    # Decisions Memory

                    ## Entries

                    ### M-1

                    - Type: decision
                    - Source: design
                    - Confidence: verified
                    - Tags: #decision #service/order-service #phase/code
                    - Links: [[services/order-service]] [[AC-1]]
                    - Text: Order service owns quote timeout behavior.

                    ### M-2

                    - Type: decision
                    - Source: design
                    - Confidence: verified
                    - Tags: #decision #service/payment-service #phase/code
                    - Links: [[services/payment-service]] [[AC-2]]
                    - Text: Payment service owns capture retries.
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = memory_capture.select_memory(repo, "code", "services/order-service")

        snippets = "\n".join(item["text"] for item in result["snippets"])
        self.assertIn("#service/order-service", snippets)
        self.assertIn("[[services/order-service]]", snippets)
        self.assertIn("quote timeout", snippets)
        self.assertNotIn("payment-service", snippets)
        self.assertNotIn("capture retries", snippets)

    def test_validate_blocks_invalid_obsidian_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            decisions = repo / "memory" / "decisions.md"
            decisions.write_text(
                textwrap.dedent(
                    """
                    # Decisions Memory

                    ## Entries

                    ### M-1

                    - Type: decision
                    - Source: design
                    - Confidence: verified
                    - Tags: #Service/Order_Service
                    - Text: Order service owns quote timeout behavior.
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = memory_capture.validate_memory(repo)

        self.assertFalse(result["ready"])
        self.assertTrue(any("tag" in reason.lower() for reason in result["blocked_reasons"]))

    def test_validate_blocks_unsafe_obsidian_link(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Links: [[https://example.com/project]]
            - Text: External project page is relevant.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("link" in reason.lower() for reason in result["blocked_reasons"]))

    def test_promote_preserves_obsidian_tags_and_links(self) -> None:
        proposed = textwrap.dedent(
            """
            # Proposed Memory Updates

            ### M-1

            - Type: decision
            - Source: user-approved
            - Confidence: approved
            - Status: accepted
            - Tags: #decision #service/sample-service #phase/code
            - Links: [[services/sample-service]] [[AC-1]]
            - Text: Sample service owns quote calculation.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "services" / "sample-service" / "src").mkdir(parents=True)
            memory_capture.init_memory(repo)
            proposed_path = repo / "docs" / "agent-runs" / "run" / "proposed-memory-updates.md"
            proposed_path.parent.mkdir(parents=True)
            proposed_path.write_text(proposed, encoding="utf-8")

            result = memory_capture.promote_memory_updates(repo, proposed_path)

            decisions = (repo / "memory" / "decisions.md").read_text(encoding="utf-8")

        self.assertEqual(1, result["promoted_count"])
        self.assertIn("- Tags: #decision #service/sample-service #phase/code", decisions)
        self.assertIn("- Links: [[services/sample-service]] [[AC-1]]", decisions)

    def test_promote_imports_only_accepted_entries(self) -> None:
        proposed = textwrap.dedent(
            """
            # Proposed Memory Updates

            ### M-1

            - Type: decision
            - Source: user-approved
            - Confidence: approved
            - Status: accepted
            - Text: Use direct Spring Framework 6 configuration.

            ### M-2

            - Type: workflow-preference
            - Source: design
            - Confidence: observed
            - Status: rejected
            - Text: Skip TDD for small changes.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            proposed_path = repo / "docs" / "agent-runs" / "run" / "proposed-memory-updates.md"
            proposed_path.parent.mkdir(parents=True)
            proposed_path.write_text(proposed, encoding="utf-8")

            result = memory_capture.promote_memory_updates(repo, proposed_path)

            decisions = (repo / "memory" / "decisions.md").read_text(encoding="utf-8")
            workflow = (repo / "memory" / "workflow-preferences.md").read_text(encoding="utf-8")

        self.assertEqual(1, result["promoted_count"])
        self.assertIn("Spring Framework 6", decisions)
        self.assertNotIn("Skip TDD", workflow)




class MemorySafetyTests(unittest.TestCase):
    def test_validate_proposed_updates_blocks_local_path(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Use tool at C:\\Users\\person\\secret.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("local path" in r.lower() for r in result["blocked_reasons"]))

    def test_validate_proposed_updates_blocks_secret(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Use api_key=sk-123456 for external service.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("secret" in r.lower() for r in result["blocked_reasons"]))

    def test_validate_proposed_updates_blocks_todo(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: TODO confirm timeout value.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("todo" in r.lower() or "tbd" in r.lower() for r in result["blocked_reasons"]))

    def test_validate_proposed_updates_blocks_exact_duplicate(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Quote timeout is 3 seconds.

            ### M-2

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Quote timeout is 3 seconds.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("duplicate" in r.lower() for r in result["blocked_reasons"]))

    def test_validate_proposed_updates_blocks_existing_memory_duplicate(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Quote timeout is 3 seconds.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)
            memory_capture.append_memory(repo, "decision", "user-approved", "approved", "Quote timeout is 3 seconds.")
            path = repo / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path, repo)

        self.assertFalse(result["ready"])
        self.assertTrue(any("already exists" in r.lower() for r in result["blocked_reasons"]))

    def test_validate_proposed_updates_warns_on_fuzzy_duplicate(self) -> None:
        proposed = textwrap.dedent(
            """
            ### M-1

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Quote timeout remains three seconds for all services.

            ### M-2

            - Type: decision
            - Source: design
            - Confidence: verified
            - Status: accepted
            - Text: Quote timeout remains three seconds for all the services.
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposed.md"
            path.write_text(proposed, encoding="utf-8")

            result = memory_capture.validate_proposed_updates(path)

        self.assertTrue(any("similar" in w.lower() for w in result["warnings"]))

    def test_append_memory_blocks_dirty_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)

            result = memory_capture.append_memory(
                repo, "decision", "user-approved", "approved",
                "Use secret at C:\\Users\\admin\\config with api_key=abc123",
            )

        self.assertIsNone(result["path"])
        self.assertTrue(len(result["blocked_reasons"]) > 0)

    def test_memory_status_strict_calls_validate_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            memory_capture.init_memory(repo)

            result = e2e_dev_harness.memory_status(repo, "strict")

        self.assertTrue(result["enabled"])
        self.assertIn("blocked_reasons", result)
        self.assertEqual("strict", result["mode"])




if __name__ == "__main__":
    unittest.main()
