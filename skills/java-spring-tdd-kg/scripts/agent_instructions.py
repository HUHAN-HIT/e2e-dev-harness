#!/usr/bin/env python3
"""Discover project and microservice AGENT.md/AGENTS.md instructions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


AGENT_FILENAMES = ("AGENT.md", "AGENTS.md")
SKIP_DIRS = {".git", ".idea", ".vscode", "target", "build", "node_modules", ".gradle", "graphify-out"}


def posix(pathlike) -> str:
    return str(pathlike).replace("\\", "/")


def first_agent_file(directory: Path) -> Path | None:
    for name in AGENT_FILENAMES:
        candidate = directory / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def parse_modules(pom: Path) -> list[str]:
    if not pom.exists():
        return []
    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(pom.read_text(encoding="utf-8"))
    except Exception:
        return []
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}", 1)[0] + "}"
    modules = root.find(f"{ns}modules")
    if modules is None:
        return []
    return [module.text.strip() for module in modules.findall(f"{ns}module") if module.text and module.text.strip()]


def service_dirs(repo: Path) -> list[Path]:
    found: set[Path] = set()

    services_root = repo / "services"
    if services_root.exists():
        for child in services_root.iterdir():
            if child.is_dir() and child.name not in SKIP_DIRS:
                if (child / "pom.xml").exists() or (child / "src").exists():
                    found.add(child.resolve())

    for module in parse_modules(repo / "pom.xml"):
        module_dir = (repo / module).resolve()
        if module_dir.exists() and module_dir != repo.resolve():
            if (module_dir / "pom.xml").exists() and (module_dir / "src").exists():
                found.add(module_dir)

    return sorted(found, key=lambda path: posix(path.relative_to(repo)))


def read_preview(path: Path, max_chars: int) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]"
    return text


def scan(repo: Path, include_content: bool, max_chars: int) -> dict:
    repo = repo.resolve()
    root_agent = first_agent_file(repo)
    services = []
    missing_services = []

    for directory in service_dirs(repo):
        agent = first_agent_file(directory)
        item = {
            "service_dir": posix(directory.relative_to(repo)),
            "agent_file": posix(agent.relative_to(repo)) if agent else None,
        }
        if agent and include_content:
            item["content"] = read_preview(agent, max_chars)
        if agent:
            services.append(item)
        else:
            services.append(item)
            missing_services.append(posix(directory.relative_to(repo)))

    result = {
        "repo": str(repo),
        "root_agent_file": posix(root_agent.relative_to(repo)) if root_agent else None,
        "service_agent_files": services,
        "missing": {
            "root": root_agent is None,
            "services": missing_services,
        },
        "load_order": [],
        "notes": [
            "Load root project instructions before service-specific instructions.",
            "Load service instructions for every affected service before requirement clarification.",
            "User instructions override AGENT.md; AGENT.md overrides this skill's defaults.",
        ],
    }
    if root_agent:
        result["load_order"].append(posix(root_agent.relative_to(repo)))
        if include_content:
            result["root_content"] = read_preview(root_agent, max_chars)
    result["load_order"].extend(item["agent_file"] for item in services if item["agent_file"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--mode", choices=["auto", "strict", "optional", "off"], default=os.environ.get("JAVA_SPRING_TDD_KG_AGENT_INSTRUCTIONS_MODE", "auto"))
    parser.add_argument("--include-content", action="store_true", help="Include instruction file content in output.")
    parser.add_argument("--max-chars", type=int, default=12000, help="Max chars per instruction file when including content.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not repo.exists():
        print(f"Repo not found: {repo}", file=sys.stderr)
        return 2

    if args.mode == "off":
        result = {
            "repo": str(repo),
            "mode": args.mode,
            "enabled": False,
            "blocked": False,
            "message": "AGENT instruction loading disabled by policy.",
        }
    else:
        result = scan(repo, args.include_content, args.max_chars)
        missing = result["missing"]["root"] or bool(result["missing"]["services"])
        result.update({
            "mode": args.mode,
            "enabled": True,
            "blocked": args.mode == "strict" and missing,
            "message": "AGENT instruction scan complete.",
        })

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result["message"])
        if result.get("root_agent_file"):
            print(f"root: {result['root_agent_file']}")
        if result.get("service_agent_files"):
            print("services:")
            for item in result["service_agent_files"]:
                status = item["agent_file"] or "MISSING"
                print(f"- {item['service_dir']}: {status}")
        if result.get("load_order"):
            print("load order:")
            for path in result["load_order"]:
                print(f"- {path}")
        if args.include_content and result.get("root_content"):
            print("\n--- BEGIN root instructions: " + result["root_agent_file"] + " ---")
            print(result["root_content"].rstrip())
            print("--- END root instructions ---")
        if args.include_content:
            for item in result.get("service_agent_files", []):
                if item.get("agent_file") and item.get("content"):
                    print("\n--- BEGIN service instructions: " + item["agent_file"] + " ---")
                    print(item["content"].rstrip())
                    print("--- END service instructions ---")
        if result.get("blocked"):
            print("blocked: missing required AGENT.md/AGENTS.md")
    return 2 if result.get("blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
