#!/usr/bin/env python3
"""Recommend single-agent or multi-agent orchestration for Spring 6 work."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from kg_refresh import detect  # noqa: E402


RISK_KEYWORDS = {
    "api",
    "contract",
    "event",
    "message",
    "schema",
    "migration",
    "database",
    "transaction",
    "auth",
    "permission",
    "security",
    "idempotent",
    "retry",
    "timeout",
    "跨服务",
    "契约",
    "消息",
    "事件",
    "数据库",
    "迁移",
    "权限",
    "幂等",
    "重试",
}


def read_design(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def feature_slug(design_doc: Path | None) -> str:
    if design_doc and design_doc.name:
        name = design_doc.stem
        for suffix in ("-design", "-requirements", "-use-cases", "-test-plan", "-implementation-plan"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        return name or "feature"
    return "feature"


def choose_mode(requested: str, facts: dict, design_text: str, design_is_template: bool) -> tuple[str, list[str]]:
    if requested in {"single", "multi"}:
        return requested, [f"mode explicitly set to {requested}"]

    reasons: list[str] = []
    service_count = len(facts.get("service_candidates", []))
    if facts.get("multi_service") or service_count > 1:
        reasons.append("multiple service candidates detected")
    if design_is_template:
        reasons.append("template design doc detected; placeholder risk keywords ignored")
    elif len(design_text) > 3000:
        reasons.append("design document is large enough to benefit from context isolation")
    if not design_is_template:
        lowered = design_text.lower()
        matched = sorted(keyword for keyword in RISK_KEYWORDS if keyword.lower() in lowered)
        if matched:
            reasons.append("risk keywords detected: " + ", ".join(matched[:8]))
    if not design_is_template and facts.get("design_docs_or_media_count", 0) >= 12:
        reasons.append("many design/media artifacts detected")

    actionable_reasons = [reason for reason in reasons if not reason.startswith("template design doc")]
    if actionable_reasons:
        return "multi", reasons
    return "single", ["single service and low-risk design context detected"]


def artifacts(slug: str) -> dict:
    base = f"docs/design/{slug}"
    return {
        "requirements": f"{base}-requirements.md",
        "use_cases": f"{base}-use-cases.md",
        "test_plan": f"{base}-test-plan.md",
        "implementation_plan": f"{base}-implementation-plan.md",
    }


def agent_plan(selected_mode: str, artifact_paths: dict) -> list[dict]:
    if selected_mode == "single":
        return [
            {
                "name": "single-agent",
                "owns": ["requirements", "use cases", "tests", "implementation"],
                "inputs": ["user request", "knowledge graph summary"],
                "outputs": list(artifact_paths.values()),
                "gate": "All open questions must be resolved before production-code edits.",
            }
        ]

    return [
        {
            "name": "requirements-clarifier",
            "owns": ["goal", "non-goals", "constraints", "acceptance criteria", "open questions"],
            "inputs": ["user request", "knowledge graph summary"],
            "outputs": [artifact_paths["requirements"]],
            "gate": "Behavior/API/data/test-impacting open questions must be resolved.",
        },
        {
            "name": "use-case-designer",
            "owns": ["happy paths", "failure paths", "cross-service flow", "contracts", "data effects"],
            "inputs": [artifact_paths["requirements"], "knowledge graph summary"],
            "outputs": [artifact_paths["use_cases"]],
            "gate": "Every acceptance criterion maps to a use case or is explicitly deferred.",
        },
        {
            "name": "test-case-developer",
            "owns": ["test strategy", "first red test", "contract tests", "Maven test scope"],
            "inputs": [artifact_paths["requirements"], artifact_paths["use_cases"], "superpowers:test-driven-development"],
            "outputs": [artifact_paths["test_plan"]],
            "gate": "First red test must be written and observed failing for the expected reason.",
        },
        {
            "name": "code-developer",
            "owns": ["minimal implementation", "red-green-refactor", "verification"],
            "inputs": [artifact_paths["requirements"], artifact_paths["use_cases"], artifact_paths["test_plan"], "failing tests"],
            "outputs": [artifact_paths["implementation_plan"], "code changes", "test results"],
            "gate": "All narrow and broadened verification commands pass.",
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument(
        "--mode",
        choices=["auto", "single", "multi"],
        default=os.environ.get("JAVA_SPRING_TDD_KG_AGENT_MODE", "auto"),
    )
    parser.add_argument("--design-doc", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not repo.exists():
        print(f"Repo not found: {repo}", file=sys.stderr)
        return 2

    design_path = args.design_doc
    if design_path and not design_path.is_absolute():
        design_path = repo / design_path
    design_text = read_design(design_path)
    facts = detect(repo)
    design_is_template = bool(design_path and "template" in design_path.stem.lower())
    selected, reasons = choose_mode(args.mode, facts, design_text, design_is_template)
    slug = feature_slug(design_path)
    artifact_paths = artifacts(slug)
    result = {
        "repo": str(repo),
        "requested_mode": args.mode,
        "selected_mode": selected,
        "reasons": reasons,
        "detected": {
            "service_candidates": facts.get("service_candidates", []),
            "multi_service": facts.get("multi_service", False),
            "design_docs_or_media_count": facts.get("design_docs_or_media_count", 0),
            "spring_entrypoints": facts.get("spring_entrypoints", []),
        },
        "handoff_artifacts": artifact_paths,
        "agents": agent_plan(selected, artifact_paths),
        "notes": [
            "Use files as handoff boundaries; do not rely on chat memory.",
            "Use superpowers:brainstorming before implementation planning.",
            "Use superpowers:test-driven-development before production-code edits.",
        ],
    }

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json:
        print(text)
    else:
        print(f"Orchestration mode: {selected}")
        print("Reasons:")
        for reason in reasons:
            print(f"- {reason}")
        print("Handoff artifacts:")
        for name, path in artifact_paths.items():
            print(f"- {name}: {path}")
        print("Agents:")
        for agent in result["agents"]:
            print(f"- {agent['name']}: {', '.join(agent['owns'])}")

    if args.status_file:
        args.status_file.parent.mkdir(parents=True, exist_ok=True)
        args.status_file.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
