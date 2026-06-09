#!/usr/bin/env python3
"""Entry shim -> harness_v2.cli.main."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness_v2.cli.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
