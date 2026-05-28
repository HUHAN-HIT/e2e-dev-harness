#!/usr/bin/env python3
"""Discover Superpowers skills and enforce the e2e-dev-harness adapter policy."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REQUIRED = {
    "clarification": ["using-superpowers", "brainstorming"],
    "implementation": ["writing-plans", "test-driven-development"],
}


def candidate_skill_dirs() -> list[Path]:
    candidates: list[Path] = []
    env_skills = os.environ.get("SUPERPOWERS_SKILLS_DIR")
    if env_skills:
        candidates.append(Path(env_skills).expanduser())

    env_root = os.environ.get("SUPERPOWERS_ROOT")
    if env_root:
        root = Path(env_root).expanduser()
        candidates.extend([root / "skills", root])

    home = Path.home()
    candidates.extend(home.glob(".codex/plugins/cache/*/superpowers/*/skills"))
    candidates.extend(home.glob(".codex/plugins/cache/*/superpowers/*"))
    candidates.extend(home.glob(".codex/skills"))
    candidates.extend(home.glob(".agents/skills"))
    candidates.extend(home.glob(".claude/skills"))
    candidates.extend(home.glob(".claude/plugins/*/superpowers/*/skills"))
    candidates.extend(home.glob(".claude/plugins/*/superpowers/*"))
    candidates.extend(home.glob(".gemini/skills"))
    candidates.extend(home.glob(".config/superpowers/skills"))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def skill_path(base: Path, name: str) -> Path:
    if (base / name / "SKILL.md").exists():
        return base / name / "SKILL.md"
    if base.name == name and (base / "SKILL.md").exists():
        return base / "SKILL.md"
    return base / name / "SKILL.md"


def discover() -> dict:
    found: dict[str, str] = {}
    checked: list[str] = []
    all_required = sorted({name for names in REQUIRED.values() for name in names})

    for base in candidate_skill_dirs():
        checked.append(str(base))
        if not base.exists():
            continue
        for name in all_required:
            path = skill_path(base, name)
            if path.exists() and name not in found:
                found[name] = str(path)

    missing = {
        phase: [name for name in names if name not in found]
        for phase, names in REQUIRED.items()
    }
    return {
        "checked": checked,
        "found": found,
        "missing": missing,
        "available": not any(missing.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["auto", "strict", "optional", "off"],
        default=os.environ.get("E2E_DEV_WORKFLOW_SUPERPOWERS_MODE", "auto"),
    )
    parser.add_argument("--phase", choices=["all", "clarification", "implementation"], default="all")
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    args = parser.parse_args()

    if args.mode == "off":
        result = {
            "mode": args.mode,
            "phase": args.phase,
            "available": False,
            "enabled": False,
            "blocked": False,
            "found": {},
            "missing": {},
            "checked": [],
            "message": "Superpowers adapter disabled by policy.",
        }
    else:
        result = discover()
        if args.phase != "all":
            result["missing"] = {args.phase: result["missing"][args.phase]}
            result["available"] = not result["missing"][args.phase]
        result.update({
            "mode": args.mode,
            "phase": args.phase,
            "enabled": result["available"],
            "blocked": args.mode == "strict" and not result["available"],
        })
        result["message"] = (
            "Superpowers adapter available."
            if result["available"]
            else "Superpowers adapter incomplete or unavailable."
        )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result["message"])
        print(f"mode: {result['mode']}")
        print(f"phase: {result['phase']}")
        if result.get("found"):
            print("found:")
            for name, path in sorted(result["found"].items()):
                print(f"- superpowers:{name} -> {path}")
        if result.get("missing"):
            printed_missing = False
            for phase, names in result["missing"].items():
                if names:
                    if not printed_missing:
                        print("missing:")
                        printed_missing = True
                    print(f"- {phase}: {', '.join('superpowers:' + name for name in names)}")

    return 2 if result.get("blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
