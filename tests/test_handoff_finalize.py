"""Handoff finalize command + unified task-state view (multi-file state hardening)."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import dispatcher  # noqa: E402
import handoff_gate  # noqa: E402
from e2e_harness.cli.commands import handoff as handoff_command  # noqa: E402


def _complete_handoff_text(out_rel: str, out_hash: str) -> str:
    return textwrap.dedent(
        f"""\
        ---
        agent: requirements-clarifier
        status: draft
        service_scope: all-services
        inputs:
          - user request
        outputs:
          - {out_rel}
        input_hashes:
          - user-request sha256:{'a' * 64}
        output_hashes:
          - {out_rel} sha256:{out_hash}
        consumed_by:
          - use-case-designer
        open_questions: None
        ---

        # Agent Handoff

        ## Summary

        The clarifier confirmed the refund-notify scope with the user and locked AC-1.

        ## Facts Used

        Project CLAUDE.md, the design doc, and the user confirmation in session.

        ## Decisions Made

        Scope limited to AutoHandleResultNotify; legacy diff topic unchanged.

        ## Downstream Assumptions

        Use-case design may rely on AC-1 publishing AutoHandleResultNotifyMQ.

        ## Verification Evidence

        {out_rel}

        ## Open Questions

        None
        """
    )


class HandoffFinalizeTests(unittest.TestCase):
    def test_incomplete_handoff_reports_blockers_and_rolls_back_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            hdir = repo / "docs" / "agent-runs" / "run" / "handoffs"
            hdir.mkdir(parents=True)
            handoff = hdir / "01-requirements-clarifier.md"
            handoff.write_text(
                "---\nagent: requirements-clarifier\nstatus: draft\n---\n\n# Agent Handoff\n",
                encoding="utf-8",
            )

            result = handoff_command.run_finalize(repo, handoff, "developer-agent-1")

            self.assertFalse(result["ready"])
            self.assertTrue(result.get("marker_rolled_back"))
            # No ready marker is left behind for an invalid handoff.
            self.assertFalse(handoff_gate.marker_path(handoff.resolve()).exists())
            # Blockers are specific, not a vague failure.
            self.assertTrue(any("non-empty" in r for r in result["blocked_reasons"]))

    def test_complete_handoff_writes_ready_marker_and_normalizes_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run = repo / "docs" / "agent-runs" / "run"
            (run / "handoffs").mkdir(parents=True)
            (run / "evidence").mkdir(parents=True)
            out = run / "evidence" / "impact-summary.md"
            out.write_text("# Impact Summary\n\nReal content.\n", encoding="utf-8")
            out_rel = "docs/agent-runs/run/evidence/impact-summary.md"
            out_hash = hashlib.sha256(out.read_bytes()).hexdigest()
            handoff = run / "handoffs" / "01-requirements-clarifier.md"
            handoff.write_text(_complete_handoff_text(out_rel, out_hash), encoding="utf-8")

            result = handoff_command.run_finalize(repo, handoff, "developer-agent-1")

            self.assertTrue(result["ready"], result["blocked_reasons"])
            marker = handoff_gate.marker_path(handoff.resolve())
            self.assertTrue(marker.exists())
            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(payload["sha256"], hashlib.sha256(handoff.read_bytes()).hexdigest())
            self.assertEqual(payload["producer_agent"], "developer-agent-1")
            text = handoff.read_text(encoding="utf-8")
            self.assertIn("status: ready", text)
            self.assertIn("agent_id: developer-agent-1", text)
            # Idempotent: a second finalize stays ready.
            again = handoff_command.run_finalize(repo, handoff, "developer-agent-1")
            self.assertTrue(again["ready"], again["blocked_reasons"])

    def test_closed_open_questions_section_is_normalized_to_literal_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run = repo / "docs" / "agent-runs" / "run"
            (run / "handoffs").mkdir(parents=True)
            (run / "evidence").mkdir(parents=True)
            out = run / "evidence" / "impact-summary.md"
            out.write_text("# Impact Summary\n\nReal content.\n", encoding="utf-8")
            out_rel = "docs/agent-runs/run/evidence/impact-summary.md"
            out_hash = hashlib.sha256(out.read_bytes()).hexdigest()
            handoff = run / "handoffs" / "01-requirements-clarifier.md"
            handoff.write_text(
                _complete_handoff_text(out_rel, out_hash).replace(
                    "## Open Questions\n\nNone\n",
                    "## Open Questions\n\nNo open questions remain; the user's earlier concern is resolved.\n",
                ),
                encoding="utf-8",
            )

            result = handoff_command.run_finalize(repo, handoff, "developer-agent-1")

            self.assertTrue(result["ready"], result["blocked_reasons"])
            text = handoff.read_text(encoding="utf-8")
            self.assertIn("## Open Questions\n\nNone\n", text)
            self.assertNotIn("earlier concern", text)

    def test_semantic_body_gap_is_not_repaired_and_marker_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run = repo / "docs" / "agent-runs" / "run"
            (run / "handoffs").mkdir(parents=True)
            (run / "evidence").mkdir(parents=True)
            out = run / "evidence" / "impact-summary.md"
            out.write_text("# Impact Summary\n\nReal content.\n", encoding="utf-8")
            out_rel = "docs/agent-runs/run/evidence/impact-summary.md"
            out_hash = hashlib.sha256(out.read_bytes()).hexdigest()
            handoff = run / "handoffs" / "01-requirements-clarifier.md"
            handoff.write_text(
                _complete_handoff_text(out_rel, out_hash).replace(
                    "The clarifier confirmed the refund-notify scope with the user and locked AC-1.",
                    "TODO",
                ),
                encoding="utf-8",
            )

            result = handoff_command.run_finalize(repo, handoff, "developer-agent-1")

            self.assertFalse(result["ready"])
            self.assertTrue(result.get("marker_rolled_back"))
            self.assertFalse(handoff_gate.marker_path(handoff.resolve()).exists())
            self.assertTrue(any("ready body section" in item for item in result["blocked_reasons"]))


class TaskStateViewTests(unittest.TestCase):
    def test_view_merges_three_status_namespaces_and_suggests_finalize(self) -> None:
        repo = Path(".").resolve()
        state = {
            "lifecycle": "CREATED",
            "dispatches": {
                "T01": {
                    "current_task_id": "T01",
                    "current_agent": "requirements-clarifier",
                    "status": "worker_running",
                    "worker_handle": "h1",
                }
            },
        }
        open_tasks = [
            {
                "id": "T01",
                "agent": "requirements-clarifier",
                "phase": "clarify",
                "status": "claimed",
                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
            }
        ]

        views = dispatcher.build_task_state_views(repo, None, state, open_tasks, [], [])

        self.assertEqual(len(views), 1)
        view = views[0]
        self.assertEqual(view["lifecycle"], "CREATED")
        self.assertEqual(view["task_status"], "claimed")
        self.assertEqual(view["dispatch_status"], "worker_running")
        self.assertIn("handoff --path", view["next_command"])


if __name__ == "__main__":
    unittest.main()
