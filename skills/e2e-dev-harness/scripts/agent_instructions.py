#!/usr/bin/env python3
"""Discover project and scoped AGENT.md/AGENTS.md instructions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import SKIP_DIRS, parse_modules, posix  # noqa: E402


AGENT_FILENAMES = ("AGENTS.override.md", "AGENT.override.md", "AGENT.md", "AGENTS.md")
AGENT_SCOPES = ("auto", "discovery", "affected", "all")
DEFAULT_DISCOVERED_SERVICE_LIMIT = 20


def env_default(new_name: str, old_name: str, fallback: str) -> str:
    return os.environ.get(new_name) or os.environ.get(old_name, fallback)


def first_agent_file(directory: Path) -> Path | None:
    for name in AGENT_FILENAMES:
        candidate = directory / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


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


def normalize_requested_paths(repo: Path, paths: list[str] | None) -> list[Path]:
    normalized: list[Path] = []
    for raw in paths or []:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = repo / candidate
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate.absolute()
        if is_relative_to(resolved, repo):
            normalized.append(resolved)
    return normalized


def path_parent_for_scope(path: Path) -> Path:
    if path.exists() and path.is_dir():
        return path
    return path.parent


def scoped_agent_files(repo: Path, paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        current = path_parent_for_scope(path)
        ancestors: list[Path] = []
        while True:
            ancestors.append(current)
            if current == repo:
                break
            if not is_relative_to(current, repo) or current.parent == current:
                break
            current = current.parent
        for directory in reversed(ancestors):
            agent = first_agent_file(directory)
            if agent:
                key = str(agent.resolve()).lower()
                if key not in seen:
                    seen.add(key)
                    found.append(agent.resolve())
    return found


def affected_service_dirs(repo: Path, paths: list[Path]) -> list[Path]:
    services = service_dirs(repo)
    if not paths:
        return services
    affected: list[Path] = []
    for service in services:
        if any(is_relative_to(path, service) for path in paths):
            affected.append(service)
    return affected


def normalize_requested_services(repo: Path, services: list[str] | None) -> tuple[list[Path], list[str]]:
    known = service_dirs(repo)
    by_slug = {path.name.lower(): path for path in known}
    by_relative = {posix(path.relative_to(repo)).lower(): path for path in known}
    normalized: list[Path] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for raw in services or []:
        value = raw.replace("\\", "/").strip("/")
        matched = by_relative.get(value.lower()) or by_slug.get(value.lower())
        if matched:
            key = str(matched.resolve()).lower()
            if key not in seen:
                seen.add(key)
                normalized.append(matched.resolve())
        else:
            unresolved.append(raw)
    return normalized, unresolved


def resolve_scope(scope: str, requested_paths: list[Path], requested_services: list[Path]) -> str:
    if scope != "auto":
        return scope
    if requested_paths or requested_services:
        return "affected"
    return "discovery"


def selected_service_dirs(repo: Path, paths: list[Path], requested_services: list[Path], resolved_scope: str) -> list[Path]:
    if resolved_scope == "all":
        return service_dirs(repo)
    selected: list[Path] = []
    if resolved_scope == "affected":
        seen: set[str] = set()
        for service in affected_service_dirs(repo, paths) if paths else []:
            key = str(service.resolve()).lower()
            if key not in seen:
                seen.add(key)
                selected.append(service.resolve())
        for service in requested_services:
            key = str(service.resolve()).lower()
            if key not in seen:
                seen.add(key)
                selected.append(service.resolve())
    return sorted(selected, key=lambda path: posix(path.relative_to(repo)))


def service_agent_items(repo: Path, directories: list[Path], include_content: bool, max_chars: int) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    missing: list[str] = []
    for directory in directories:
        agent = first_agent_file(directory)
        item = {
            "service_dir": posix(directory.relative_to(repo)),
            "agent_file": posix(agent.relative_to(repo)) if agent else None,
        }
        if agent and include_content:
            item["content"] = read_preview(agent, max_chars)
        items.append(item)
        if not agent:
            missing.append(posix(directory.relative_to(repo)))
    return items, missing


def capped_items(items: list[dict], limit: int) -> tuple[list[dict], bool]:
    if limit <= 0 or len(items) <= limit:
        return items, False
    return items[:limit], True


def read_preview(path: Path, max_chars: int) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]"
    return text


def scan(
    repo: Path,
    include_content: bool,
    max_chars: int,
    paths: list[str] | None = None,
    scope: str = "auto",
    services: list[str] | None = None,
    max_discovered_services: int = DEFAULT_DISCOVERED_SERVICE_LIMIT,
) -> dict:
    repo = repo.resolve()
    requested_paths = normalize_requested_paths(repo, paths)
    requested_services, unresolved_services = normalize_requested_services(repo, services)
    resolved = resolve_scope(scope, requested_paths, requested_services)
    root_agent = first_agent_file(repo)
    all_service_dirs = service_dirs(repo)
    all_service_items, discovered_missing_services = service_agent_items(repo, all_service_dirs, False, max_chars)
    discovered_service_items, discovered_truncated = capped_items(all_service_items, max_discovered_services)
    selected_dirs = selected_service_dirs(repo, requested_paths, requested_services, resolved)
    services_to_load, missing_services = service_agent_items(repo, selected_dirs, include_content, max_chars)

    scoped_files = scoped_agent_files(repo, requested_paths)
    load_order_paths: list[Path] = []
    seen_load: set[str] = set()

    def append_load(path: Path | None) -> None:
        if not path:
            return
        resolved = path.resolve()
        key = str(resolved).lower()
        if key not in seen_load:
            seen_load.add(key)
            load_order_paths.append(resolved)

    append_load(root_agent)
    for scoped in scoped_files:
        append_load(scoped)
    for item in services_to_load:
        if item["agent_file"]:
            append_load(repo / item["agent_file"])

    result = {
        "repo": str(repo),
        "requested_paths": [posix(path.relative_to(repo)) for path in requested_paths],
        "requested_services": [posix(path.relative_to(repo)) for path in requested_services],
        "unresolved_requested_services": unresolved_services,
        "requested_scope": scope,
        "resolved_scope": resolved,
        "root_agent_file": posix(root_agent.relative_to(repo)) if root_agent else None,
        "service_agent_files": services_to_load,
        "discovered_service_count": len(all_service_items),
        "discovered_service_agent_files": discovered_service_items,
        "discovered_service_agent_files_truncated": discovered_truncated,
        "discovered_service_agent_files_limit": max_discovered_services,
        "scoped_agent_files": [posix(path.relative_to(repo)) for path in scoped_files],
        "missing": {
            "root": root_agent is None,
            "services": missing_services,
            "requested_services": unresolved_services,
            "discovered_services": discovered_missing_services,
        },
        "next_steps": [
            "Use discovery scope only for root project instructions and service inventory.",
            "After requirements identify affected services, rerun with --scope affected plus --service or --path.",
            "Use --scope all only for explicit whole-repo service work.",
        ],
        "load_order": [posix(path.relative_to(repo)) for path in load_order_paths],
        "notes": [
            "Load root project instructions before service-specific instructions.",
            "Default auto scope uses discovery before affected services are known: load root instructions and list service AGENT files without loading their contents.",
            "After clarification identifies affected services, rerun with --path or --service so only those service AGENT files enter load_order.",
            "Use --scope all only when the task genuinely needs every service instruction file.",
            "User instructions override AGENT.md; AGENT.md overrides this skill's defaults.",
            "More deeply nested AGENT files override broader AGENT files when both apply.",
        ],
    }
    if include_content:
        result["instruction_contents"] = {
            posix(path.relative_to(repo)): read_preview(path, max_chars)
            for path in load_order_paths
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--mode", choices=["auto", "strict", "optional", "off"], default=env_default("E2E_DEV_HARNESS_AGENT_INSTRUCTIONS_MODE", "E2E_DEV_WORKFLOW_AGENT_INSTRUCTIONS_MODE", "auto"))
    parser.add_argument("--include-content", action="store_true", help="Include instruction file content in output.")
    parser.add_argument("--max-chars", type=int, default=12000, help="Max chars per instruction file when including content.")
    parser.add_argument("--path", action="append", dest="paths", help="Path that may be touched; can be repeated to load scoped AGENT files.")
    parser.add_argument("--service", action="append", dest="services", help="Affected service directory or service name; can be repeated.")
    parser.add_argument("--scope", choices=AGENT_SCOPES, default=env_default("E2E_DEV_HARNESS_AGENT_INSTRUCTIONS_SCOPE", "E2E_DEV_WORKFLOW_AGENT_INSTRUCTIONS_SCOPE", "auto"))
    parser.add_argument("--max-discovered-services", type=int, default=DEFAULT_DISCOVERED_SERVICE_LIMIT)
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
        result = scan(
            repo,
            args.include_content,
            args.max_chars,
            args.paths,
            args.scope,
            args.services,
            args.max_discovered_services,
        )
        missing = result["missing"]["root"] or bool(result["missing"]["services"]) or bool(result["missing"]["requested_services"])
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
        if result.get("requested_paths"):
            print("requested paths:")
            for path in result["requested_paths"]:
                print(f"- {path}")
        if result.get("requested_services"):
            print("requested services:")
            for service in result["requested_services"]:
                print(f"- {service}")
        if result.get("resolved_scope"):
            print(f"scope: {result['resolved_scope']}")
        if result.get("root_agent_file"):
            print(f"root: {result['root_agent_file']}")
        if result.get("discovered_service_agent_files") and not result.get("service_agent_files"):
            print("discovered services:")
            for item in result["discovered_service_agent_files"]:
                status = item["agent_file"] or "MISSING"
                print(f"- {item['service_dir']}: {status}")
        if result.get("service_agent_files"):
            print("services:")
            for item in result["service_agent_files"]:
                status = item["agent_file"] or "MISSING"
                print(f"- {item['service_dir']}: {status}")
        if result.get("load_order"):
            print("load order:")
            for path in result["load_order"]:
                print(f"- {path}")
        if args.include_content and result.get("instruction_contents"):
            for path in result["load_order"]:
                content = result["instruction_contents"].get(path)
                if content is not None:
                    print("\n--- BEGIN instructions: " + path + " ---")
                    print(content.rstrip())
                    print("--- END instructions ---")
        if result.get("blocked"):
            print("blocked: missing required AGENT.md/AGENTS.md")
    return 2 if result.get("blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
