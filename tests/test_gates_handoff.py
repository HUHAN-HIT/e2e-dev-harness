"""Handoff gate: phase-transition readiness."""
from __future__ import annotations

import sys
import hashlib
import json
import tempfile
import textwrap
import unittest

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import handoff_gate  # noqa: E402
import e2e_dev_harness  # noqa: E402


class HandoffGateTests(unittest.TestCase):
    def write_ready_marker(
        self,
        handoff: Path,
        producer_agent: str = "developer-agent-1",
        status: str = "ready",
        sha256: str | None = None,
    ) -> None:
        marker = handoff.with_suffix(".ready.json")
        marker.write_text(
            json.dumps(
                {
                    "path": str(handoff.name),
                    "sha256": sha256 or hashlib.sha256(handoff.read_bytes()).hexdigest(),
                    "producer_agent": producer_agent,
                    "status": status,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def test_handoff_gate_blocks_draft_template_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            (handoff_dir / "04-code-developer.md").write_text(
                e2e_dev_harness.handoff_text("code-developer"),
                encoding="utf-8",
            )

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("draft" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertTrue(any("agent id" in reason.lower() for reason in result["blocked_reasons"]))

    def test_handoff_gate_blocks_partial_file_before_downstream_consumption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            (handoff_dir / "04-code-developer.md.partial").write_text("half written", encoding="utf-8")

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("partial" in reason.lower() for reason in result["blocked_reasons"]))

    def test_handoff_gate_can_require_non_empty_handoff_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)

            result = handoff_gate.validate(repo, [handoff_dir], require_files=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("handoff artifacts are missing" in reason.lower() for reason in result["blocked_reasons"]))

    def test_handoff_gate_allows_ready_handoff_with_hashes_and_no_open_questions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("Implementation manifest evidence.\n", encoding="utf-8")
            evidence_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
            handoff = handoff_dir / "04-code-developer.md"
            handoff.write_text(
                textwrap.dedent(
                    f"""
                    ---
                    agent: code-developer
                    agent_id: developer-agent-1
                    status: ready
                    inputs:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md
                    outputs:
                      - docs/agent-runs/run/evidence/implementation-manifest.md
                    input_hashes:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/implementation-manifest.md sha256:{evidence_hash}
                    blocked_by: []
                    consumed_by:
                      - coverage-reviewer
                    open_questions: None
                    service_scope: services/order-service
                    memory_updates_proposed: []
                    ---

                    # Agent Handoff

                    ## Summary

                    Implemented order-service refund flow.

                    ## Facts Used

                    Consumed the test handoff and service plan.

                    ## Decisions Made

                    Reused the existing service-layer pattern.

                    ## Open Questions

                    None

                    ## Downstream Assumptions

                    Coverage reviewer may rely on the implementation manifest.

                    ## Verification Evidence

                    mvn -pl services/order-service -am test passed.
                    """
                ).strip(),
                encoding="utf-8",
            )
            self.write_ready_marker(handoff)

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(1, len(result["items"]))

    def test_handoff_gate_blocks_self_referential_output_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            handoff = handoff_dir / "04-code-developer.md"
            handoff.write_text(
                textwrap.dedent(
                    """
                    ---
                    agent: code-developer
                    agent_id: developer-agent-1
                    status: ready
                    inputs:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md
                    outputs:
                      - docs/agent-runs/run/handoffs/04-code-developer.md
                    input_hashes:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/handoffs/04-code-developer.md sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                    consumed_by:
                      - coverage-reviewer
                    open_questions: None
                    ---

                    # Agent Handoff

                    ## Summary

                    Implemented order-service refund flow.

                    ## Facts Used

                    Consumed the test handoff and service plan.

                    ## Decisions Made

                    Reused the existing service-layer pattern.

                    ## Open Questions

                    None

                    ## Downstream Assumptions

                    Coverage reviewer may rely on the implementation manifest.

                    ## Verification Evidence

                    mvn -pl services/order-service -am test passed.
                    """
                ).strip(),
                encoding="utf-8",
            )
            self.write_ready_marker(handoff)

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("self-referential" in reason.lower() for reason in result["blocked_reasons"]))

    def test_handoff_gate_blocks_ready_handoff_with_empty_body_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            handoff = handoff_dir / "04-code-developer.md"
            handoff.write_text(
                textwrap.dedent(
                    """
                    ---
                    agent: code-developer
                    agent_id: developer-agent-1
                    status: ready
                    inputs:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md
                    outputs:
                      - docs/agent-runs/run/evidence/implementation-manifest.md
                    input_hashes:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/implementation-manifest.md sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                    consumed_by:
                      - coverage-reviewer
                    open_questions: None
                    ---

                    # Agent Handoff

                    ## Summary

                    ## Facts Used

                    ## Decisions Made

                    ## Open Questions

                    None

                    ## Downstream Assumptions

                    ## Verification Evidence
                    """
                ).strip(),
                encoding="utf-8",
            )
            self.write_ready_marker(handoff)

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("Summary" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("Verification Evidence" in reason for reason in result["blocked_reasons"]))

    def test_handoff_gate_blocks_missing_ready_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            handoff = handoff_dir / "04-code-developer.md"
            handoff.write_text(
                textwrap.dedent(
                    """
                    ---
                    agent: code-developer
                    agent_id: developer-agent-1
                    status: ready
                    inputs:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md
                    outputs:
                      - docs/agent-runs/run/evidence/implementation-manifest.md
                    input_hashes:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/implementation-manifest.md sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                    consumed_by:
                      - coverage-reviewer
                    open_questions: None
                    ---

                    # Agent Handoff

                    ## Open Questions

                    None
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("ready marker" in reason.lower() for reason in result["blocked_reasons"]))

    def test_handoff_gate_blocks_stale_ready_marker_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            handoff = handoff_dir / "04-code-developer.md"
            handoff.write_text(
                textwrap.dedent(
                    """
                    ---
                    agent: code-developer
                    agent_id: developer-agent-1
                    status: ready
                    inputs:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md
                    outputs:
                      - docs/agent-runs/run/evidence/implementation-manifest.md
                    input_hashes:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/implementation-manifest.md sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                    consumed_by:
                      - coverage-reviewer
                    open_questions: None
                    ---

                    # Agent Handoff

                    ## Open Questions

                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            self.write_ready_marker(handoff, sha256="0" * 64)

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("sha256" in reason.lower() for reason in result["blocked_reasons"]))

    def test_handoff_gate_blocks_ready_marker_path_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            handoff_dir.mkdir(parents=True)
            handoff = handoff_dir / "04-code-developer.md"
            handoff.write_text(
                textwrap.dedent(
                    """
                    ---
                    agent: code-developer
                    agent_id: developer-agent-1
                    status: ready
                    inputs:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md
                    outputs:
                      - docs/agent-runs/run/evidence/implementation-manifest.md
                    input_hashes:
                      - docs/agent-runs/run/handoffs/03-test-case-developer.md sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/implementation-manifest.md sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                    consumed_by:
                      - coverage-reviewer
                    open_questions: None
                    ---

                    # Agent Handoff

                    ## Open Questions

                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            marker = handoff.with_suffix(".ready.json")
            marker.write_text(
                json.dumps(
                    {
                        "path": "other.md",
                        "sha256": hashlib.sha256(handoff.read_bytes()).hexdigest(),
                        "producer_agent": "developer-agent-1",
                        "status": "ready",
                    }
                ),
                encoding="utf-8",
            )

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("path" in reason.lower() for reason in result["blocked_reasons"]))

    def test_handoff_gate_blocks_output_hash_mismatch_against_current_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "impact-summary.md"
            handoff_dir.mkdir(parents=True)
            evidence.parent.mkdir(parents=True)
            evidence.write_text("current impact evidence\n", encoding="utf-8")
            handoff = handoff_dir / "01-requirements-clarifier.md"
            handoff.write_text(
                textwrap.dedent(
                    """
                    ---
                    agent: requirements-clarifier
                    agent_id: requirements-agent-1
                    status: ready
                    inputs:
                      - user request
                    outputs:
                      - docs/agent-runs/run/evidence/impact-summary.md
                    input_hashes:
                      - user-request sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/impact-summary.md sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
                    consumed_by:
                      - implementation-planner
                    open_questions: None
                    ---

                    ## Summary
                    Requirements are clarified.

                    ## Facts Used
                    The design document was inspected.

                    ## Decisions Made
                    Downstream agents may proceed.

                    ## Open Questions
                    None

                    ## Downstream Assumptions
                    Workers consume evidence files.

                    ## Verification Evidence
                    Evidence hashes are declared in frontmatter.
                    """
                ).strip(),
                encoding="utf-8",
            )
            self.write_ready_marker(handoff, producer_agent="requirements-agent-1")

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("output_hashes" in reason and "does not match" in reason for reason in result["blocked_reasons"]))

    def test_handoff_gate_blocks_duplicate_ready_marker_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff_dir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "requirements-summary.md"
            handoff_dir.mkdir(parents=True)
            evidence.parent.mkdir(parents=True)
            evidence.write_text("requirements evidence\n", encoding="utf-8")
            evidence_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
            handoff = handoff_dir / "01-requirements-clarifier.md"
            handoff.write_text(
                textwrap.dedent(
                    f"""
                    ---
                    agent: requirements-clarifier
                    agent_id: requirements-agent-1
                    status: ready
                    inputs:
                      - user request
                    outputs:
                      - docs/agent-runs/run/evidence/requirements-summary.md
                    input_hashes:
                      - user-request sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/requirements-summary.md sha256:{evidence_hash}
                    consumed_by:
                      - implementation-planner
                    open_questions: None
                    ---

                    ## Summary
                    Requirements are clarified.

                    ## Facts Used
                    The design document was inspected.

                    ## Decisions Made
                    Downstream agents may proceed.

                    ## Open Questions
                    None

                    ## Downstream Assumptions
                    Workers consume evidence files.

                    ## Verification Evidence
                    Evidence hashes are declared in frontmatter.
                    """
                ).strip(),
                encoding="utf-8",
            )
            self.write_ready_marker(handoff, producer_agent="requirements-agent-1")
            duplicate = handoff.with_name(handoff.name + ".ready.json")
            duplicate.write_text(
                json.dumps(
                    {
                        "path": handoff.name,
                        "sha256": hashlib.sha256(handoff.read_bytes()).hexdigest(),
                        "producer_agent": "requirements-agent-1",
                        "status": "ready",
                    }
                ),
                encoding="utf-8",
            )

            result = handoff_gate.validate(repo, [handoff_dir])

        self.assertFalse(result["ready"])
        self.assertTrue(any("duplicate ready marker" in reason.lower() for reason in result["blocked_reasons"]))




if __name__ == "__main__":
    unittest.main()
