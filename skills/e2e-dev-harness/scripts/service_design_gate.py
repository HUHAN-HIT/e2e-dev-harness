#!/usr/bin/env python3
"""Validate service-local design slices against the global design."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import clarification_gate  # noqa: E402
import coverage_gate  # noqa: E402
from common import configure_utf8_stdio, posix  # noqa: E402


REQUIRED_SECTIONS = {
    "Service Scope",
    "Global Intent Summary",
    "Mapped Acceptance Criteria",
    "Runtime Path",
    "Service-local TDD Plan",
    "Dependency Boundary",
    "Test Impact",
}
AC_RE = re.compile(r"\bAC-\d+\b", re.IGNORECASE)
EMPTY_VALUES = {"", "n/a", "none", "-", "todo", "tbd"}
CONCRETE_RUNTIME_RE = re.compile(r"(->|controller|service|repository|client|sender|producer|listener|handler|#|\.)", re.IGNORECASE)
TEST_REF_RE = re.compile(r"(\b[A-Z][A-Za-z0-9_]*(?:Test|Tests|IT|Spec)\b|src/test|mvn|gradle|junit|assert)", re.IGNORECASE)
MAVEN_OR_TEST_COMMAND_RE = re.compile(r"\b(mvn|gradle|test|verify)\b", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\b(todo|tbd|pending|unknown|placeholder)\b|<[^>]+>", re.IGNORECASE)
MOJIBAKE_LEAD_CHARS = (
    "\u59af\u5be6\u690b\u699b\u6d5c\u6f61\u7039\u704f\u7459\u7487"
    "\u7eef\u7f02\u934f\u9359\u935a\u935c\u9366\u93c0"
)
MOJIBAKE_RE = re.compile(r"[\ufffd]|(?:[" + re.escape(MOJIBAKE_LEAD_CHARS) + r"][\u4e00-\u9fff]{1,8})")


SECTION_TEMPLATES = {
    "Service Scope": "## Service Scope\n- Service/module: <service>\n- Allowed edit scope:\n  - <service>/\n- Explicitly out of scope:\n",
    "Global Intent Summary": "## Global Intent Summary\n- Restated user intent:\n- This service's responsibility:\n",
    "Mapped Acceptance Criteria": (
        "## Mapped Acceptance Criteria\n"
        "| AC | global requirement | service responsibility | local tests |\n"
        "| --- | --- | --- | --- |\n"
        "| AC-1 |  |  | <ServiceTest> |\n"
    ),
    "Runtime Path": "## Runtime Path\n- Controller#method -> Service#method -> Repository/Client/Sender#method\n",
    "Local Sequence": (
        "## Local Sequence\n"
        "```mermaid\n"
        "sequenceDiagram\n"
        "    participant Entry\n"
        "    participant Service\n"
        "    participant Edge as Repository/Client/Sender\n"
        "    Entry->>Service: Execute mapped AC behavior\n"
        "    Service->>Edge: Persist, call, or publish declared side effect\n"
        "    Edge-->>Service: Result or acknowledgement\n"
        "```\n"
    ),
    "Service-local TDD Plan": (
        "## Service-local TDD Plan\n"
        "- First red test: <ServiceTest> should fail before implementation\n"
        "- Expected failure: <missing behavior/assertion>\n"
        "- Minimal green implementation:\n"
        "- Refactor checks:\n"
        "- Required Maven command: mvn -pl <service> -am test\n"
    ),
    "Dependency Boundary": (
        "## Dependency Boundary\n"
        "- Independent service change: yes/no with reason\n"
        "- HTTP/API dependencies: None or contract path\n"
        "- MQ/DMQ/Kafka dependencies: None or topic/contract\n"
        "- Shared DB/schema/config/security dependencies: None or migration/config path\n"
        "- Required contracts or explicit non-applicability:\n"
    ),
    "Test Impact": "## Test Impact\n- Service-local test impact plan: mvn -pl <service> -am test\n- Broadened verification:\n",
}


def resolve(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    return path if path.is_absolute() else repo / path


def section_titles(text: str) -> set[str]:
    return {
        match.group(1).strip()
        for match in re.finditer(r"^\s{0,3}##\s+(.+?)\s*$", text, re.MULTILINE)
    }


def section_body(text: str, title: str) -> str:
    return clarification_gate.section_text(text, [r"^" + re.escape(title.lower()) + r"$"]) or ""


def explicit_service_files(repo: Path, paths: list[Path] | None, service_design_dir: Path | None) -> list[Path]:
    files: list[Path] = []
    for path in paths or []:
        resolved = resolve(repo, path)
        if not resolved:
            continue
        if resolved.is_file():
            files.append(resolved)
        elif resolved.is_dir():
            files.extend(sorted(resolved.glob("*.md")))
    resolved_dir = resolve(repo, service_design_dir)
    if resolved_dir and resolved_dir.exists():
        files.extend(sorted(resolved_dir.glob("*.md")))
    return sorted(dict.fromkeys(files))


def mapped_acceptance_ids(text: str) -> set[str]:
    ids: set[str] = set()
    for row in coverage_gate.parse_markdown_tables(text):
        for key, value in row.items():
            if key in {"ac", "id", "acceptance", "global_requirement"}:
                ids.update(match.upper() for match in AC_RE.findall(value))
    ids.update(match.upper() for match in AC_RE.findall(text))
    return ids


def has_allowed_edit_scope(text: str) -> bool:
    scope = section_body(text, "Service Scope")
    for line in scope.splitlines():
        normalized = line.strip().lower().strip("-* ")
        if normalized in EMPTY_VALUES:
            continue
        if "allowed edit scope" in normalized:
            continue
        if "/" in normalized or "\\" in normalized:
            return True
    return False


def dependency_boundary_closed(text: str) -> bool:
    body = section_body(text, "Dependency Boundary")
    lowered = body.lower()
    if any(marker in lowered for marker in ("todo", "tbd", "<", "pending")):
        return False
    return "independent service change:" in lowered


def meaningful_lines(body: str) -> list[str]:
    lines: list[str] = []
    for line in body.splitlines():
        normalized = line.strip().strip("-* ")
        if normalized.lower() in EMPTY_VALUES:
            continue
        if PLACEHOLDER_RE.search(normalized):
            continue
        lines.append(normalized)
    return lines


def runtime_path_is_concrete(text: str) -> bool:
    body = section_body(text, "Runtime Path")
    return any(CONCRETE_RUNTIME_RE.search(line) for line in meaningful_lines(body))


def local_sequence_is_concrete(text: str) -> bool:
    body = section_body(text, "Local Sequence")
    lines = meaningful_lines(body)
    return any("sequencediagram" in line.lower() for line in lines) or any(
        re.search(r"\bparticipant\b|->>|-->>|->", line, re.IGNORECASE) for line in lines
    )


def dependency_boundary_has_runtime_coupling(text: str) -> bool:
    body = section_body(text, "Dependency Boundary")
    for raw_line in body.splitlines():
        line = raw_line.strip().strip("-* ")
        normalized = line.lower()
        if not normalized:
            continue
        value = line.split(":", 1)[1].strip().lower() if ":" in line else ""
        if "independent service change" in normalized and re.search(r"\b(no|false)\b|not independent", value):
            return True
        labels = (
            "http/api dependencies",
            "mq/dmq/kafka dependencies",
            "shared db/schema/config/security dependencies",
            "required contracts",
        )
        if not any(label in normalized for label in labels):
            continue
        cleaned = value.strip(" .;")
        if cleaned and cleaned not in EMPTY_VALUES and not cleaned.startswith(("none", "n/a", "not applicable", "no ")):
            return True
    return False


def tdd_plan_is_concrete(text: str) -> bool:
    body = section_body(text, "Service-local TDD Plan")
    lines = meaningful_lines(body)
    has_red_test = any("first red test" in line.lower() and TEST_REF_RE.search(line) for line in lines)
    has_expected_failure = any("expected failure" in line.lower() and len(line.split(":", 1)[-1].strip()) > 3 for line in lines)
    has_command = any("required maven command" in line.lower() and MAVEN_OR_TEST_COMMAND_RE.search(line) for line in lines)
    return has_red_test and has_expected_failure and has_command


def test_impact_is_concrete(text: str) -> bool:
    body = section_body(text, "Test Impact")
    return any(MAVEN_OR_TEST_COMMAND_RE.search(line) for line in meaningful_lines(body))


def local_tests_are_mapped(text: str) -> list[str]:
    missing: list[str] = []
    for row in coverage_gate.parse_markdown_tables(text):
        ac_values = " ".join(row.get(key, "") for key in ("ac", "id", "acceptance", "global_requirement"))
        ids = [match.upper() for match in AC_RE.findall(ac_values)]
        if not ids:
            continue
        local_tests = row.get("local_tests") or row.get("tests") or ""
        if not TEST_REF_RE.search(local_tests):
            missing.extend(ids)
    return sorted(set(missing))


def mojibake_samples(text: str, limit: int = 3) -> list[str]:
    samples: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if MOJIBAKE_RE.search(stripped):
            samples.append(stripped[:120])
        if len(samples) >= limit:
            break
    return samples


def add_fix_hint(
    fix_hints: list[dict],
    action: str,
    message: str,
    path: str = "",
    section: str = "",
    template: str = "",
) -> None:
    hint = {"action": action, "message": message}
    if path:
        hint["path"] = path
    if section:
        hint["section"] = section
    if template:
        hint["template"] = template
    if hint not in fix_hints:
        fix_hints.append(hint)


def validate(repo: Path, global_design: Path | None, service_design_dir: Path | None = None, service_designs: list[Path] | None = None) -> dict:
    repo = repo.resolve()
    blocked: list[str] = []
    warnings: list[str] = []
    fix_hints: list[dict] = []
    design_path = resolve(repo, global_design)
    global_acs: set[str] = set()
    if not design_path or not design_path.exists():
        blocked.append("Global design document is required for service design validation.")
        add_fix_hint(
            fix_hints,
            "provide_global_design",
            "Pass --global-design pointing at the clarified design doc with Acceptance Criteria.",
        )
    else:
        global_acs = {item["id"].upper() for item in clarification_gate.extract_acceptance_items(design_path)}
        if not global_acs:
            blocked.append("Global design has no acceptance criteria to map into service designs.")
            add_fix_hint(
                fix_hints,
                "add_acceptance_criteria",
                "Add AC-N acceptance criteria to the global design before writing service slices.",
                path=posix(design_path.relative_to(repo)),
            )

    files = explicit_service_files(repo, service_designs, service_design_dir)
    if not files:
        blocked.append("No service design files found; expected service-designs/<service>.md.")
        add_fix_hint(
            fix_hints,
            "create_service_design",
            "Create one service-designs/<service>.md file per affected service, or run service-design --emit-template <service>.",
        )

    mapped: dict[str, list[str]] = {}
    for path in files:
        rel_path = posix(path.relative_to(repo))
        text = path.read_text(encoding="utf-8", errors="replace")
        mojibake = mojibake_samples(text)
        if mojibake:
            blocked.append(
                f"Service design {rel_path} appears to contain mojibake/encoding-corrupted text; "
                "rewrite it as UTF-8 before validation. Samples: " + " | ".join(mojibake)
            )
            add_fix_hint(
                fix_hints,
                "rewrite_utf8",
                "Rewrite the service design as clean UTF-8 text; do not patch over mojibake samples.",
                path=rel_path,
            )
        titles = section_titles(text)
        missing = sorted(REQUIRED_SECTIONS - titles)
        if missing:
            blocked.append(f"Service design {rel_path} missing sections: {', '.join(missing)}")
            for title in missing:
                add_fix_hint(
                    fix_hints,
                    "add_section",
                    f"Add the ## {title} section to the service design.",
                    path=rel_path,
                    section=title,
                    template=SECTION_TEMPLATES.get(title, f"## {title}\n"),
                )
        ids = mapped_acceptance_ids(text)
        for ac_id in ids:
            mapped.setdefault(ac_id, []).append(rel_path)
        unknown = sorted(ids - global_acs) if global_acs else []
        if unknown:
            blocked.append(f"Service design {rel_path} maps unknown global AC ids: {', '.join(unknown)}")
            add_fix_hint(
                fix_hints,
                "replace_unknown_ac_ids",
                "Map only AC ids that exist in the global design document.",
                path=rel_path,
                section="Mapped Acceptance Criteria",
            )
        if not ids:
            blocked.append(f"Service design {rel_path} must map at least one global AC.")
            add_fix_hint(
                fix_hints,
                "map_acceptance_criteria",
                "Add at least one global AC id and local test in the Mapped Acceptance Criteria table.",
                path=rel_path,
                section="Mapped Acceptance Criteria",
                template=SECTION_TEMPLATES["Mapped Acceptance Criteria"],
            )
        if not has_allowed_edit_scope(text):
            blocked.append(f"Service design {rel_path} must declare a concrete allowed edit scope.")
            add_fix_hint(
                fix_hints,
                "declare_allowed_edit_scope",
                "Under Service Scope, add an Allowed edit scope entry with the service path.",
                path=rel_path,
                section="Service Scope",
            )
        if not runtime_path_is_concrete(text):
            blocked.append(f"Service design {rel_path} must declare a concrete Runtime Path.")
            add_fix_hint(
                fix_hints,
                "fill_runtime_path",
                "Describe the concrete call path from entry point to service/repository/client/sender.",
                path=rel_path,
                section="Runtime Path",
                template=SECTION_TEMPLATES["Runtime Path"],
            )
        if dependency_boundary_has_runtime_coupling(text) and not local_sequence_is_concrete(text):
            blocked.append(
                f"Service design {rel_path} must declare a concrete Local Sequence for cross-service, contract, shared-state, or event dependencies."
            )
            add_fix_hint(
                fix_hints,
                "add_local_sequence",
                "Add ## Local Sequence with a Mermaid sequenceDiagram that shows the service-local entry point, collaborator, and dependency edge.",
                path=rel_path,
                section="Local Sequence",
                template=SECTION_TEMPLATES["Local Sequence"],
            )
        if not tdd_plan_is_concrete(text):
            blocked.append(f"Service design {rel_path} must declare first red test, expected failure, and required Maven command.")
            add_fix_hint(
                fix_hints,
                "fill_tdd_plan",
                "Fill first red test, expected failure, and required Maven command exactly in Service-local TDD Plan.",
                path=rel_path,
                section="Service-local TDD Plan",
                template=SECTION_TEMPLATES["Service-local TDD Plan"],
            )
        if not test_impact_is_concrete(text):
            blocked.append(f"Service design {rel_path} must declare concrete Test Impact command.")
            add_fix_hint(
                fix_hints,
                "fill_test_impact",
                "Add the concrete Maven/Gradle command used to validate this service slice.",
                path=rel_path,
                section="Test Impact",
                template=SECTION_TEMPLATES["Test Impact"],
            )
        missing_tests = local_tests_are_mapped(text)
        if missing_tests:
            blocked.append(
                f"Service design {rel_path} must map local tests for ACs: "
                + ", ".join(missing_tests)
            )
            add_fix_hint(
                fix_hints,
                "map_local_tests",
                "Fill the local tests column with concrete test class or src/test paths for each mapped AC.",
                path=rel_path,
                section="Mapped Acceptance Criteria",
            )
        if not dependency_boundary_closed(text):
            blocked.append(f"Service design {rel_path} must close Dependency Boundary and state independent service change.")
            add_fix_hint(
                fix_hints,
                "close_dependency_boundary",
                "Replace placeholders and include the literal Independent service change: line with a yes/no decision and reason.",
                path=rel_path,
                section="Dependency Boundary",
                template=SECTION_TEMPLATES["Dependency Boundary"],
            )

    missing_global = sorted(ac_id for ac_id in global_acs if ac_id not in mapped)
    if missing_global:
        blocked.append("Global acceptance criteria not mapped to any service design: " + ", ".join(missing_global))
        add_fix_hint(
            fix_hints,
            "map_uncovered_global_acs",
            "Assign every global AC to at least one service design and include a concrete local test.",
            section="Mapped Acceptance Criteria",
            template=SECTION_TEMPLATES["Mapped Acceptance Criteria"],
        )
    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "fix_hints": fix_hints,
        "warnings": warnings,
        "global_acceptance_ids": sorted(global_acs),
        "mapped_acceptance_ids": sorted(mapped),
        "service_designs": [posix(path.relative_to(repo)) for path in files],
    }


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--global-design", required=True, type=Path)
    parser.add_argument("--service-design-dir", type=Path)
    parser.add_argument("--service-design", action="append", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(args.repo, args.global_design, args.service_design_dir, args.service_design)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Service design gate: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
