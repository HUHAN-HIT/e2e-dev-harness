#!/usr/bin/env python3
"""Lightweight Spring Framework static checks for completion gates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import SKIP_DIRS, posix  # noqa: E402


COMPONENT_ANNOTATIONS = {
    "Component",
    "Service",
    "Repository",
    "Controller",
    "RestController",
    "Configuration",
}
CLASS_RE = re.compile(
    r"(?P<annotations>(?:\s*@[\w.]+(?:\([^)]*\))?)*\s*)"
    r"\b(?P<visibility>public|protected|private)?\s*"
    r"(?P<modifier>abstract|final|sealed|non-sealed)?\s*"
    r"(?P<kind>class|interface|record)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)
BEAN_RE = re.compile(
    r"@Bean(?:\s*\([^)]*\))?\s+"
    r"(?:(?:public|protected|private)\s+)?"
    r"(?:static\s+)?"
    r"(?P<return_type>[A-Za-z_][A-Za-z0-9_.$<>?,\s]+?)\s+"
    r"[A-Za-z_][A-Za-z0-9_]*\s*\(",
    re.MULTILINE,
)


@dataclass
class JavaType:
    name: str
    kind: str
    path: Path
    component: bool


def iter_java_files(repo: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(repo.rglob("*.java")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def annotation_names(text: str) -> set[str]:
    names: set[str] = set()
    for match in re.finditer(r"@([\w.]+)", text):
        names.add(match.group(1).split(".")[-1])
    return names


def raw_type(type_text: str) -> str:
    text = re.sub(r"<.*>", "", type_text)
    text = text.replace("...", "").strip()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def split_params(params: str) -> list[str]:
    result: list[str] = []
    current: list[str] = []
    depth = 0
    for char in params:
        if char == "<":
            depth += 1
        elif char == ">" and depth:
            depth -= 1
        elif char == "," and depth == 0:
            item = "".join(current).strip()
            if item:
                result.append(item)
            current = []
            continue
        current.append(char)
    item = "".join(current).strip()
    if item:
        result.append(item)
    return result


def parameter_type(param: str) -> str | None:
    text = re.sub(r"@\w+(?:\([^)]*\))?", " ", param)
    tokens = [token for token in text.replace("final ", " ").split() if token]
    if len(tokens) < 2:
        return None
    return raw_type(tokens[-2])


def constructor_params(text: str, class_name: str) -> list[str]:
    pattern = re.compile(
        rf"(?:(?:public|protected|private)\s+)?{re.escape(class_name)}\s*\((?P<params>[^)]*)\)",
        re.MULTILINE,
    )
    params: list[str] = []
    for match in pattern.finditer(text):
        for param in split_params(match.group("params")):
            param_type = parameter_type(param)
            if param_type:
                params.append(param_type)
    return params


def collect_types(repo: Path) -> tuple[dict[str, JavaType], set[str], dict[Path, str]]:
    types: dict[str, JavaType] = {}
    bean_types: set[str] = set()
    texts: dict[Path, str] = {}
    for path in iter_java_files(repo):
        text = path.read_text(encoding="utf-8", errors="replace")
        texts[path] = text
        for match in CLASS_RE.finditer(text):
            names = annotation_names(match.group("annotations"))
            types[match.group("name")] = JavaType(
                name=match.group("name"),
                kind=match.group("kind"),
                path=path,
                component=bool(names & COMPONENT_ANNOTATIONS),
            )
        for match in BEAN_RE.finditer(text):
            bean_types.add(raw_type(match.group("return_type")))
    return types, bean_types, texts


def validate(repo: Path) -> dict:
    repo = repo.resolve()
    blocked: list[str] = []
    warnings: list[str] = []
    types, bean_types, texts = collect_types(repo)
    injection_count = 0

    for java_type in sorted(types.values(), key=lambda item: (posix(item.path), item.name)):
        if not java_type.component:
            continue
        text = texts[java_type.path]
        for param_type in constructor_params(text, java_type.name):
            injected = types.get(param_type)
            if not injected:
                continue
            if injected.kind == "interface":
                warnings.append(
                    f"{java_type.name} injects interface {param_type}; verify an implementation or @Bean is available."
                )
                continue
            injection_count += 1
            if not injected.component and param_type not in bean_types:
                blocked.append(
                    f"Injected type {param_type} used by {java_type.name} is declared in "
                    f"{posix(injected.path.relative_to(repo))} but is not a Spring component or @Bean."
                )

    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "checked_java_types": len(types),
        "checked_constructor_injections": injection_count,
        "bean_types": sorted(bean_types),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(args.repo)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Spring static check: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
