#!/usr/bin/env python3
"""Validate required implementation artifacts before completion."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import coverage_gate  # noqa: E402
from common import posix  # noqa: E402


REQUIRED_COLUMNS = {
    "id",
    "module",
    "artifact",
    "artifact_type",
    "source",
    "required",
    "tests",
    "status",
    "evidence",
}
PASS_STATUSES = {"implemented", "covered", "done", "pass", "passed", "verified"}
REQUIRED_VALUES = {"yes", "y", "true", "required", "must", "mandatory", "必需", "必须", "是"}
OPTIONAL_VALUES = {"no", "n", "false", "optional", "deferred", "skip", "skipped", "否", "可选"}
NO_TEST_VALUES = {"", "-", "n/a", "na", "none", "no", "manual", "review", "code review", "代码审查"}
CLASS_LIKE_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9_]*(?:"
    r"Service|Controller|Repository|Client|Listener|Consumer|Producer|Handler|"
    r"Params|Config|Kit|Util|Dto|DTO|VO|DO|PO|Entity|Mapper|RS|RQ"
    r")\b"
)
ARTIFACT_SECTION_KEYWORDS = (
    "required artifact",
    "required artifacts",
    "implementation artifact",
    "implementation artifacts",
    "affected artifact",
    "affected artifacts",
    "affected class",
    "affected classes",
    "required class",
    "required classes",
    "affected file",
    "affected files",
    "required file",
    "required files",
    "implementation manifest",
    "artifact checklist",
    "code artifacts",
    "modification points",
    "\u5fc5\u6539",
    "\u9700\u5b9e\u73b0",
    "\u5b9e\u73b0\u4ea7\u7269",
    "\u4ea7\u7269\u6e05\u5355",
    "\u7c7b\u6e05\u5355",
    "\u6587\u4ef6\u6e05\u5355",
)
MARKED_ARTIFACT_RE = re.compile(
    r"\[(?:artifact|required-artifact|must-implement|code-artifact)\]\s*`?(" + CLASS_LIKE_RE.pattern + r")`?",
    re.IGNORECASE,
)
SECTION_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*$")
MODULE_SECTION_KEYWORDS = (
    "scope",
    "affected service",
    "affected services",
    "affected module",
    "affected modules",
    "affected services/modules",
    "in-scope",
    "in scope",
    "涉及模块",
    "影响模块",
    "影响服务",
)


def strip_bom(text: str) -> str:
    return text.lstrip("\ufeff")


def normalized_required(value: str) -> bool | None:
    lowered = value.strip().lower()
    if lowered in REQUIRED_VALUES:
        return True
    if lowered in OPTIONAL_VALUES:
        return False
    return None


def split_cell_values(value: str) -> list[str]:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    parts = re.split(r"[,;\n]+", text)
    return [part.strip().strip("`") for part in parts if part.strip().strip("`")]


def normalize_module(value: str) -> str:
    text = value.strip().strip("`").replace("\\", "/")
    text = re.sub(r"\s+#.*$", "", text)
    text = text.split(":", 1)[0].strip()
    text = text.split(" - ", 1)[0].strip()
    text = text.split(" ", 1)[0].strip()
    return text.strip("/.,;")


def module_names_from_row(row: dict[str, str]) -> set[str]:
    modules = {normalize_module(value) for value in split_cell_values(row.get("module", ""))}
    for artifact in split_artifacts(row.get("artifact", "")):
        path = artifact.replace("\\", "/").strip("/")
        if "/" in path:
            modules.add(path.split("/", 1)[0])
    return {module for module in modules if module}


def split_artifacts(value: str) -> list[str]:
    artifacts: list[str] = []
    for item in split_cell_values(value):
        cleaned = re.sub(r"\s+\(.*?\)\s*$", "", item).strip()
        artifacts.append(cleaned)
    return artifacts


def looks_like_path(value: str) -> bool:
    text = value.replace("\\", "/")
    return "/" in text or bool(re.search(r"\.[a-zA-Z0-9]{1,8}(?::\d+)?$", text))


def resolve_artifact_path(repo: Path, artifact: str) -> Path:
    text = artifact.strip().strip("`")
    if re.search(r"\.[a-zA-Z0-9]{1,8}:\d+$", text):
        text = text.rsplit(":", 1)[0]
    if re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith(("/", "\\")):
        return Path(text)
    path = Path(text)
    return path if path.is_absolute() else repo / path


def design_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        match = SECTION_HEADING_RE.match(line)
        if match:
            current = match.group("title").strip().lower()
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(line)
    return {title: "\n".join(lines).strip() for title, lines in sections.items()}


def extract_design_modules(design_path: Path | None) -> list[str]:
    if not design_path or not design_path.exists():
        return []
    text = strip_bom(design_path.read_text(encoding="utf-8", errors="replace"))
    modules: list[str] = []
    seen: set[str] = set()
    for title, body in design_sections(text).items():
        if not any(keyword in title for keyword in MODULE_SECTION_KEYWORDS):
            continue
        for line in body.splitlines():
            if not re.match(r"\s*[-*]\s+", line):
                continue
            item = re.sub(r"^\s*[-*]\s+", "", line).strip()
            module = normalize_module(item)
            if module and module.lower() not in {"none", "n/a"} and module not in seen:
                seen.add(module)
                modules.append(module)
    return modules


def extract_design_artifacts(design_path: Path | None) -> list[str]:
    if not design_path or not design_path.exists():
        return []
    text = strip_bom(design_path.read_text(encoding="utf-8", errors="replace"))
    result: list[str] = []
    seen: set[str] = set()
    bodies: list[str] = []
    for title, body in design_sections(text).items():
        if any(keyword in title for keyword in ARTIFACT_SECTION_KEYWORDS):
            bodies.append(body)
    for marker in MARKED_ARTIFACT_RE.finditer(text):
        value = marker.group(1)
        if value not in seen:
            seen.add(value)
            result.append(value)
    for match in CLASS_LIKE_RE.finditer("\n".join(bodies)):
        value = match.group(0)
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def design_requires_manifest(design_path: Path | None) -> bool:
    modules = extract_design_modules(design_path)
    artifacts = extract_design_artifacts(design_path)
    return len(modules) > 1 or len(artifacts) >= 3


def row_mentions(row: dict[str, str], needle: str) -> bool:
    haystack = " ".join(str(value) for value in row.values())
    return needle in haystack


def validate(repo: Path, manifest: Path | None, design_doc: Path | None = None) -> dict:
    repo = repo.resolve()
    blocked: list[str] = []
    warnings: list[str] = []
    rows: list[dict[str, str]] = []

    manifest_path = manifest if manifest and manifest.is_absolute() else (repo / manifest if manifest else None)
    if not manifest_path:
        if design_requires_manifest(design_doc):
            blocked.append("Implementation manifest is required for multi-module or artifact-heavy designs.")
        return {
            "repo": str(repo),
            "ready": not blocked,
            "blocked_reasons": blocked,
            "warnings": warnings,
            "implementation_manifest": None,
            "rows": 0,
            "required_rows": 0,
            "design_modules": extract_design_modules(design_doc),
            "design_artifacts": extract_design_artifacts(design_doc),
        }
    if not manifest_path.exists():
        blocked.append(f"Implementation manifest not found: {manifest_path}")
        return {
            "repo": str(repo),
            "ready": False,
            "blocked_reasons": blocked,
            "warnings": warnings,
            "implementation_manifest": str(manifest_path),
            "rows": 0,
            "required_rows": 0,
            "design_modules": extract_design_modules(design_doc),
            "design_artifacts": extract_design_artifacts(design_doc),
        }

    text = strip_bom(manifest_path.read_text(encoding="utf-8", errors="replace"))
    if coverage_gate.TODO_RE.search(text):
        blocked.append(f"Implementation manifest contains unresolved TODO/TBD markers: {manifest_path}")
    rows = coverage_gate.parse_markdown_tables(text)
    if not rows:
        blocked.append(f"Implementation manifest has no Markdown table rows: {manifest_path}")
    else:
        columns = set().union(*(row.keys() for row in rows))
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            blocked.append("Implementation manifest missing columns: " + ", ".join(missing))

    required_rows = 0
    covered_modules: set[str] = set()
    for index, row in enumerate(rows, start=1):
        row_id = row.get("id") or f"row {index}"
        for column in sorted(REQUIRED_COLUMNS):
            if not row.get(column, "").strip():
                blocked.append(f"Implementation manifest {row_id} missing {column}.")
        required = normalized_required(row.get("required", ""))
        if required is None:
            blocked.append(f"Implementation manifest {row_id} required must be yes/no or equivalent.")
            required = True
        if not required:
            continue
        required_rows += 1
        covered_modules.update(module_names_from_row(row))
        status = row.get("status", "").strip().lower()
        if status not in PASS_STATUSES:
            blocked.append(f"Implementation manifest {row_id} status is not implemented/verified: {row.get('status')}")
        tests = row.get("tests", "").strip().lower()
        if tests in NO_TEST_VALUES:
            blocked.append(f"Implementation manifest {row_id} requires real tests, not review-only evidence.")
        source = row.get("source", "").strip().lower()
        if source in {"", "-", "n/a", "none"}:
            blocked.append(f"Implementation manifest {row_id} must name why the artifact is required.")
        for artifact in split_artifacts(row.get("artifact", "")):
            if not looks_like_path(artifact):
                continue
            resolved = resolve_artifact_path(repo, artifact)
            if not resolved.exists():
                blocked.append(f"Implementation manifest {row_id} artifact does not exist: {posix(resolved.relative_to(repo)) if resolved.is_relative_to(repo) else resolved}")

    design_modules = extract_design_modules(design_doc)
    for module in design_modules:
        if module not in covered_modules:
            blocked.append(f"Design module is missing from implementation manifest: {module}")

    design_artifacts = extract_design_artifacts(design_doc)
    for artifact in design_artifacts:
        if not any(row_mentions(row, artifact) for row in rows):
            blocked.append(f"Design artifact is missing from implementation manifest: {artifact}")

    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "implementation_manifest": str(manifest_path),
        "rows": len(rows),
        "required_rows": required_rows,
        "design_modules": design_modules,
        "design_artifacts": design_artifacts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--design-doc", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(args.repo, args.manifest, args.design_doc)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Implementation manifest: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
