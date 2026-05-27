#!/usr/bin/env python3
"""Validate semantic reviewer-agent artifacts before completion."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import clarification_gate  # noqa: E402


REQUIRED_FIELDS = {
    "phase": "Phase",
    "reviewer": "Reviewer",
    "review_request": "Review Request",
    "developer_agent": "Developer Agent",
    "reviewer_agent": "Reviewer Agent",
    "reviewer_session": "Reviewer Session",
    "reviewer_invocation": "Reviewer Invocation",
    "request_hash": "Request Hash",
    "independence": "Independence",
    "context_boundary": "Context Boundary",
    "no_code_changes": "No Code Changes",
    "scope": "Scope",
    "inputs_reviewed": "Inputs Reviewed",
    "findings": "Findings",
    "required_rework": "Required Rework",
    "status": "Status",
}
PHASE_ALIASES = {
    "r1": "design",
    "design-review": "design",
    "requirements-review": "design",
    "r2": "test",
    "test-review": "test",
    "red-test-review": "test",
    "r3": "implementation",
    "implementation-review": "implementation",
    "code-review": "implementation",
}
PASS_STATUSES = {"approved", "verified", "clear", "passed"}
PASS_WITH_REWORK_STATUSES = {"approved-with-rework", "verified-with-rework"}
BLOCK_STATUSES = {"open", "in-progress", "in_progress", "blocked", "changes-requested", "needs-rework"}
NONE_VALUES = {"", "-", "none", "n/a", "na", "no", "no findings", "no rework", "无", "没有"}
INDEPENDENT_VALUES = {"independent-agent"}
SELF_REVIEW_VALUES = {"self-review", "same-agent", "developer-agent", "same-session"}
NO_CODE_CHANGE_VALUES = {"confirmed", "true", "yes", "no-code-changes", "read-only", "none"}
REQUEST_REQUIRED_FIELDS = {
    "phase": "Phase",
    "reviewer_role": "Reviewer Role",
    "context_package": "Context Package",
    "forbidden": "Forbidden",
    "output": "Output",
    "developer_agent": "Developer Agent",
    "reviewer_agent": "Reviewer Agent",
    "reviewer_invocation": "Reviewer Invocation",
}
FIELD_RE = re.compile(r"^\s*-?\s*([A-Za-z][A-Za-z _-]*):\s*(.*?)\s*$")
PLACEHOLDER_RE = re.compile(r"^\s*(<[^>]+>|\[[^\]]+\]|todo|tbd|unknown|draft|placeholder)\s*$", re.IGNORECASE)
CHECKED_ITEM_RE = re.compile(r"^\s*[-*]\s*\[[xX]\]\s*`?([A-Za-z0-9][A-Za-z0-9._/-]*)`?")
CODE_PATH_HEADING_RE = re.compile(r"(?im)^\s*#{2,4}\s+code path trace\s*$")
MESSAGING_PATH_HEADING_RE = re.compile(r"(?im)^\s*#{2,4}\s+messaging path trace\s*$")
TRACE_EVIDENCE_RE = re.compile(
    r"(->|\bcalls?\b|\binvokes?\b|\bsends?\b|\bpublishes?\b|\bpersists?\b|\breturns?\b|\brejects?\b|\bvalidates?\b|\bupdates?\b|\bcontroller\b|\bservice\b|\brepository\b|\bsender\b|\bproducer\b)",
    re.IGNORECASE,
)
MESSAGING_AC_RE = re.compile(
    r"\b(mq|dmq|kafka|rocketmq|rabbitmq|topic|tag|group|payload|producer|consumer|sender|publish|message)\b|消息|队列|生产者|消费者",
    re.IGNORECASE,
)
MESSAGING_TRACE_REQUIREMENTS = {
    "sender/producer injection point": re.compile(r"\b(sender|producer|inject|constructor|bean|component)\b", re.IGNORECASE),
    "actual send call": re.compile(r"\b(send|publish|emit|produce)\b", re.IGNORECASE),
    "topic/tag/group": re.compile(r"\b(topic|tag|group)\b", re.IGNORECASE),
    "payload fields": re.compile(r"\bpayload|field", re.IGNORECASE),
    "test evidence": re.compile(r"\btest|spec|verify|assert", re.IGNORECASE),
}
PROJECT_REVIEW_PROFILE_CANDIDATES = [
    Path(".e2e/review-profile.json"),
    Path(".e2e/review-profiles/default.json"),
    Path("docs/review-profile.json"),
    Path("docs/review-profiles/default.json"),
]
PROFILE_DISABLE_VALUES = {"off", "none", "disabled", "false"}
PROFILE_BLOCKING_SEVERITIES = {"blocker", "blocking", "required", "error", "critical"}
PROFILE_WARNING_SEVERITIES = {"warning", "warn", "advisory", "advice", "info", "optional"}


def normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def normalize_value(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def normalize_phase(value: str) -> str:
    phase = normalize_value(value)
    return PHASE_ALIASES.get(phase, phase)


def is_none_value(value: str) -> bool:
    return normalize_value(value) in NONE_VALUES


def checked_checklist_ids(text: str) -> set[str]:
    ids: set[str] = set()
    for line in text.splitlines():
        match = CHECKED_ITEM_RE.match(line)
        if match:
            ids.add(normalize_value(match.group(1).strip("`")))
    return ids


def markdown_section(text: str, heading_re: re.Pattern) -> str:
    match = heading_re.search(text)
    if not match:
        return ""
    next_heading = re.search(r"(?m)^\s*#{1,4}\s+\S", text[match.end():])
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end():end].strip()


def expected_acceptance_ids(repo: Path, anchor_paths: list[Path | None] | None) -> list[str]:
    results: list[str] = []
    for anchor in anchor_paths or []:
        if not anchor:
            continue
        path = anchor if anchor.is_absolute() else repo / anchor
        if not path.exists() or not path.is_file():
            continue
        try:
            ids = clarification_gate.extract_acceptance_criteria(path)
        except (OSError, UnicodeDecodeError):
            ids = []
        for ac_id in ids:
            if ac_id not in results:
                results.append(ac_id)
    return results


def expected_acceptance_items(repo: Path, anchor_paths: list[Path | None] | None) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in anchor_paths or []:
        if not anchor:
            continue
        path = anchor if anchor.is_absolute() else repo / anchor
        if not path.exists() or not path.is_file():
            continue
        try:
            items = clarification_gate.extract_acceptance_items(path)
        except (OSError, UnicodeDecodeError):
            items = []
        for item in items:
            item_id = item.get("id", "")
            if item_id and item_id not in seen:
                seen.add(item_id)
                results.append(item)
    return results


def missing_code_path_trace_acs(text: str, ac_ids: list[str]) -> list[str]:
    if not ac_ids:
        return []
    section = markdown_section(text, CODE_PATH_HEADING_RE)
    if not section:
        return ac_ids
    missing: list[str] = []
    lines = section.splitlines()
    for ac_id in ac_ids:
        matched = False
        for line in lines:
            if ac_id in line and TRACE_EVIDENCE_RE.search(line):
                matched = True
                break
        if not matched:
            missing.append(ac_id)
    return missing


def missing_messaging_path_trace(text: str, acceptance_items: list[dict[str, str]]) -> dict[str, list[str]]:
    messaging_items = [
        item
        for item in acceptance_items
        if MESSAGING_AC_RE.search(item.get("text", ""))
    ]
    if not messaging_items:
        return {}
    section = markdown_section(text, MESSAGING_PATH_HEADING_RE) or markdown_section(text, CODE_PATH_HEADING_RE)
    missing: dict[str, list[str]] = {}
    for item in messaging_items:
        ac_id = item.get("id", "")
        ac_lines = "\n".join(line for line in section.splitlines() if ac_id and ac_id in line)
        item_missing = [
            label
            for label, pattern in MESSAGING_TRACE_REQUIREMENTS.items()
            if not pattern.search(ac_lines)
        ]
        if item_missing:
            missing[ac_id] = item_missing
    return missing


def review_profile_candidates(repo: Path, profile_path: Path | str, base_dir: Path | None = None) -> list[Path]:
    profile_path = Path(str(profile_path))
    if profile_path.is_absolute():
        return [profile_path]
    candidates = []
    if base_dir:
        candidates.append(base_dir / profile_path)
        if profile_path.suffix != ".json":
            candidates.append(base_dir / f"{profile_path.name}.json")
    candidates.append(repo / profile_path)
    if profile_path.suffix != ".json":
        candidates.append(repo / f"{profile_path.name}.json")
    parts = list(profile_path.parts)
    if "review-profiles" in parts:
        index = parts.index("review-profiles")
        candidates.append(SCRIPT_DIR.parent / Path(*parts[index:]))
    if len(parts) == 1:
        name = profile_path.name
        if not name.endswith(".json"):
            name = f"{name}.json"
        candidates.append(SCRIPT_DIR.parent / "review-profiles" / name)
    candidates.append(SCRIPT_DIR.parent / "review-profiles" / profile_path.name)
    return list(dict.fromkeys(candidates))


def resolve_review_profile_path(repo: Path, profile_ref: Path | str, base_dir: Path | None = None) -> Path:
    candidates = review_profile_candidates(repo, profile_ref, base_dir=base_dir)
    resolved = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    return resolved


def discover_project_review_profile(repo: Path) -> Path | None:
    for relative in PROJECT_REVIEW_PROFILE_CANDIDATES:
        candidate = repo / relative
        if candidate.exists():
            return candidate
    return None


def normalize_profile_item(item: object) -> dict | None:
    if isinstance(item, str):
        return {"id": item, "title": item, "required": True}
    if not isinstance(item, dict) or not item.get("id"):
        return None
    result = copy.deepcopy(item)
    result["id"] = str(result["id"])
    result["title"] = str(result.get("title") or result["id"])
    return result


def checklist_map(profile: dict | list | None) -> dict[str, list]:
    raw = profile or {}
    if isinstance(raw, list):
        return {"all": raw}
    if isinstance(raw, dict):
        return {
            str(key): value
            for key, value in raw.items()
            if isinstance(value, list)
        }
    return {}


def profile_checklist_map(profile: dict) -> dict[str, list]:
    return checklist_map(profile.get("required_checklist") or profile.get("checklist"))


def merge_checklist_items(parent_items: list, child_items: list) -> list[dict]:
    merged: list[dict] = []
    positions: dict[str, int] = {}
    for item in parent_items:
        normalized = normalize_profile_item(item)
        if not normalized:
            continue
        positions[normalize_value(normalized["id"])] = len(merged)
        merged.append(normalized)
    for item in child_items:
        normalized = normalize_profile_item(item)
        if not normalized:
            continue
        item_id = normalize_value(normalized["id"])
        if item_id in positions:
            existing = merged[positions[item_id]]
            merged[positions[item_id]] = {**existing, **normalized}
        else:
            positions[item_id] = len(merged)
            merged.append(normalized)
    return merged


def merge_checklists(parent: dict, child: dict) -> dict[str, list[dict]]:
    merged: dict[str, list[dict]] = {}
    parent_map = profile_checklist_map(parent)
    child_map = profile_checklist_map(child)
    for phase in list(parent_map) + [phase for phase in child_map if phase not in parent_map]:
        merged[phase] = merge_checklist_items(parent_map.get(phase, []), child_map.get(phase, []))
    return merged


def merge_issue_collection(parent: object, child: object) -> object:
    if child in (None, [], {}):
        return copy.deepcopy(parent)
    if isinstance(parent, dict) and isinstance(child, dict):
        merged = copy.deepcopy(parent)
        merged.update(copy.deepcopy(child))
        return merged
    if isinstance(parent, list) or isinstance(child, list):
        merged_list: list = []
        positions: dict[str, int] = {}
        for source_item in issue_collection_items(parent) + issue_collection_items(child):
            item = copy.deepcopy(source_item)
            if isinstance(item, dict) and item.get("id"):
                item_id = normalize_value(str(item["id"]))
                if item_id in positions:
                    merged_list[positions[item_id]] = {**merged_list[positions[item_id]], **item}
                else:
                    positions[item_id] = len(merged_list)
                    merged_list.append(item)
            else:
                merged_list.append(item)
        return merged_list
    return copy.deepcopy(child)


def issue_collection_items(value: object) -> list:
    if value in (None, [], {}):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        items: list = []
        for key, item in value.items():
            if isinstance(item, dict):
                normalized = {"id": str(key), **copy.deepcopy(item)}
                normalized["id"] = str(normalized.get("id") or key)
                items.append(normalized)
            else:
                items.append({"id": str(key), "title": str(item)})
        return items
    return [value]


def merge_profiles(parent: dict, child: dict) -> dict:
    merged = copy.deepcopy(parent)
    for key, value in child.items():
        if key in {"extends", "required_checklist", "checklist", "common_issues", "issues"}:
            continue
        merged[key] = copy.deepcopy(value)
    merged["required_checklist"] = merge_checklists(parent, child)
    if "common_issues" in parent or "common_issues" in child:
        merged["common_issues"] = merge_issue_collection(parent.get("common_issues"), child.get("common_issues"))
    if "issues" in parent or "issues" in child:
        merged["issues"] = merge_issue_collection(parent.get("issues"), child.get("issues"))
    return merged


def as_extends_list(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def load_review_profile_file(repo: Path, profile_path: Path, stack: list[Path] | None = None) -> tuple[dict, list[str], list[str]]:
    resolved = profile_path.resolve()
    stack = stack or []
    if resolved in stack:
        chain = " -> ".join(str(path) for path in stack + [resolved])
        return {}, [f"Review profile extends cycle detected: {chain}"], [str(resolved)]
    if not resolved.exists():
        return {}, [f"Review profile not found: {resolved}"], [str(resolved)]
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {}, [f"Review profile is not valid JSON: {resolved}: {error}"], [str(resolved)]
    if not isinstance(data, dict):
        return {}, [f"Review profile must be a JSON object: {resolved}"], [str(resolved)]

    blocked: list[str] = []
    merged: dict = {}
    chain: list[str] = []
    for parent_ref in as_extends_list(data.get("extends")):
        parent_path = resolve_review_profile_path(repo, parent_ref, base_dir=resolved.parent)
        parent_profile, parent_blocked, parent_chain = load_review_profile_file(repo, parent_path, stack + [resolved])
        blocked.extend(parent_blocked)
        chain.extend(parent_chain)
        merged = merge_profiles(merged, parent_profile)
    merged = merge_profiles(merged, data)
    chain.append(str(resolved))
    return merged, blocked, list(dict.fromkeys(chain))


def load_review_profile(repo: Path, profile_path: Path | str | None) -> tuple[dict, list[str], str | None, str | None, list[str]]:
    if profile_path and normalize_value(str(profile_path)) in PROFILE_DISABLE_VALUES:
        return {}, [], None, "disabled", []
    source = "explicit" if profile_path else None
    resolved: Path | None = None
    if profile_path:
        resolved = resolve_review_profile_path(repo, profile_path)
    else:
        resolved = discover_project_review_profile(repo)
        if resolved:
            source = "project"
    if not resolved:
        return {}, [], None, None, []

    profile, blocked, chain = load_review_profile_file(repo, resolved)
    return profile, blocked, str(resolved.resolve()), source, chain


def normalize_profile_severity(item: dict) -> str:
    severity = normalize_value(str(item.get("severity", "")))
    if not severity:
        return "blocker" if item.get("required", True) is not False else "advisory"
    if severity in PROFILE_BLOCKING_SEVERITIES:
        return "blocker"
    if severity in PROFILE_WARNING_SEVERITIES:
        return "warning"
    return severity


def profile_required_items(profile: dict, phase: str) -> list[dict[str, str]]:
    raw = profile.get("required_checklist") or profile.get("checklist") or {}
    selected: list = []
    if isinstance(raw, list):
        selected.extend(raw)
    elif isinstance(raw, dict):
        for key in ("all", phase):
            value = raw.get(key, [])
            if isinstance(value, list):
                selected.extend(value)
    result: list[dict[str, str]] = []
    for item in selected:
        normalized = normalize_profile_item(item)
        if normalized and normalized.get("required", True) is not False:
            normalized["severity"] = normalize_profile_severity(normalized)
            result.append(normalized)
    return result


def parse_item(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.lstrip("\ufeff")
        match = FIELD_RE.match(line)
        if not match:
            continue
        key = normalize_key(match.group(1))
        value = match.group(2).strip()
        if key not in fields:
            fields[key] = value
    return fields


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def normalize_agent_id(value: str) -> str:
    return re.sub(r"\s+", "", normalize_value(value).strip("<>"))


def is_placeholder(value: str) -> bool:
    return not value.strip() or bool(PLACEHOLDER_RE.match(value.strip()))


def request_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_repo_path(repo: Path, value: str) -> Path:
    path = Path(value.strip())
    return path if path.is_absolute() else repo / path


def inside_repo(repo: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(repo.resolve())
        return True
    except ValueError:
        return False


def explicit_files(repo: Path, inputs: list[Path] | None) -> list[Path]:
    files: list[Path] = []
    for item in inputs or []:
        resolved = item if item.is_absolute() else repo / item
        if resolved.is_file():
            files.append(resolved)
        elif resolved.is_dir():
            files.extend(sorted(resolved.glob("*review*.md")))
            files.extend(sorted(resolved.glob("reviews/*review*.md")))
    return sorted(
        path
        for path in dict.fromkeys(files)
        if "review-request" not in path.name.lower()
    )


def dedupe_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(path)
    return sorted(result)


def agent_run_dir_from_path(repo: Path, path: Path | None) -> Path | None:
    if not path:
        return None
    resolved = path if path.is_absolute() else repo / path
    parts = resolved.resolve().parts
    for index in range(len(parts) - 2):
        if parts[index] == "docs" and parts[index + 1] == "agent-runs":
            return Path(*parts[: index + 3])
    return None


def infer_agent_run_dir(repo: Path, anchor_paths: list[Path | None] | None) -> Path | None:
    for path in anchor_paths or []:
        run_dir = agent_run_dir_from_path(repo, path)
        if run_dir:
            return run_dir
    return None


def service_slug(value: str) -> str:
    text = value.strip().strip("`").replace("\\", "/").strip("/")
    if not text:
        return ""
    text = text.split(":", 1)[0].strip()
    text = text.split(" - ", 1)[0].strip()
    text = text.split(" ", 1)[0].strip()
    return text.rsplit("/", 1)[-1].strip("/.,;")


def expected_services(agent_run_dir: Path | None) -> list[str]:
    if not agent_run_dir:
        return []
    service_plans = agent_run_dir / "service-plans"
    if not service_plans.exists():
        return []
    services = [
        path.name
        for path in sorted(service_plans.iterdir())
        if path.is_dir()
    ]
    return sorted(dict.fromkeys(services))


def service_from_review_path(agent_run_dir: Path | None, path: Path) -> str:
    if not agent_run_dir:
        return ""
    service_plans = agent_run_dir / "service-plans"
    try:
        relative = path.resolve().relative_to(service_plans.resolve())
    except ValueError:
        return ""
    parts = relative.parts
    if len(parts) >= 3 and parts[1] == "reviews":
        return parts[0]
    return ""


def service_from_scope(scope: str, expected: list[str]) -> str:
    slug = service_slug(scope)
    return slug if slug in expected else ""


def discovered_files(repo: Path, agent_run_dir: Path | None) -> list[Path]:
    if not agent_run_dir:
        return []
    run_dir = agent_run_dir if agent_run_dir.is_absolute() else repo / agent_run_dir
    candidates: list[Path] = []
    if (run_dir / "reviews").exists():
        candidates.extend(sorted((run_dir / "reviews").glob("*review*.md")))
    service_plans = run_dir / "service-plans"
    if service_plans.exists():
        candidates.extend(sorted(service_plans.glob("*/reviews/*review*.md")))
    return sorted(dict.fromkeys(candidates))


def validate_item(
    repo: Path,
    path: Path,
    fields: dict[str, str],
    review_profile: dict | None = None,
    expected_acs: list[str] | None = None,
    expected_ac_items: list[dict[str, str]] | None = None,
) -> tuple[dict, list[str], list[str]]:
    blocked: list[str] = []
    warnings: list[str] = []
    missing = [label for key, label in REQUIRED_FIELDS.items() if not fields.get(key, "").strip()]
    if missing:
        blocked.append(f"Semantic review {path} missing required fields: {', '.join(missing)}")

    phase = normalize_phase(fields.get("phase", ""))
    status = normalize_value(fields.get("status", ""))
    findings = fields.get("findings", "")
    required_rework = fields.get("required_rework", "")
    developer_agent = fields.get("developer_agent", "").strip()
    reviewer_agent = fields.get("reviewer_agent", "").strip()
    reviewer_session = fields.get("reviewer_session", "").strip()
    reviewer_invocation = fields.get("reviewer_invocation", "").strip()
    report_request_hash = fields.get("request_hash", "").strip().lower()
    independence = normalize_value(fields.get("independence", ""))
    no_code_changes = normalize_value(fields.get("no_code_changes", ""))
    context_boundary = fields.get("context_boundary", "").strip().lower()
    review_request = fields.get("review_request", "").strip()

    for label, value in (
        ("Developer Agent", developer_agent),
        ("Reviewer Agent", reviewer_agent),
        ("Reviewer Session", reviewer_session),
    ):
        if is_placeholder(value):
            blocked.append(f"Semantic review {path} has placeholder {label}; use a concrete independent agent/session id.")
    if developer_agent and reviewer_agent and normalize_agent_id(developer_agent) == normalize_agent_id(reviewer_agent):
        blocked.append(f"Semantic review {path} uses the same Developer Agent and Reviewer Agent; self-review is not allowed.")
    if not independence or independence in SELF_REVIEW_VALUES or independence not in INDEPENDENT_VALUES:
        blocked.append(f"Semantic review {path} must declare Independence: independent-agent or equivalent, got {fields.get('independence')}.")
    if not no_code_changes or no_code_changes not in NO_CODE_CHANGE_VALUES:
        blocked.append(f"Semantic review {path} must declare No Code Changes: confirmed/read-only, got {fields.get('no_code_changes')}.")
    if not context_boundary or not ("request" in context_boundary and ("no inherited" in context_boundary or "isolated" in context_boundary)):
        blocked.append(f"Semantic review {path} must use a request-scoped isolated context boundary.")
    invocation_fields: dict = {}
    if reviewer_invocation:
        resolved_invocation = resolve_repo_path(repo, reviewer_invocation)
        if not inside_repo(repo, resolved_invocation):
            blocked.append(f"Semantic review {path} references Reviewer Invocation outside repo: {reviewer_invocation}")
        elif not resolved_invocation.exists():
            blocked.append(f"Semantic review {path} references missing Reviewer Invocation: {reviewer_invocation}")
        else:
            invocation_fields = read_json(resolved_invocation)
            if not invocation_fields:
                blocked.append(f"Reviewer Invocation {resolved_invocation} is missing or not valid JSON.")
            if normalize_agent_id(str(invocation_fields.get("developer_agent", ""))) != normalize_agent_id(developer_agent):
                blocked.append(f"Reviewer Invocation {resolved_invocation} Developer Agent does not match review report.")
            if normalize_agent_id(str(invocation_fields.get("reviewer_agent", ""))) != normalize_agent_id(reviewer_agent):
                blocked.append(f"Reviewer Invocation {resolved_invocation} Reviewer Agent does not match review report.")
            if normalize_agent_id(str(invocation_fields.get("reviewer_session", ""))) != normalize_agent_id(reviewer_session):
                blocked.append(f"Reviewer Invocation {resolved_invocation} Reviewer Session does not match review report.")
            if invocation_fields.get("fork_context") is not False:
                blocked.append(f"Reviewer Invocation {resolved_invocation} must declare fork_context=false.")
            context_policy = str(invocation_fields.get("context_policy", "")).lower()
            if not ("request" in context_policy and ("no-inherited" in context_policy or "no inherited" in context_policy or "isolated" in context_policy)):
                blocked.append(f"Reviewer Invocation {resolved_invocation} must declare request-only/no-inherited context policy.")
            if normalize_value(str(invocation_fields.get("status", ""))) not in {"completed", "complete", "done"}:
                blocked.append(f"Reviewer Invocation {resolved_invocation} must have status=completed.")
    if review_request:
        resolved_request = resolve_repo_path(repo, review_request)
        if not inside_repo(repo, resolved_request):
            blocked.append(f"Semantic review {path} references Review Request outside repo: {review_request}")
        elif not resolved_request.exists():
            blocked.append(f"Semantic review {path} references missing Review Request: {review_request}")
        else:
            request_fields = parse_item(resolved_request)
            missing_request = [
                label
                for key, label in REQUEST_REQUIRED_FIELDS.items()
                if not request_fields.get(key, "").strip()
            ]
            if missing_request:
                blocked.append(
                    f"Review Request {resolved_request} missing required fields: {', '.join(missing_request)}"
                )
            request_developer = request_fields.get("developer_agent", "").strip()
            request_reviewer = request_fields.get("reviewer_agent", "").strip()
            request_invocation = request_fields.get("reviewer_invocation", "").strip()
            for label, value in (
                ("Review Request Developer Agent", request_developer),
                ("Review Request Reviewer Agent", request_reviewer),
            ):
                if is_placeholder(value):
                    blocked.append(f"Review Request {resolved_request} has placeholder {label}; assign concrete agent ids before review.")
            if request_developer and developer_agent and normalize_agent_id(request_developer) != normalize_agent_id(developer_agent):
                blocked.append(f"Semantic review {path} Developer Agent does not match Review Request Developer Agent.")
            if request_reviewer and reviewer_agent and normalize_agent_id(request_reviewer) != normalize_agent_id(reviewer_agent):
                blocked.append(f"Semantic review {path} Reviewer Agent does not match Review Request Reviewer Agent.")
            if request_developer and request_reviewer and normalize_agent_id(request_developer) == normalize_agent_id(request_reviewer):
                blocked.append(f"Review Request {resolved_request} assigns the same Developer Agent and Reviewer Agent.")
            if request_invocation and reviewer_invocation:
                resolved_request_invocation = resolve_repo_path(repo, request_invocation)
                resolved_report_invocation = resolve_repo_path(repo, reviewer_invocation)
                if resolved_request_invocation.resolve() != resolved_report_invocation.resolve():
                    blocked.append(f"Semantic review {path} Reviewer Invocation does not match Review Request.")
            context_package = request_fields.get("context_package", "").strip().lower()
            forbidden = request_fields.get("forbidden", "").strip().lower()
            if not ("request" in context_package and ("no inherited" in context_package or "isolated" in context_package)):
                blocked.append(f"Review Request {resolved_request} must declare a request-scoped context with no inherited developer chat context.")
            if not ("self-review" in forbidden and "production-code edits" in forbidden):
                blocked.append(f"Review Request {resolved_request} must forbid self-review and production-code edits.")
            if report_request_hash != request_hash(resolved_request):
                blocked.append(f"Semantic review {path} Request Hash does not match Review Request content.")
            if invocation_fields:
                invocation_request = str(invocation_fields.get("review_request", "")).strip()
                invocation_output = str(invocation_fields.get("output", "")).strip()
                if invocation_request:
                    resolved_invocation_request = resolve_repo_path(repo, invocation_request)
                    if resolved_invocation_request.resolve() != resolved_request.resolve():
                        blocked.append(f"Reviewer Invocation for {path} does not point to the same Review Request.")
                else:
                    blocked.append(f"Reviewer Invocation for {path} must include review_request.")
                if invocation_output:
                    resolved_invocation_output = resolve_repo_path(repo, invocation_output)
                    if resolved_invocation_output.resolve() != path.resolve():
                        blocked.append(f"Reviewer Invocation for {path} does not point to this review report output.")
                else:
                    blocked.append(f"Reviewer Invocation for {path} must include output.")
            request_phase = normalize_phase(request_fields.get("phase", ""))
            if phase and request_phase and phase != request_phase:
                blocked.append(
                    f"Semantic review {path} phase {phase} does not match Review Request phase {request_phase}."
                )
            output = request_fields.get("output", "").strip()
            if output:
                resolved_output = resolve_repo_path(repo, output)
                if not inside_repo(repo, resolved_output):
                    blocked.append(f"Review Request {resolved_request} declares output outside repo: {output}")
                elif resolved_output.resolve() != path.resolve():
                    blocked.append(f"Semantic review {path} is not the declared Review Request output: {output}")
    if status in BLOCK_STATUSES:
        blocked.append(f"Semantic review {path} is still {status}; create rework items and return to the required phase.")
    elif status in PASS_WITH_REWORK_STATUSES and is_none_value(required_rework):
        blocked.append(f"Semantic review {path} is {status} but Required Rework is empty.")
    elif status and status not in PASS_STATUSES and status not in PASS_WITH_REWORK_STATUSES:
        blocked.append(f"Semantic review {path} has unsupported Status: {fields.get('status')}")
    if status in PASS_STATUSES and not is_none_value(findings) and is_none_value(required_rework):
        blocked.append(f"Semantic review {path} has Findings but Required Rework is empty; route findings to rework or use a blocking/with-rework status.")

    raw_text = path.read_text(encoding="utf-8", errors="replace")
    missing_trace_acs: list[str] = []
    missing_messaging_trace: dict[str, list[str]] = {}
    if phase == "implementation" and expected_acs:
        missing_trace_acs = missing_code_path_trace_acs(raw_text, expected_acs)
        if missing_trace_acs:
            blocked.append(
                f"Semantic review {path} missing Code Path Trace coverage for acceptance criteria: "
                + ", ".join(missing_trace_acs)
            )
        missing_messaging_trace = missing_messaging_path_trace(raw_text, expected_ac_items or [])
        for ac_id, labels in missing_messaging_trace.items():
            blocked.append(
                f"Semantic review {path} missing Messaging Path Trace for {ac_id}: "
                + ", ".join(labels)
            )
    checked_ids = checked_checklist_ids(raw_text)
    missing_profile_items: list[str] = []
    warning_profile_items: list[str] = []
    for profile_item in profile_required_items(review_profile or {}, phase):
        item_id = normalize_value(profile_item["id"])
        if item_id not in checked_ids:
            missing_profile_items.append(profile_item["id"])
            message = f"Semantic review {path} missing required review profile checklist item: {profile_item['id']} ({profile_item['title']})."
            description = str(profile_item.get("description", "")).strip()
            if description:
                message += f" Guidance: {description}"
            if profile_item.get("severity") == "warning":
                warning_profile_items.append(profile_item["id"])
                warnings.append(message)
            else:
                blocked.append(message)

    item = dict(fields)
    item.update(
        {
            "path": str(path),
            "phase": phase,
            "status": status,
            "developer_agent": developer_agent,
            "reviewer_agent": reviewer_agent,
            "reviewer_session": reviewer_session,
            "reviewer_invocation": reviewer_invocation,
            "independence": independence,
            "review_request": review_request,
            "request_hash": report_request_hash,
            "has_required_rework": not is_none_value(required_rework),
            "checked_profile_items": sorted(checked_ids),
            "missing_profile_items": missing_profile_items,
            "warning_profile_items": warning_profile_items,
            "missing_code_path_trace_acs": missing_trace_acs,
            "missing_messaging_path_trace": missing_messaging_trace,
        }
    )
    return item, blocked, warnings


def validate(
    repo: Path,
    review_dirs: list[Path] | None = None,
    anchor_paths: list[Path | None] | None = None,
    require_phases: list[str] | None = None,
    review_profile: Path | None = None,
) -> dict:
    repo = repo.resolve()
    files = explicit_files(repo, review_dirs)
    inferred_run_dir = None
    inferred_run_dir = infer_agent_run_dir(repo, list(review_dirs or []) + list(anchor_paths or []))
    if inferred_run_dir:
        files = dedupe_paths(files + discovered_files(repo, inferred_run_dir))

    required = [normalize_phase(phase) for phase in require_phases or []]
    services = expected_services(inferred_run_dir)
    blocked: list[str] = []
    profile, profile_blocked, profile_path, profile_source, profile_chain = load_review_profile(repo, review_profile)
    blocked.extend(profile_blocked)
    warnings: list[str] = []
    items: list[dict] = []
    expected_ac_items = expected_acceptance_items(repo, anchor_paths)
    expected_acs = [item["id"] for item in expected_ac_items]
    covered: set[str] = set()
    covered_service_reviews: dict[str, set[str]] = {service: set() for service in services}
    for path in files:
        fields = parse_item(path)
        item, item_blocked, item_warnings = validate_item(repo, path, fields, profile, expected_acs, expected_ac_items)
        service = service_from_review_path(inferred_run_dir, path) or service_from_scope(fields.get("scope", ""), services)
        if service and item.get("phase") in {"test", "implementation"}:
            covered_service_reviews.setdefault(service, set()).add(item["phase"])
            item["service"] = service
        items.append(item)
        blocked.extend(item_blocked)
        warnings.extend(item_warnings)
        if item.get("phase"):
            covered.add(item["phase"])

    missing_phases = [phase for phase in required if phase not in covered]
    if missing_phases:
        blocked.append("Missing required semantic review phases: " + ", ".join(missing_phases))
    for service in services:
        for phase in [phase for phase in required if phase in {"test", "implementation"}]:
            if phase not in covered_service_reviews.get(service, set()):
                blocked.append(f"Missing service-local semantic review for service {service} phase {phase}.")

    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": warnings,
        "scanned_files": [str(path) for path in files],
        "inferred_agent_run_dir": str(inferred_run_dir) if inferred_run_dir else None,
        "review_profile": profile_path,
        "review_profile_source": profile_source,
        "review_profile_chain": profile_chain,
        "covered_phases": sorted(covered),
        "expected_services": services,
        "covered_service_reviews": {
            service: sorted(phases)
            for service, phases in covered_service_reviews.items()
        },
        "required_phases": required,
        "expected_acceptance_ids": expected_acs,
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--review-dir", action="append", type=Path)
    parser.add_argument("--anchor-path", action="append", type=Path)
    parser.add_argument("--require-phase", action="append", choices=["design", "test", "implementation"])
    parser.add_argument("--review-profile", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(args.repo, args.review_dir, args.anchor_path, args.require_phase, args.review_profile)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Semantic review gate: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
