#!/usr/bin/env python3
"""GitNexus-first cross-service dependency scanner for Java/Spring repositories."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import SKIP_DIRS, posix  # noqa: E402

HTTP_MAPPING_RE = re.compile(r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\((.*?)\))?", re.S)
VALUE_FIELD_RE = re.compile(r"@Value\s*\(\s*\"\$\{([^}:]+)(?::[^}]*)?}\"\s*\)\s*(?:private|protected|public)?\s*(?:final\s+)?(?:String|URI|URL)\s+(\w+)", re.S)
ENV_PROPERTY_RE = re.compile(r"(\w+)\s*=\s*[^;\n]*getProperty\s*\(\s*\"([^\"]+)\"", re.S)
STRING_CONSTANT_RE = re.compile(r"(?:public|private|protected|static|final|\s)*String\s+(\w+)\s*=\s*\"([^\"]+)\"")
PUBLISH_RE = re.compile(r"\b(?:\w*dmq\w*|\w*Dmq\w*|\w*Template|\w*Producer)\s*\.\s*(send|publish|produce|convertAndSend)\s*\(([^;]+)\)", re.S)
LISTENER_RE = re.compile(r"@(DmqListener|KafkaListener|RocketMQMessageListener|JmsListener)\s*\((.*?)\)", re.S)
CROSS_SERVICE_RE = re.compile(
    r"\b(cross-service|dmq|topic|event|message|callback)\b|跨服务|微服务|消息|事件|契约",
    re.IGNORECASE,
)


def java_parser_backend() -> dict:
    try:
        import tree_sitter  # type: ignore  # noqa: F401
        import tree_sitter_java  # type: ignore  # noqa: F401
    except Exception:
        return {
            "backend": "regex-fallback",
            "tree_sitter_available": False,
            "warning": "tree-sitter Java parser is unavailable; deterministic scan uses regex fallback and may miss nested Java syntax.",
        }
    return {
        "backend": "tree-sitter-java-available",
        "tree_sitter_available": True,
        "warning": "",
    }


def walk_files(root: Path):
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        base = Path(current)
        for name in files:
            yield base / name


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")


def service_slug(service: str) -> str:
    return service.replace("\\", "/").rstrip("/").split("/")[-1]


def detect_services(repo: Path) -> list[str]:
    services: set[str] = set()
    services_root = repo / "services"
    if services_root.exists():
        for child in services_root.iterdir():
            if child.is_dir() and ((child / "pom.xml").exists() or (child / "src").exists()):
                services.add(posix(child.relative_to(repo)))
    for pom in repo.glob("*/pom.xml"):
        module = pom.parent
        if module != repo and (module / "src").exists():
            services.add(posix(module.relative_to(repo)))
    return sorted(services)


def service_for_path(repo: Path, services: list[str], path: Path) -> str | None:
    rel = posix(path.relative_to(repo))
    matches = [service for service in services if rel == service or rel.startswith(service + "/")]
    return sorted(matches, key=len, reverse=True)[0] if matches else None


def parse_properties(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        separator = "=" if "=" in line else (":" if ":" in line and not line.endswith(":") else "")
        if not separator:
            continue
        key, value = line.split(separator, 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def parse_yaml(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    stack: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parts = [part for _, part in stack] + [key]
        if value:
            values[".".join(parts)] = value
        else:
            stack.append((indent, key))
    return values


def load_config(repo: Path, services: list[str]) -> dict[str, list[dict]]:
    result = {service: [] for service in services}
    for path in walk_files(repo):
        if path.name.startswith("application") and path.suffix.lower() in {".properties", ".yml", ".yaml"}:
            service = service_for_path(repo, services, path)
            if not service:
                continue
            text = read_text(path)
            values = parse_yaml(text) if path.suffix.lower() in {".yml", ".yaml"} else parse_properties(text)
            for key, value in values.items():
                result[service].append({
                    "key": key,
                    "value": value,
                    "path": posix(path.relative_to(repo)),
                })
    return result


def annotation_path(args: str | None) -> str:
    if not args:
        return ""
    match = re.search(r"(?:value|path)\s*=\s*\"([^\"]+)\"", args)
    if match:
        return match.group(1)
    match = re.search(r"\"([^\"]+)\"", args)
    return match.group(1) if match else ""


def normalize_path(*parts: str) -> str:
    combined = "/".join(part.strip("/") for part in parts if part and part != "/")
    return "/" + combined.strip("/") if combined.strip("/") else "/"


def extract_routes(repo: Path, services: list[str]) -> list[dict]:
    routes: list[dict] = []
    for path in walk_files(repo):
        if path.suffix != ".java":
            continue
        service = service_for_path(repo, services, path)
        if not service:
            continue
        text = read_text(path)
        class_match = re.search(r"\bclass\s+(\w+)", text)
        class_pos = class_match.start() if class_match else 0
        class_name = class_match.group(1) if class_match else path.stem
        class_base = ""
        for mapping in HTTP_MAPPING_RE.finditer(text[:class_pos]):
            class_base = annotation_path(mapping.group(2))
        for mapping in HTTP_MAPPING_RE.finditer(text[class_pos:]):
            method_name = mapping.group(1)
            method = "ANY" if method_name == "RequestMapping" else method_name.replace("Mapping", "").upper()
            route_path = normalize_path(class_base, annotation_path(mapping.group(2)))
            routes.append({
                "service": service,
                "method": method,
                "path": route_path,
                "symbol": f"{class_name}.{method.lower()}",
                "evidence_refs": [f"{posix(path.relative_to(repo))}:@{method_name}"],
            })
    return routes


def config_lookup(configs: dict[str, list[dict]], service: str) -> dict[str, dict]:
    return {entry["key"]: entry for entry in configs.get(service, [])}


def resolve_url_target(value: str, services: list[str]) -> tuple[str | None, str, str | None]:
    placeholder = re.search(r"\$\{([^}:]+)", value)
    if placeholder:
        return None, "", placeholder.group(1)
    parsed = urlparse(value)
    host = parsed.hostname or ""
    base_path = parsed.path or ""
    if not host:
        return None, base_path, None
    host_key = host.lower().replace("_", "-")
    for service in services:
        slug = service_slug(service).lower()
        if host_key == slug or host_key.startswith(slug + ".") or slug in host_key:
            return service, base_path, None
    return None, base_path, None


def variable_config_refs(text: str) -> dict[str, str]:
    refs = {var: key for key, var in VALUE_FIELD_RE.findall(text)}
    refs.update({var: key for var, key in ENV_PROPERTY_RE.findall(text)})
    return refs


def extract_http_clients(repo: Path, services: list[str], configs: dict[str, list[dict]]) -> list[dict]:
    clients: list[dict] = []
    referenced_keys: set[tuple[str, str]] = set()
    for path in walk_files(repo):
        if path.suffix != ".java":
            continue
        service = service_for_path(repo, services, path)
        if not service:
            continue
        text = read_text(path)
        refs = variable_config_refs(text)
        config_by_key = config_lookup(configs, service)
        for var, key in refs.items():
            entry = config_by_key.get(key)
            if not entry:
                continue
            referenced_keys.add((service, key))
            target_service, base_path, unresolved = resolve_url_target(entry["value"], services)
            call_paths = re.findall(rf"\b{re.escape(var)}\s*\+\s*\"([^\"]+)\"", text)
            if not call_paths:
                call_paths = [""]
            for call_path in call_paths:
                clients.append({
                    "service": service,
                    "config_key": key,
                    "config_value": entry["value"],
                    "config_path": entry["path"],
                    "target_service": target_service,
                    "base_path": base_path,
                    "call_path": call_path,
                    "unresolved_placeholder": unresolved,
                    "evidence_refs": [f"{posix(path.relative_to(repo))}:{var}", entry["path"]],
                })
        for raw_url, path_suffix in re.findall(r"\"(https?://[^\"]+?)\"\s*\+\s*\"([^\"]+)\"", text):
            target_service, base_path, unresolved = resolve_url_target(raw_url, services)
            clients.append({
                "service": service,
                "config_key": None,
                "config_value": raw_url,
                "config_path": None,
                "target_service": target_service,
                "base_path": base_path,
                "call_path": path_suffix,
                "unresolved_placeholder": unresolved,
                "evidence_refs": [posix(path.relative_to(repo))],
            })
    for service, entries in configs.items():
        for entry in entries:
            key = entry["key"]
            if (service, key) in referenced_keys:
                continue
            if not re.search(r"(?:^|[.-])(base-url|url|endpoint|host)$", key, re.IGNORECASE):
                continue
            target_service, base_path, unresolved = resolve_url_target(entry["value"], services)
            if unresolved or target_service:
                clients.append({
                    "service": service,
                    "config_key": key,
                    "config_value": entry["value"],
                    "config_path": entry["path"],
                    "target_service": target_service,
                    "base_path": base_path,
                    "call_path": "",
                    "unresolved_placeholder": unresolved,
                    "evidence_refs": [entry["path"]],
                })
    return clients


def route_match(routes: list[dict], target_service: str | None, target_path: str) -> dict | None:
    for route in routes:
        if target_service and route["service"] == target_service and route["path"] == target_path:
            return route
    return None


def http_dependencies(clients: list[dict], routes: list[dict]) -> tuple[list[dict], list[str]]:
    dependencies: list[dict] = []
    questions: list[str] = []
    for client in clients:
        target_path = normalize_path(client.get("base_path", ""), client.get("call_path", ""))
        target_route = route_match(routes, client.get("target_service"), target_path)
        if client.get("unresolved_placeholder"):
            questions.append(
                f"Resolve HTTP config placeholder {client['unresolved_placeholder']} for {client['service']} ({client['config_key']})."
            )
        if not client.get("target_service"):
            questions.append(f"Confirm target service for HTTP config {client.get('config_key') or client.get('config_value')} in {client['service']}.")
        dependencies.append({
            "kind": "http",
            "source_service": client["service"],
            "target_service": client.get("target_service"),
            "target_route": target_path,
            "config_key": client.get("config_key"),
            "confidence": "verified" if client.get("target_service") and target_route else "candidate",
            "evidence_refs": client["evidence_refs"] + (target_route["evidence_refs"] if target_route else []),
            "unresolved": bool(client.get("unresolved_placeholder") or not client.get("target_service") or not target_route),
        })
    return dependencies, questions


def class_name(text: str, path: Path) -> str:
    match = re.search(r"\bclass\s+(\w+)", text)
    return match.group(1) if match else path.stem


def split_args(args: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    previous = ""
    for char in args:
        if char == '"' and previous != "\\":
            in_string = not in_string
        elif not in_string:
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth = max(0, depth - 1)
            elif char == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
                previous = char
                continue
        current.append(char)
        previous = char
    if current:
        parts.append("".join(current).strip())
    return parts


def constants(repo: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in walk_files(repo):
        if path.suffix != ".java":
            continue
        text = read_text(path)
        owner = class_name(text, path)
        for name, value in STRING_CONSTANT_RE.findall(text):
            result[name] = value
            result[f"{owner}.{name}"] = value
    return result


def resolve_expr(expr: str, consts: dict[str, str]) -> str | None:
    expr = expr.strip()
    if expr.startswith('"') and expr.endswith('"'):
        return expr.strip('"')
    return consts.get(expr) or consts.get(expr.split(".")[-1])


def annotation_attr(args: str, names: tuple[str, ...], consts: dict[str, str]) -> str | None:
    for name in names:
        match = re.search(rf"\b{name}\s*=\s*(\"[^\"]+\"|[\w.]+)", args)
        if match:
            return resolve_expr(match.group(1), consts)
    return None


def extract_messaging(repo: Path, services: list[str]) -> tuple[list[dict], list[dict]]:
    consts = constants(repo)
    producers: list[dict] = []
    consumers: list[dict] = []
    for path in walk_files(repo):
        if path.suffix != ".java":
            continue
        service = service_for_path(repo, services, path)
        if not service:
            continue
        text = read_text(path)
        owner = class_name(text, path)
        for match in PUBLISH_RE.finditer(text):
            args = split_args(match.group(2))
            topic = resolve_expr(args[0], consts) if args else None
            tag = resolve_expr(args[1], consts) if len(args) > 1 else None
            if topic:
                producers.append({
                    "service": service,
                    "topic": topic,
                    "tag": tag,
                    "symbol": f"{owner}.{match.group(1)}",
                    "evidence_refs": [f"{posix(path.relative_to(repo))}:{match.group(1)}"],
                })
        for match in LISTENER_RE.finditer(text):
            args = match.group(2)
            topic = annotation_attr(args, ("topic", "topics", "destination"), consts)
            tag = annotation_attr(args, ("tag", "tags", "selectorExpression"), consts)
            group = annotation_attr(args, ("group", "consumerGroup", "groupId"), consts)
            if topic:
                consumers.append({
                    "service": service,
                    "topic": topic,
                    "tag": tag,
                    "group": group,
                    "symbol": f"{owner}.{match.group(1)}",
                    "evidence_refs": [f"{posix(path.relative_to(repo))}:@{match.group(1)}"],
                })
    return producers, consumers


def dmq_dependencies(producers: list[dict], consumers: list[dict]) -> tuple[list[dict], list[str]]:
    dependencies: list[dict] = []
    questions: list[str] = []
    for producer in producers:
        matches = [consumer for consumer in consumers if consumer["topic"] == producer["topic"]]
        if not matches:
            questions.append(f"Confirm consumers for DMQ topic {producer['topic']} produced by {producer['service']}.")
        for consumer in matches:
            mismatch = producer.get("tag") and consumer.get("tag") and producer["tag"] != consumer["tag"]
            if mismatch:
                questions.append(
                    f"Confirm DMQ tag mapping for topic {producer['topic']}: producer tag {producer['tag']} vs consumer tag {consumer['tag']}."
                )
            dependencies.append({
                "kind": "dmq",
                "source_service": producer["service"],
                "target_service": consumer["service"],
                "topic": producer["topic"],
                "tag": producer.get("tag") or consumer.get("tag"),
                "consumer_group": consumer.get("group"),
                "confidence": "ambiguous" if mismatch else "verified",
                "evidence_refs": producer["evidence_refs"] + consumer["evidence_refs"],
                "unresolved": bool(mismatch),
            })
    return dependencies, questions


def run_command(command: list[str], cwd: Path) -> dict:
    try:
        completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, shell=False)
        return {
            "command": " ".join(command),
            "exit_code": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        }
    except FileNotFoundError as error:
        return {"command": " ".join(command), "exit_code": 127, "stdout_tail": "", "stderr_tail": str(error)}


def gitnexus_evidence(
    repo: Path,
    dependencies: list[dict],
    gitnexus_mode: str,
    command_runner=run_command,
    gitnexus_available: bool | None = None,
    max_seeds: int = 12,
) -> tuple[dict, list[str]]:
    available = bool(shutil.which("gitnexus")) if gitnexus_available is None else gitnexus_available
    result = {
        "mode": gitnexus_mode,
        "available": available,
        "primary": True,
        "suggested_refresh_command": "gitnexus analyze .",
        "verified": False,
        "evidence": [],
    }
    warnings: list[str] = []
    if gitnexus_mode == "off":
        result["verified"] = False
        return result, warnings
    if not available:
        warnings.append("GitNexus is unavailable; dependency evidence falls back to deterministic scan and should be treated as insufficient for high-risk cross-service changes.")
        return result, warnings

    seeds: list[str] = []
    for dependency in dependencies:
        for value in (
            dependency.get("topic"),
            dependency.get("config_key"),
            dependency.get("target_route"),
            dependency.get("source_service"),
            dependency.get("target_service"),
        ):
            if value and value not in seeds:
                seeds.append(str(value))
    evidence: list[dict] = [command_runner(["gitnexus", "analyze", "."], repo)]
    for seed in seeds[:max_seeds]:
        evidence.append(command_runner(["gitnexus", "context", seed], repo))
        evidence.append(command_runner(["gitnexus", "impact", seed], repo))
    result["evidence"] = evidence
    result["verified"] = bool(evidence) and all(item.get("exit_code") == 0 for item in evidence)
    if gitnexus_mode == "strict" and not result["verified"]:
        warnings.append("GitNexus evidence did not fully verify; inspect context/impact output before implementation.")
    return result, warnings


def write_dependency_reports(repo: Path, result: dict, output_dir: Path | None = None) -> dict:
    target = output_dir or repo / "knowledge-graph"
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "cross-service-dependencies.json"
    md_path = target / "cross-service-dependencies.md"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Cross-Service Dependencies",
        "",
        "GitNexus is the primary code-evidence engine. Graphify is auxiliary for design docs, ADRs, diagrams, and semantic context.",
        "",
        "## Dependencies",
    ]
    for dependency in result["dependencies"]:
        if dependency["kind"] == "http":
            lines.append(f"- HTTP `{dependency['source_service']}` -> `{dependency.get('target_service')}` `{dependency.get('target_route')}` ({dependency['confidence']})")
        else:
            lines.append(f"- DMQ `{dependency['source_service']}` -> `{dependency.get('target_service')}` via topic `{dependency.get('topic')}` ({dependency['confidence']})")
    lines.extend(["", "## Unresolved Questions"])
    lines.extend([f"- {question}" for question in result["unresolved_questions"]] or ["- None"])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def scan(
    repo: Path,
    gitnexus_mode: str = "auto",
    graphify_mode: str = "auxiliary",
    write_reports: bool = True,
    output_dir: Path | None = None,
    command_runner=run_command,
    gitnexus_available: bool | None = None,
) -> dict:
    repo = repo.resolve()
    services = detect_services(repo)
    configs = load_config(repo, services)
    routes = extract_routes(repo, services)
    clients = extract_http_clients(repo, services, configs)
    http_edges, http_questions = http_dependencies(clients, routes)
    producers, consumers = extract_messaging(repo, services)
    dmq_edges, dmq_questions = dmq_dependencies(producers, consumers)
    dependencies = http_edges + dmq_edges
    unresolved = sorted(dict.fromkeys(http_questions + dmq_questions))
    parser_backend = java_parser_backend()
    gitnexus, gitnexus_warnings = gitnexus_evidence(
        repo,
        dependencies or [{"source_service": service} for service in services],
        gitnexus_mode,
        command_runner,
        gitnexus_available,
    )
    warnings = list(gitnexus_warnings)
    if parser_backend.get("warning"):
        warnings.append(str(parser_backend["warning"]))
    result = {
        "repo": str(repo),
        "ready": not unresolved,
        "services": services,
        "tool_priority": ["gitnexus", "deterministic-scan", "graphify"],
        "java_parser": parser_backend,
        "gitnexus": gitnexus,
        "graphify": {
            "mode": graphify_mode,
            "role": "auxiliary semantic/document evidence only; inferred or ambiguous edges become clarification questions.",
        },
        "http": {"clients": clients, "providers": routes},
        "dmq": {"producers": producers, "consumers": consumers},
        "dependencies": dependencies,
        "unresolved_questions": unresolved,
        "warnings": warnings,
        "report_paths": {},
    }
    if write_reports:
        result["report_paths"] = write_dependency_reports(repo, result, output_dir)
    return result


def design_requires_dependency_report(design_text: str) -> bool:
    services = sorted(set(re.findall(r"services/[A-Za-z0-9._-]+", design_text)))
    return len(services) >= 2 or bool(CROSS_SERVICE_RE.search(design_text))


def validate_dependency_report(repo: Path, report_path: Path | None, design_doc: Path | None = None) -> dict:
    blocked: list[str] = []
    design_requires = False
    if design_doc:
        design_path = design_doc if design_doc.is_absolute() else repo / design_doc
        if design_path.exists():
            design_requires = design_requires_dependency_report(read_text(design_path))
    resolved = report_path if report_path and report_path.is_absolute() else (repo / report_path if report_path else None)
    if not resolved:
        if design_requires:
            blocked.append("Cross-service design requires a dependency report via --dependency-report.")
        return {
            "ready": not blocked,
            "required": design_requires,
            "path": None,
            "unresolved_questions": [],
            "blocked_reasons": blocked,
        }
    if not resolved.exists():
        blocked.append(f"Dependency report not found: {resolved}")
        return {"ready": False, "required": design_requires, "path": str(resolved), "unresolved_questions": [], "blocked_reasons": blocked}
    try:
        data = json.loads(read_text(resolved))
    except json.JSONDecodeError as error:
        blocked.append(f"Dependency report is not valid JSON: {resolved}: {error}")
        return {"ready": False, "required": design_requires, "path": str(resolved), "unresolved_questions": [], "blocked_reasons": blocked}
    questions = [str(question) for question in data.get("unresolved_questions", [])]
    for question in questions:
        blocked.append(f"Unresolved dependency question: {question}")
    for index, dependency in enumerate(data.get("dependencies", []), start=1):
        confidence = str(dependency.get("confidence", "")).lower()
        if dependency.get("unresolved") or confidence in {"ambiguous", "candidate", "inferred"}:
            label = dependency.get("topic") or dependency.get("target_route") or dependency.get("config_key") or dependency.get("kind") or index
            blocked.append(f"Low-confidence dependency remains unresolved: {label}")
    if data.get("ready") is False and not questions:
        blocked.append(f"Dependency report is not ready: {resolved}")
    return {
        "ready": not blocked,
        "required": design_requires,
        "path": str(resolved),
        "unresolved_questions": questions,
        "dependencies_count": len(data.get("dependencies", [])),
        "gitnexus_verified": bool(data.get("gitnexus", {}).get("verified")),
        "blocked_reasons": blocked,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--gitnexus-mode", choices=["auto", "strict", "optional", "off"], default="auto")
    parser.add_argument("--graphify-mode", choices=["auxiliary", "off"], default="auxiliary")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = scan(
        args.repo,
        gitnexus_mode=args.gitnexus_mode,
        graphify_mode=args.graphify_mode,
        write_reports=not args.no_write,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
