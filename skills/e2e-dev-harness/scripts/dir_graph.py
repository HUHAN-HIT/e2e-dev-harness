"""Read-only repository directory graph contract validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DIR_GRAPH_SCHEMA = "e2e-dev-harness.dir-graph.v1"
DIR_GRAPH_PATH = Path(".e2e") / "dir-graph.yaml"
LIST_MAP_KEYS = {"repositories", "directories", "protected_paths", "pipeline", "skill_contracts"}
MAP_KEYS = {"state_machine"}


def _strip_comment(line: str) -> str:
    in_quote = ""
    out: list[str] = []
    for char in line:
        if char in {"'", '"'}:
            in_quote = "" if in_quote == char else (char if not in_quote else in_quote)
        if char == "#" and not in_quote:
            break
        out.append(char)
    return "".join(out).rstrip()


def _scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_scalar(item.strip()) for item in inner.split(",") if item.strip()]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    return value.strip("'\"")


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    data: dict[str, Any] = {}
    current_top = ""
    current_item: dict[str, Any] | None = None
    current_nested_key = ""

    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0:
            key, sep, value = stripped.partition(":")
            if not sep:
                continue
            current_top = key.strip()
            current_item = None
            current_nested_key = ""
            if value.strip():
                data[current_top] = _scalar(value)
            elif current_top in LIST_MAP_KEYS:
                data[current_top] = []
            elif current_top in MAP_KEYS:
                data[current_top] = {}
            else:
                data[current_top] = {}
            continue

        if not current_top:
            continue
        container = data.setdefault(current_top, [] if current_top in LIST_MAP_KEYS else {})
        if indent == 2 and stripped.startswith("- "):
            item_text = stripped[2:].strip()
            current_nested_key = ""
            if isinstance(container, list):
                if ":" in item_text:
                    key, _, value = item_text.partition(":")
                    current_item = {key.strip(): _scalar(value)}
                    container.append(current_item)
                else:
                    current_item = None
                    container.append(_scalar(item_text))
            continue

        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if indent == 2 and isinstance(container, dict):
            if value:
                container[key] = _scalar(value)
                current_nested_key = ""
            else:
                container[key] = {}
                current_nested_key = key
            continue
        if indent == 4 and current_item is not None:
            current_item[key] = _scalar(value)
            continue
        if indent == 4 and isinstance(container, dict) and current_nested_key:
            nested = container.setdefault(current_nested_key, {})
            if isinstance(nested, dict):
                nested[key] = _scalar(value)

    return data


def _posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _repo_path(repo: Path, raw: object, label: str) -> tuple[Path | None, str | None]:
    if not isinstance(raw, str) or not raw.strip():
        return None, f"Dir graph {label} path is missing."
    path = Path(raw.strip())
    resolved = (path if path.is_absolute() else repo / path).resolve()
    try:
        resolved.relative_to(repo.resolve())
    except ValueError:
        return None, f"Dir graph {label} path resolves outside repository: {raw}"
    return resolved, None


def load_dir_graph(repo: Path, path: Path | None = None) -> dict[str, Any]:
    graph_path = path or repo / DIR_GRAPH_PATH
    result: dict[str, Any] = {
        "schema": DIR_GRAPH_SCHEMA,
        "exists": graph_path.exists(),
        "path": _posix(graph_path if graph_path.is_absolute() else graph_path),
        "graph": {},
        "blocked_reasons": [],
    }
    if not graph_path.exists():
        return result
    try:
        result["graph"] = _parse_simple_yaml(graph_path.read_text(encoding="utf-8"))
    except OSError as error:
        result["blocked_reasons"] = [f"Could not read dir graph contract: {error}"]
    return result


def validate_dir_graph(repo: Path, graph: dict[str, Any]) -> list[str]:
    blocked: list[str] = []
    if graph.get("schema") != DIR_GRAPH_SCHEMA:
        blocked.append(f"Dir graph schema must be {DIR_GRAPH_SCHEMA}.")

    for item in graph.get("directories", []) or []:
        if not isinstance(item, dict):
            blocked.append("Dir graph directories entries must be objects.")
            continue
        resolved, error = _repo_path(repo, item.get("path"), "directory")
        if error:
            blocked.append(error)
            continue
        if item.get("required") is True and resolved and not resolved.exists():
            blocked.append(f"Dir graph required directory is missing: {_posix(resolved.relative_to(repo.resolve()))}")

    for item in graph.get("protected_paths", []) or []:
        if not isinstance(item, dict):
            blocked.append("Dir graph protected_paths entries must be objects.")
            continue
        _, error = _repo_path(repo, item.get("path"), "protected")
        if error:
            blocked.append(error)

    state_machine = graph.get("state_machine", {}) if isinstance(graph.get("state_machine"), dict) else {}
    lifecycles = state_machine.get("lifecycles", [])
    if not isinstance(lifecycles, list):
        blocked.append("Dir graph state_machine.lifecycles must be a list.")
        lifecycles = []
    from run_state import GATE_TRANSITIONS, LIFECYCLE  # noqa: PLC0415

    missing_lifecycles = sorted(str(item) for item in LIFECYCLE - set(str(item) for item in lifecycles))
    if missing_lifecycles:
        blocked.append("Dir graph state machine is missing lifecycles: " + ", ".join(missing_lifecycles))

    declared_transitions = state_machine.get("gate_transitions", {})
    if not isinstance(declared_transitions, dict):
        blocked.append("Dir graph state_machine.gate_transitions must be an object.")
        declared_transitions = {}
    for gate, target in GATE_TRANSITIONS.items():
        if str(declared_transitions.get(gate, "")) != target:
            blocked.append(f"Dir graph gate transition drift: {gate} must transition to {target}.")

    from coordinator_flow import BLUEPRINT_STEPS  # noqa: PLC0415

    declared_pipeline = [
        (str(item.get("lifecycle", "")), str(item.get("phase", "")))
        for item in graph.get("pipeline", []) or []
        if isinstance(item, dict)
    ]
    expected_pipeline = [(lifecycle, phase) for lifecycle, phase, _ in BLUEPRINT_STEPS]
    if declared_pipeline != expected_pipeline:
        blocked.append("Dir graph pipeline does not match coordinator BLUEPRINT_STEPS.")

    contracts = graph.get("skill_contracts", [])
    if not isinstance(contracts, list) or not contracts:
        blocked.append("Dir graph skill_contracts must declare at least one role contract.")
    for item in contracts or []:
        if not isinstance(item, dict):
            blocked.append("Dir graph skill_contracts entries must be objects.")
            continue
        if not str(item.get("role", "")).strip():
            blocked.append("Dir graph skill contract role is missing.")

    from orchestration_plan import ROLE_TEMPLATE_FILES  # noqa: PLC0415

    declared_roles = {
        str(item.get("role", "")).strip()
        for item in contracts or []
        if isinstance(item, dict) and str(item.get("role", "")).strip()
    }
    expected_roles = set(ROLE_TEMPLATE_FILES)
    missing_roles = sorted(expected_roles - declared_roles)
    if missing_roles:
        blocked.append("Dir graph skill_contracts missing worker role contracts: " + ", ".join(missing_roles))
    unknown_roles = sorted(declared_roles - expected_roles)
    if unknown_roles:
        blocked.append("Dir graph skill_contracts declare unknown worker roles: " + ", ".join(unknown_roles))

    return blocked


def _role_matches(agent: str, role: str) -> bool:
    agent = agent.strip()
    role = role.strip()
    return bool(agent and role and (agent == role or agent.startswith(role + "-")))


def _role_contract(graph: dict[str, Any], agent: str) -> dict[str, Any] | None:
    for item in graph.get("skill_contracts", []) or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip()
        if _role_matches(agent, role):
            return item
    return None


def _scope_values(contract: dict[str, Any]) -> list[str]:
    raw = contract.get("write_scopes", contract.get("allowed_outputs", contract.get("write_scope", "")))
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _scope_regex(scope: str) -> re.Pattern[str] | None:
    normalized = scope.replace("\\", "/").strip().strip("/")
    if not normalized or normalized == "claimed-service-scope":
        return None
    escaped = re.escape(normalized)
    escaped = escaped.replace(re.escape("<run>"), r"[^/]+")
    escaped = escaped.replace(re.escape("<service>"), r"[^/]+")
    escaped = escaped.replace(r"\*", r"[^/]*")
    return re.compile(rf"^{escaped}(?:/.*)?$")


def _output_allowed(output: str, scopes: list[str]) -> bool:
    normalized = output.replace("\\", "/").strip().strip("/")
    if not normalized:
        return True
    regexes = [regex for regex in (_scope_regex(scope) for scope in scopes) if regex is not None]
    if not regexes:
        return True
    return any(regex.match(normalized) for regex in regexes)


def context_pack_role_blockers(repo: Path, task: dict[str, Any], outputs: list[Any]) -> list[str]:
    loaded = load_dir_graph(repo)
    if not loaded["exists"] or loaded.get("blocked_reasons"):
        return []
    graph = loaded.get("graph", {})
    if not isinstance(graph, dict):
        return []
    agent = str(task.get("agent", "")).strip()
    contract = _role_contract(graph, agent)
    if not contract:
        return []
    scopes = _scope_values(contract)
    blocked: list[str] = []
    for output in outputs:
        if not isinstance(output, str):
            continue
        if not _output_allowed(output, scopes):
            blocked.append(
                f"Context pack output violates dir graph role contract for {agent}: {output}"
            )
    return blocked


def dir_graph_contract_blockers(repo: Path, run_state_path: Path | str | None = None) -> list[str]:
    del run_state_path
    repo = repo.resolve()
    loaded = load_dir_graph(repo)
    if not loaded["exists"]:
        return []
    if loaded.get("blocked_reasons"):
        return [str(reason) for reason in loaded["blocked_reasons"]]
    graph = loaded.get("graph", {})
    if not isinstance(graph, dict):
        return ["Dir graph contract must parse to an object."]
    return validate_dir_graph(repo, graph)
