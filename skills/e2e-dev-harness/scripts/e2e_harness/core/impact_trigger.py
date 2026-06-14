"""Pure impact trigger policy (design: Trigger Policy).

Reads run-state + the acceptance contract file only — never a subprocess — so it is
safe to call both from the bridge (decide whether to run the provider) and from the
PLANNED gate backstop (decide whether a missing binding is a defect). [] == not
required.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_DOC_ONLY = re.compile(r"\b(documentation|readme|changelog|comment|typo|wording|docs?)\b", re.I)
_CODE_SURFACE = re.compile(
    r"\b(function|class|method|module|route|endpoint|api|table|schema|topic|"
    r"service|handler|migration|helper)\b", re.I)
_EXPLICIT = re.compile(
    r"\b(impact|blast radius|safety|safe to change|dependency|dependencies|"
    r"affected|regression surface)\b", re.I)
_CONTRACT_SENSITIVE = re.compile(
    r"\b(compatib|migration|security|cross-service|public api|persistence|"
    r"shared helper|backward)\b", re.I)


def _load_contract(state: dict, repo_root) -> dict | None:
    entry = (state.get("phases", {}).get("CLARIFIED", {})
             .get("evidence", {}).get("acceptance_contract"))
    if not entry:
        return None
    rel = entry["path"] if isinstance(entry, dict) else entry
    full = Path(rel)
    if not full.is_absolute() and repo_root is not None:
        full = Path(repo_root) / rel
    try:
        return json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_documentation_only(state: dict, repo_root) -> bool:
    request = str(state.get("request") or "")
    if _CODE_SURFACE.search(request):
        return False
    return bool(_DOC_ONLY.search(request))


def required_reasons(state: dict, repo_root) -> list[str]:
    reasons: list[str] = []
    request = str(state.get("request") or "")
    contract = _load_contract(state, repo_root)

    if str(state.get("tier") or "") in {"critical", "audited"}:
        reasons.append("tier-critical")
    if _EXPLICIT.search(request):
        reasons.append("explicit-impact")
    if contract and contract.get("impact_seed_candidates"):
        reasons.append("existing-symbol")
    if _CODE_SURFACE.search(request):
        reasons.append("code-change")
    if contract:
        blob = json.dumps(contract, ensure_ascii=False)
        if _CONTRACT_SENSITIVE.search(blob):
            reasons.append("contract-sensitive")

    if is_documentation_only(state, repo_root):
        return []
    # de-dup, preserve order
    seen: set[str] = set()
    return [r for r in reasons if not (r in seen or seen.add(r))]
