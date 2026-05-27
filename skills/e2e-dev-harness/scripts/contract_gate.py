#!/usr/bin/env python3
"""Validate cross-service contract artifacts before parallel service implementation."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REQUIRED_FIELDS = {
    "contract_id": "Contract ID",
    "kind": "Kind",
    "producer_service": "Producer Service",
    "consumer_services": "Consumer Services",
    "payload_schema": "Payload Schema",
    "compatibility_rule": "Compatibility Rule",
    "producer_ack": "Producer ACK",
    "consumer_ack": "Consumer ACK",
    "contract_tests": "Contract Tests",
    "status": "Status",
}
PASS_STATUSES = {"ready", "verified", "approved", "passed", "complete", "completed"}
BLOCK_STATUSES = {"draft", "open", "in-progress", "in_progress", "blocked", "needs-rework", "changes-requested"}
NONE_VALUES = {"", "-", "none", "n/a", "na", "no", "todo", "tbd"}
ACK_RE = re.compile(r"\b(ack|approved|verified|accepted|confirmed)\b", re.IGNORECASE)
FIELD_RE = re.compile(r"^\s*-?\s*([A-Za-z][A-Za-z _-]*):\s*(.*?)\s*$")


def normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def normalize_value(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def is_none_value(value: str) -> bool:
    return normalize_value(value) in NONE_VALUES


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


def split_values(value: str) -> list[str]:
    parts = re.split(r"[,;\n]+", value)
    return [part.strip().strip("`") for part in parts if part.strip().strip("`")]


def explicit_files(repo: Path, inputs: list[Path] | None) -> list[Path]:
    files: list[Path] = []
    for item in inputs or []:
        resolved = item if item.is_absolute() else repo / item
        if resolved.is_file():
            files.append(resolved)
        elif resolved.is_dir():
            files.extend(sorted(resolved.glob("*.md")))
    return sorted(dict.fromkeys(files))


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


def discovered_files(repo: Path, agent_run_dir: Path | None) -> list[Path]:
    if not agent_run_dir:
        return []
    run_dir = agent_run_dir if agent_run_dir.is_absolute() else repo / agent_run_dir
    contracts = run_dir / "contracts"
    if not contracts.exists():
        return []
    return sorted(contracts.glob("*.md"))


def ack_ready(value: str) -> bool:
    return bool(value.strip()) and not is_none_value(value) and bool(ACK_RE.search(value))


def validate_item(path: Path, fields: dict[str, str]) -> tuple[dict, list[str]]:
    blocked: list[str] = []
    missing = [label for key, label in REQUIRED_FIELDS.items() if not fields.get(key, "").strip()]
    if missing:
        blocked.append(f"Contract {path} missing required fields: {', '.join(missing)}")

    kind = normalize_value(fields.get("kind", ""))
    status = normalize_value(fields.get("status", ""))
    if kind not in {"http", "dmq"}:
        blocked.append(f"Contract {path} Kind must be http or dmq, got {fields.get('kind')}.")
    if status in BLOCK_STATUSES:
        blocked.append(f"Contract {path} is still {status}.")
    elif status and status not in PASS_STATUSES:
        blocked.append(f"Contract {path} has unsupported Status: {fields.get('status')}")

    if kind == "http" and not (fields.get("endpoint", "").strip() or fields.get("route", "").strip()):
        blocked.append(f"HTTP contract {path} must include Endpoint or Route.")
    if kind == "dmq":
        for key, label in (("topic", "Topic"), ("tag", "Tag"), ("group", "Group")):
            if not fields.get(key, "").strip():
                blocked.append(f"DMQ contract {path} must include {label}.")

    if not ack_ready(fields.get("producer_ack", "")):
        blocked.append(f"Contract {path} Producer ACK is missing or not approved.")
    if not ack_ready(fields.get("consumer_ack", "")):
        blocked.append(f"Contract {path} Consumer ACK is missing or not approved.")
    if is_none_value(fields.get("contract_tests", "")):
        blocked.append(f"Contract {path} Contract Tests must name real contract tests.")
    if is_none_value(fields.get("payload_schema", "")):
        blocked.append(f"Contract {path} Payload Schema must be explicit.")
    if is_none_value(fields.get("compatibility_rule", "")):
        blocked.append(f"Contract {path} Compatibility Rule must be explicit.")

    item = dict(fields)
    item.update(
        {
            "path": str(path),
            "kind": kind,
            "status": status,
            "producer_service": fields.get("producer_service", "").strip(),
            "consumer_services": split_values(fields.get("consumer_services", "")),
        }
    )
    return item, blocked


def validate(
    repo: Path,
    contract_dirs: list[Path] | None = None,
    anchor_paths: list[Path | None] | None = None,
    require_contracts: bool = False,
) -> dict:
    repo = repo.resolve()
    files = explicit_files(repo, contract_dirs)
    inferred_run_dir = infer_agent_run_dir(repo, list(contract_dirs or []) + list(anchor_paths or []))
    if not contract_dirs and inferred_run_dir:
        files = discovered_files(repo, inferred_run_dir)

    blocked: list[str] = []
    if require_contracts and not files:
        blocked.append("Cross-service work requires contract artifacts under docs/agent-runs/<run>/contracts.")
    items: list[dict] = []
    for path in files:
        fields = parse_item(path)
        item, item_blocked = validate_item(path, fields)
        items.append(item)
        blocked.extend(item_blocked)
    return {
        "repo": str(repo),
        "ready": not blocked,
        "blocked_reasons": blocked,
        "warnings": [],
        "scanned_files": [str(path) for path in files],
        "inferred_agent_run_dir": str(inferred_run_dir) if inferred_run_dir else None,
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--contract-dir", action="append", type=Path)
    parser.add_argument("--anchor-path", action="append", type=Path)
    parser.add_argument("--require-contracts", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = validate(args.repo, args.contract_dir, args.anchor_path, args.require_contracts)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Contract gate: " + ("READY" if result["ready"] else "BLOCKED"))
        for reason in result["blocked_reasons"]:
            print(f"- {reason}")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
