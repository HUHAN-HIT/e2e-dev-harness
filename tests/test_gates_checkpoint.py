"""Checkpoint gate: phase completion verification."""
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

import checkpoint_gate  # noqa: E402


class CheckpointGateTests(unittest.TestCase):
    def test_checkpoint_gate_blocks_missing_required_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = checkpoint_gate.validate(repo, None, ["clarify"], "required")

        self.assertFalse(result["ready"])
        self.assertTrue(any("clarify" in reason for reason in result["blocked_reasons"]))

    def test_checkpoint_gate_accepts_approved_markdown_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            confirmation = repo / "docs" / "agent-runs" / "run" / "confirmations" / "clarify.md"
            confirmation.parent.mkdir(parents=True)
            confirmation.write_text(
                textwrap.dedent(
                    """
                    # Clarify Confirmation

                    - Phase: clarify
                    - Status: approved
                    - Confirmed By: user
                    - Decision: continue
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = checkpoint_gate.validate(repo, [confirmation.parent], ["clarify"], "required")

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["clarify"], [item["phase"] for item in result["confirmations"]])

    def test_checkpoint_gate_advisory_downgrades_missing_confirmation_to_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = checkpoint_gate.validate(Path(tmp), None, ["clarify"], "advisory")

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(any("clarify" in warning for warning in result["warnings"]))




if __name__ == "__main__":
    unittest.main()
