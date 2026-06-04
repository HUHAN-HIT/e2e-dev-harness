from __future__ import annotations

import argparse
import sys
import unittest

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class CliParserTests(unittest.TestCase):
    def test_prepare_args_accept_discovery_and_dependency_options(self) -> None:
        from e2e_harness.cli.parser import add_prepare_args  # noqa: PLC0415

        parser = argparse.ArgumentParser()
        add_prepare_args(parser)

        args = parser.parse_args(
            [
                "repo-root",
                "--design-doc",
                "docs/design.md",
                "--path",
                "skills/e2e-dev-harness",
                "--service",
                "harness",
                "--workflow-tier",
                "auto",
                "--dependency-scan-mode",
                "strict",
                "--no-write-dependency-report",
            ]
        )

        self.assertEqual(Path("repo-root"), args.repo)
        self.assertEqual(Path("docs/design.md"), args.design_doc)
        self.assertEqual(["skills/e2e-dev-harness"], args.path)
        self.assertEqual(["harness"], args.service)
        self.assertEqual("auto", args.workflow_tier)
        self.assertEqual("strict", args.dependency_scan_mode)
        self.assertFalse(args.write_dependency_report)

    def test_output_args_accept_legacy_full_json_aliases(self) -> None:
        from e2e_harness.cli.parser import add_output_args  # noqa: PLC0415

        parser = argparse.ArgumentParser()
        add_output_args(parser)

        self.assertTrue(parser.parse_args(["--json-full"]).json_full)
        self.assertTrue(parser.parse_args(["--full-json"]).json_full)
        self.assertTrue(parser.parse_args(["--compact-output"]).compact_output)

    def test_legacy_cli_reexports_parser_output_args(self) -> None:
        import e2e_dev_harness  # noqa: PLC0415
        from e2e_harness.cli.parser import add_output_args  # noqa: PLC0415

        self.assertIs(add_output_args, e2e_dev_harness.add_output_args)

    def test_legacy_cli_reexports_parser_prepare_args(self) -> None:
        import e2e_dev_harness  # noqa: PLC0415
        from e2e_harness.cli.parser import add_prepare_args  # noqa: PLC0415

        self.assertIs(add_prepare_args, e2e_dev_harness.add_prepare_args)


if __name__ == "__main__":
    unittest.main()
