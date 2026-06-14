"""GitNexus impact provider.

Mirrors the legacy cross-service scanner's testability pattern: subprocess
orchestration goes through an injectable `command_runner`, and `available` can be
forced, so every method is unit-testable without a real GitNexus. Index status,
seed resolution and assessment are separate because they fail/degrade differently.
Each GitNexus call runs under a wall-clock budget (the assessment executes inside
engine.evaluate, the hot path behind `next`); a timeout yields `blocked`, never a
stall.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from e2e_harness.adapters.evidence import impact as impact_ev

_SYMBOL_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$")


def is_symbol_seed(value: str) -> bool:
    """Symbol/route/file identifier — never a service directory (legacy parity)."""
    v = (value or "").strip()
    if not v or "/" in v or "\\" in v or v.startswith((".", "-", "/")):
        return False
    if ":" in v or "{" in v or "}" in v or re.search(r"\s", v):
        return False
    return bool(_SYMBOL_RE.match(v))


def run_command(command: list[str], cwd: Path, timeout: float = 20.0) -> dict:
    try:
        done = subprocess.run(command, cwd=cwd, text=True, capture_output=True,
                              shell=False, timeout=timeout)
        return {"command": " ".join(command), "exit_code": done.returncode,
                "stdout": done.stdout, "stderr": done.stderr}
    except FileNotFoundError as e:
        return {"command": " ".join(command), "exit_code": 127, "stdout": "", "stderr": str(e)}
    except subprocess.TimeoutExpired:
        return {"command": " ".join(command), "exit_code": 124, "stdout": "", "stderr": "timeout"}


def _iq(n: int, question: str) -> dict:
    return {"id": f"IQ-{n:03d}", "question": question, "status": "open"}


class GitNexusImpactProvider:
    name = "gitnexus"

    def __init__(self, *, command_runner=run_command, available=None,
                 call_timeout_s: float = 20.0, refresh_timeout_s: float = 120.0):
        self._run = command_runner
        self._available = available
        self._call_t = call_timeout_s
        self._refresh_t = refresh_timeout_s

    def _is_available(self) -> bool:
        if self._available is not None:
            return bool(self._available)
        return bool(shutil.which("gitnexus"))

    def inspect_index(self, repo: Path) -> dict:
        if not self._is_available():
            return {"available": False, "fresh": False}
        res = self._run(["gitnexus", "status", "--repo", str(Path(repo).resolve())], repo)
        fresh = res.get("exit_code") == 0 and "stale" not in (res.get("stdout") or "").lower()
        return {"available": True, "fresh": fresh, "raw": res}

    def refresh_index(self, repo: Path) -> dict:
        res = self._run(["gitnexus", "analyze", str(Path(repo).resolve())], repo)
        return {"refreshed": res.get("exit_code") == 0, "raw": res}

    def resolve_seeds(self, repo: Path, request: dict) -> dict:
        candidates = [c for c in (request.get("seed_candidates") or []) if isinstance(c, str)]
        seeds: list[str] = []
        for c in candidates:
            if is_symbol_seed(c) and c not in seeds:
                seeds.append(c)
        if not seeds:
            return {"seeds": [], "blocked": True,
                    "open_questions": [_iq(1, "Name the affected module, route, class, "
                                            "function, or file so impact can be assessed.")]}
        return {"seeds": seeds, "blocked": False, "open_questions": []}

    def _impact_for_seed(self, repo: Path, seed: str) -> dict:
        return self._run(["gitnexus", "impact", seed, "--repo", str(Path(repo).resolve()),
                          "--direction", "upstream"], repo)

    def assess(self, repo: Path, request: dict) -> dict:
        """Produce an impact-assessment.v1 dict. Never raises; degrades to blocked."""
        repo = Path(repo)
        base = {"schema": impact_ev.SCHEMA, "tool": "gitnexus", "seeds": [], "impact": [],
                "planning_constraints": [], "open_questions": [], "degradation": None,
                "approval": None}
        if not self._is_available():
            return {**base, "status": "blocked",
                    "open_questions": [_iq(1, "GitNexus is unavailable; approve degradation "
                                            "or install/index GitNexus to assess impact.")]}
        resolved = self.resolve_seeds(repo, request)
        if resolved["blocked"]:
            return {**base, "status": "blocked", "open_questions": resolved["open_questions"]}

        seeds: list[dict] = []
        impact_rows: list[dict] = []
        questions: list[dict] = []
        for i, seed in enumerate(resolved["seeds"], start=1):
            res = self._impact_for_seed(repo, seed)
            if res.get("exit_code") == 124:
                return {**base, "status": "blocked",
                        "open_questions": [_iq(1, f"GitNexus timed out assessing {seed}; "
                                               "retry or approve degradation.")]}
            data = _parse_json(res.get("stdout"))
            if data is None:
                questions.append(_iq(i, f"GitNexus produced no parseable impact for {seed}."))
                continue
            candidates = data.get("candidates")
            if isinstance(candidates, list) and len(candidates) > 1:
                opts = ", ".join(str(c) for c in candidates[:6])
                questions.append(_iq(i, f"Seed {seed} is ambiguous; disambiguate among: {opts}."))
                continue
            seeds.append({"kind": "symbol", "name": seed,
                          "file_path": data.get("file_path", ""), "reason": "resolved seed"})
            impact_rows.append(_normalize_impact(seed, data))

        if questions:
            return {**base, "status": "blocked", "open_questions": questions}
        return {**base, "status": "verified", "seeds": seeds, "impact": impact_rows,
                "index": {"fresh": True}}


def _parse_json(text):
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _normalize_impact(seed: str, data: dict) -> dict:
    risk = str(data.get("risk") or "LOW").upper()
    if risk not in impact_ev.RISK_ORDER:
        risk = "LOW"
    summary = data.get("summary") or {}
    procs = data.get("affected_processes") or []
    return {
        "seed": seed,
        "direction": "upstream",
        "risk": risk,
        "summary": {
            "direct": int(summary.get("direct", 0) or 0),
            "processes_affected": int(summary.get("processes_affected", len(procs)) or 0),
            "modules_affected": int(summary.get("modules_affected", 0) or 0),
        },
        "affected_processes": [
            {"name": p.get("name", ""), "file_path": p.get("file_path", "")}
            if isinstance(p, dict) else {"name": str(p), "file_path": ""}
            for p in procs
        ],
        "affected_modules": list(data.get("affected_modules") or []),
    }
