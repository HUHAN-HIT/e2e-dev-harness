# GitNexus Impact Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a structured GitNexus **Impact Assessment** artifact + supplemental `PLANNED` gate to the e2e-dev-harness lifecycle, so code-impacting runs cannot plan past real dependency/blast-radius evidence.

**Architecture:** A control-plane bridge (`impact_bridge.ensure_assessment_for_planning`) runs an idempotent, contract-hash-keyed trigger as `engine.evaluate` reaches `PLANNED`; it persists `impact-assessment.json` + a run-state binding. A pure `impact_gate.planned_missing` adds a state-aware supplemental check to `gates.gate_passes` for `PLANNED`. Runtime `dispatch` only transports the artifact path. The whole subsystem is gated by a run-state `impact.mode` (`off` default → no-op, preserving compatibility; `auto`/`strict` → enforcement).

**Tech Stack:** Python 3, stdlib only (project is zero-runtime-dependency). Tests: pytest (run from `skills/e2e-dev-harness`, `scripts/` is auto-added to `sys.path` by `tests/conftest.py`).

---

## Conventions (read once)

- **Run all tests from** `skills/e2e-dev-harness`:
  `python -m pytest tests/ -q`
- **Run one test file:** `python -m pytest tests/test_impact_evidence.py -v`
- **Run one test:** `python -m pytest tests/test_impact_evidence.py::test_verified_artifact_passes -v`
- Tests are plain `def test_*()` functions with `assert` (no `unittest.TestCase`). Do **not** use `python -m unittest` — it will not collect these.
- Source root: `skills/e2e-dev-harness/scripts/e2e_harness` (import as `e2e_harness.*`).
- New modules use `from __future__ import annotations` and the terse, comment-rich house style.
- **Commit after each task** (per-task `git add` + `git commit`). Branch off `master` first if not already on a feature branch.

## Baseline invariant

Before starting and after every slice: `python -m pytest tests/ -q` must stay green (baseline: **675 passed**). New tests add to this count.

## Verified seams (from the current checkout)

- `core/lifecycle.py`: `Phase` frozen dataclass. `CLARIFIED` gate `(clarification, acceptance_contract)`, `PLANNED` gate `(plan, module_plan)`. `next_phase` is set by `build_spine`.
- `core/engine.py`: `_evaluate_singleton(spine, state, repo_root)` is the single-cursor walk (lines 173–234). Loop body starts `phase = by_name[name]; rec = ...; ok, missing = gates.gate_passes(phase, rec, repo_root, state=state)`. This is where the bridge call is inserted (before the PLANNED gate is evaluated).
- `core/gates.py`: `gate_passes(phase, phase_record, repo_root=None, *, skip_replay=False, state=None)` (line 8). `all_gates_pass` (line 46) threads `state`.
- `core/navigation.py`: per-phase `gate_passes` calls at lines **25, 60, 63, 81** pass **no** `state`; `all_gates_pass` at line 106 **does**. (F2 inconsistency to fix.)
- `cli/commands/dispatch.py`: `run()` assembles `extra: list[str]` (lines 81–88: domain block, language profile path) then `_phase_request(state, phase, args, extra)` folds `extra` into `context_paths` (line 55). `run_dir = Path(args.state).resolve().parent` (line 111).
- `cli/commands/next.py`: when `res["blocked_phase"] == "CLARIFIED"` it calls `clarification.pending_from_state(state, repo)` and sets `res["open_questions"]` (lines 39–44).
- `adapters/evidence/clarification.py`: `pending_from_state(state, repo_root)` reads the CLARIFIED `acceptance_contract` evidence and returns `acceptance.pending_questions(obj)`.
- `core/module_plan.py`: `validate_module_plan(obj)`; `_validate_module(mod)` does per-module shape. `module_ids(obj)`.
- `adapters/evidence/validate.py`: `STRUCTURED_KEYS` registry. **Do NOT register `impact_assessment`** (design F5).
- `adapters/tier/recommend.py`: `_gitnexus_floor(scope)` reads `scope["gitnexus"]["impact_summary"]["risk"]` + `scope["gitnexus"]["verified"]`. Stays pure.
- `cli/commands/start.py`: `recommend.recommend_tier(request, scope, selected_tier=args.tier)` (line 90) — the only tier call; happens **before** CLARIFIED. Stores `st["tier_recommendation"]`.
- `cli/main.py`: `_COMMANDS` dict (line 21) + `build_parser` subparsers. `start` parser at lines 38–54.
- Reusable: `adapters/evidence/hashing.py:sha256_file`; legacy `adapters/scanner/_legacy/cross_service_dependency_scan.py` has `is_gitnexus_symbol_seed`, `_impact_summary_from_evidence` (risk order `LOW<MEDIUM<HIGH<CRITICAL`), `run_command`, `validate_gitnexus_degradation` to mirror.

## Locked interfaces (used across tasks — keep names identical)

```text
# adapters/evidence/impact.py
SCHEMA = "e2e-dev-harness.impact-assessment.v1"
VALID_STATUS = {"verified", "not_applicable", "blocked", "degraded"}
RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
validate_impact_assessment(obj) -> tuple[bool, str | None]
approval_matches(obj: dict, state: dict) -> bool
max_seed_risk(obj: dict) -> str | None          # highest impact[].risk, else None

# adapters/impact/base.py
class ImpactProvider(Protocol): name; inspect_index; refresh_index; resolve_seeds; assess

# adapters/impact/gitnexus.py
class GitNexusImpactProvider:
    name = "gitnexus"
    def __init__(self, *, command_runner=run_command, available=None,
                 call_timeout_s=20.0, refresh_timeout_s=120.0): ...
    def inspect_index(self, repo) -> dict
    def refresh_index(self, repo) -> dict
    def resolve_seeds(self, repo, request: dict) -> dict
    def assess(self, repo, request: dict) -> dict      # returns an impact-assessment.v1 dict

# core/impact_trigger.py  (PURE: reads state + files, never a subprocess)
required_reasons(state: dict, repo_root) -> list[str]   # [] == not required
is_documentation_only(state: dict, repo_root) -> bool

# core/impact_bridge.py
BINDING_SCHEMA = "e2e-dev-harness.impact-binding.v1"
ensure_assessment_for_planning(state, repo_root, *, provider=None) -> dict | None
    # None -> engine may proceed; {"status": "blocked", ...} -> block at CLARIFIED

# core/impact_gate.py  (PURE: in-memory binding + module_plan file read; no subprocess)
planned_missing(state: dict, repo_root, phase_record: dict) -> list[str]

# adapters/tier/impact_scope.py  (PURE)
scope_gitnexus_from_artifact(obj: dict) -> dict   # {"impact_summary": {...}, "verified": bool}
```

**Run-state additions (all additive):**

```json
{
  "impact": { "mode": "off" },                      // off|auto|strict; default off
  "impact_assessment": {                            // the binding (written by the bridge)
    "schema": "e2e-dev-harness.impact-binding.v1",
    "path": "impact-assessment.json",
    "sha256": "<artifact hash>",
    "contract_sha256": "<acceptance-contract.json hash at assessment time>",
    "status": "verified",
    "required": true,
    "risk": "LOW",
    "seeds": ["_phase_request"]                      // verified only; makes planned_missing pure
  },
  "approvals": {
    "impact_degradation": { "source": "user-approved", "approval_path": "...",
                            "sha256": "...", "recorded_by": "coordinator", "reason": "..." }
  }
}
```

---

# Slice 1: Impact Artifact + Validator

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/impact.py`
- Test: `skills/e2e-dev-harness/tests/test_impact_evidence.py`

### Task 1.1: Validator structural happy paths + status enum

- [ ] **Step 1: Write the failing test** — create `tests/test_impact_evidence.py`:

```python
from e2e_harness.adapters.evidence import impact


def _verified():
    return {
        "schema": impact.SCHEMA,
        "status": "verified",
        "tool": "gitnexus",
        "seeds": [{"kind": "symbol", "name": "_phase_request",
                   "file_path": "x.py", "reason": "r"}],
        "impact": [{"seed": "_phase_request", "direction": "upstream", "risk": "LOW",
                    "summary": {"direct": 1, "processes_affected": 1, "modules_affected": 1},
                    "affected_processes": [{"name": "run", "file_path": "x.py"}],
                    "affected_modules": ["Commands"]}],
        "planning_constraints": [], "open_questions": [], "degradation": None, "approval": None,
    }


def test_verified_artifact_passes():
    ok, reason = impact.validate_impact_assessment(_verified())
    assert ok is True and reason is None


def test_not_applicable_passes():
    obj = {"schema": impact.SCHEMA, "status": "not_applicable",
           "seeds": [], "impact": [], "open_questions": []}
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is True and reason is None


def test_not_object_rejected():
    ok, reason = impact.validate_impact_assessment(["nope"])
    assert ok is False and reason == "not-object"


def test_bad_schema_rejected():
    obj = _verified(); obj["schema"] = "wrong"
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is False and reason == "bad-schema"


def test_bad_status_rejected():
    obj = _verified(); obj["status"] = "maybe"
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is False and reason.startswith("bad-status")
```

- [ ] **Step 2: Run, expect fail** — `python -m pytest tests/test_impact_evidence.py -v` → ImportError / module missing.

- [ ] **Step 3: Create `adapters/evidence/impact.py`** with the full module (covers all of Slice 1; later tasks only add tests):

```python
"""Validate impact-assessment.json (design: GitNexus Impact Analysis).

Pure structural validator. Invoked IMPERATIVELY by impact_bridge and
impact_gate.planned_missing — deliberately NOT registered in
validate.STRUCTURED_KEYS, because impact_assessment is a run-level artifact, not a
phase exit_gate key (design F5). Degraded trust is split: `validate_impact_assessment`
checks structure only; `approval_matches` is the run-state cross-check.
"""
from __future__ import annotations

SCHEMA = "e2e-dev-harness.impact-assessment.v1"
VALID_STATUS = {"verified", "not_applicable", "blocked", "degraded"}
RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
_HIGH_RISKS = {"HIGH", "CRITICAL"}


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate_impact_assessment(obj) -> tuple[bool, str | None]:
    """(ok, reason); reason is a stable code naming the first defect."""
    if not isinstance(obj, dict):
        return False, "not-object"
    if obj.get("schema") != SCHEMA:
        return False, "bad-schema"
    status = obj.get("status")
    if status not in VALID_STATUS:
        return False, f"bad-status:{status!r}"

    seeds = obj.get("seeds", [])
    impact = obj.get("impact", [])
    if not isinstance(seeds, list) or not isinstance(impact, list):
        return False, "bad-shape"

    if status == "verified":
        if not impact:
            return False, "verified-without-impact"
        impacted = set()
        for row in impact:
            if not isinstance(row, dict):
                return False, "bad-impact-row"
            seed = row.get("seed")
            if not _nonempty_str(seed):
                return False, "bad-impact-seed"
            impacted.add(seed)
            risk = str(row.get("risk") or "").upper()
            if risk not in RISK_ORDER:
                return False, f"bad-risk:{seed}:{risk}"
            if risk in _HIGH_RISKS and not row.get("affected_processes"):
                return False, f"high-risk-without-processes:{seed}"
        # every declared seed must have an impact result
        for s in seeds:
            name = s.get("name") if isinstance(s, dict) else None
            if _nonempty_str(name) and name not in impacted:
                return False, f"seed-without-impact:{name}"

    if status == "blocked":
        oqs = obj.get("open_questions")
        defect = _validate_open_questions(oqs)
        if defect is not None:
            return False, defect
        if not oqs:
            return False, "blocked-without-open-questions"

    if status == "degraded":
        approval = obj.get("approval")
        if not isinstance(approval, dict) or not _nonempty_str(approval.get("sha256")):
            return False, "degraded-without-approval"

    return True, None


def _validate_open_questions(items) -> str | None:
    if not isinstance(items, list):
        return "bad-open-questions"
    seen: set[str] = set()
    for q in items:
        if not isinstance(q, dict):
            return "bad-open-question"
        ident = q.get("id")
        if not _nonempty_str(ident) or not ident.startswith("IQ-"):
            return f"bad-iq-id:{ident!r}"
        if ident in seen:
            return f"duplicate-iq-id:{ident}"
        seen.add(ident)
        if not _nonempty_str(q.get("question")):
            return f"empty-iq-question:{ident}"
        if q.get("status") not in {"open", "resolved", "deferred"}:
            return f"bad-iq-status:{ident}"
    return None


def open_questions(obj) -> list[dict]:
    """[{id, question}] for still-open IQ-* questions (re-clarify merge helper)."""
    out: list[dict] = []
    for q in obj.get("open_questions", []) if isinstance(obj, dict) else []:
        if isinstance(q, dict) and q.get("status") == "open" and _nonempty_str(q.get("id")):
            out.append({"id": q["id"], "question": q.get("question", "")})
    return out


def max_seed_risk(obj) -> str | None:
    """Highest impact[].risk by RISK_ORDER, else None."""
    best = 0
    best_name = None
    for row in obj.get("impact", []) if isinstance(obj, dict) else []:
        risk = str(row.get("risk") or "").upper() if isinstance(row, dict) else ""
        if RISK_ORDER.get(risk, 0) > best:
            best = RISK_ORDER[risk]
            best_name = risk
    return best_name


def approval_matches(obj, state) -> bool:
    """Run-state cross-check: artifact.approval.sha256 == state approval sha256."""
    artifact_sha = ((obj.get("approval") or {}).get("sha256")
                    if isinstance(obj, dict) else None)
    state_sha = (((state or {}).get("approvals") or {})
                 .get("impact_degradation") or {}).get("sha256")
    return bool(artifact_sha) and artifact_sha == state_sha
```

- [ ] **Step 4: Run, expect pass** — `python -m pytest tests/test_impact_evidence.py -v`.
- [ ] **Step 5: Commit** — `git add adapters/.../impact.py tests/test_impact_evidence.py && git commit -m "feat(e2e-dev-harness): impact-assessment artifact validator (Slice 1)"`

### Task 1.2: Validator edge cases (blocked / degraded / verified rigor)

- [ ] **Step 1: Append failing tests** to `tests/test_impact_evidence.py`:

```python
def test_blocked_without_open_questions_fails():
    obj = {"schema": impact.SCHEMA, "status": "blocked", "seeds": [], "impact": [],
           "open_questions": []}
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is False and reason == "blocked-without-open-questions"


def test_blocked_with_open_questions_passes():
    obj = {"schema": impact.SCHEMA, "status": "blocked", "seeds": [], "impact": [],
           "open_questions": [{"id": "IQ-001", "question": "Which handler?", "status": "open"}]}
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is True and reason is None
    assert impact.open_questions(obj) == [{"id": "IQ-001", "question": "Which handler?"}]


def test_degraded_without_approval_fails():
    obj = {"schema": impact.SCHEMA, "status": "degraded", "seeds": [], "impact": [],
           "approval": None}
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is False and reason == "degraded-without-approval"


def test_verified_high_risk_without_processes_fails():
    obj = _verified()
    obj["impact"][0]["risk"] = "HIGH"
    obj["impact"][0]["affected_processes"] = []
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is False and reason.startswith("high-risk-without-processes")


def test_verified_seed_without_impact_fails():
    obj = _verified()
    obj["seeds"].append({"kind": "symbol", "name": "orphan", "file_path": "y.py", "reason": "r"})
    ok, reason = impact.validate_impact_assessment(obj)
    assert ok is False and reason == "seed-without-impact:orphan"


def test_max_seed_risk_picks_highest():
    obj = _verified()
    obj["impact"].append({"seed": "_phase_request", "direction": "upstream", "risk": "CRITICAL",
                          "summary": {}, "affected_processes": [{"name": "x"}], "affected_modules": []})
    assert impact.max_seed_risk(obj) == "CRITICAL"


def test_approval_matches_true_and_false():
    obj = {"approval": {"sha256": "abc"}}
    assert impact.approval_matches(obj, {"approvals": {"impact_degradation": {"sha256": "abc"}}}) is True
    assert impact.approval_matches(obj, {"approvals": {"impact_degradation": {"sha256": "zzz"}}}) is False
    assert impact.approval_matches(obj, {}) is False
```

- [ ] **Step 2: Run, expect pass** (module from 1.1 already implements these): `python -m pytest tests/test_impact_evidence.py -v`. If any fail, fix `impact.py`.
- [ ] **Step 3: Commit** — `git commit -am "test(e2e-dev-harness): impact validator edge cases (Slice 1)"`

---

# Slice 2: GitNexus Impact Provider

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/impact/__init__.py` (empty)
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/impact/base.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/impact/gitnexus.py`
- Test: `skills/e2e-dev-harness/tests/test_gitnexus_impact_provider.py`

### Task 2.1: Provider interface + seed resolution

- [ ] **Step 1: Write failing test** — `tests/test_gitnexus_impact_provider.py`:

```python
from pathlib import Path
from e2e_harness.adapters.impact import gitnexus


def _runner(scripted):
    """command_runner stub: maps a substring of the joined command -> result dict."""
    def run(command, cwd):
        joined = " ".join(command)
        for needle, result in scripted.items():
            if needle in joined:
                return dict(result, command=joined)
        return {"command": joined, "exit_code": 0, "stdout": ""}
    return run


def test_resolve_seeds_filters_non_symbol_candidates():
    p = gitnexus.GitNexusImpactProvider(command_runner=_runner({}), available=True)
    out = p.resolve_seeds(Path("."), {"seed_candidates": ["_phase_request", "services/auth", "a/b.py"]})
    assert out["seeds"] == ["_phase_request"]   # service dir + path rejected
    assert out["blocked"] is False


def test_resolve_seeds_blocks_when_none_derivable():
    p = gitnexus.GitNexusImpactProvider(command_runner=_runner({}), available=True)
    out = p.resolve_seeds(Path("."), {"seed_candidates": ["services/auth"]})
    assert out["seeds"] == []
    assert out["blocked"] is True
    assert any(q["id"].startswith("IQ-") for q in out["open_questions"])
```

- [ ] **Step 2: Run, expect fail** (module missing).

- [ ] **Step 3: Create `adapters/impact/__init__.py`** (empty) and **`adapters/impact/base.py`**:

```python
"""Narrow impact-provider interface (design: Components)."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ImpactProvider(Protocol):
    name: str

    def inspect_index(self, repo: Path) -> dict: ...
    def refresh_index(self, repo: Path) -> dict: ...
    def resolve_seeds(self, repo: Path, request: dict) -> dict: ...
    def assess(self, repo: Path, request: dict) -> dict: ...
```

- [ ] **Step 4: Create `adapters/impact/gitnexus.py`** (full provider; later tasks add tests only):

```python
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

        seeds, impact_rows, questions = [], [], []
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
```

- [ ] **Step 5: Run, expect pass** — `python -m pytest tests/test_gitnexus_impact_provider.py -v`.
- [ ] **Step 6: Commit** — `git add adapters/impact tests/test_gitnexus_impact_provider.py && git commit -m "feat(e2e-dev-harness): GitNexus impact provider (Slice 2)"`

### Task 2.2: assess() — verified normalization, HIGH risk, ambiguity, unavailable

- [ ] **Step 1: Append failing tests**:

```python
def test_assess_unavailable_blocks():
    p = gitnexus.GitNexusImpactProvider(available=False)
    out = p.assess(Path("."), {"seed_candidates": ["foo"]})
    assert out["status"] == "blocked"
    assert out["open_questions"]


def test_assess_high_risk_normalized():
    impact_json = '{"risk": "HIGH", "file_path": "a.py", "summary": {"direct": 9}, ' \
                  '"affected_processes": [{"name": "checkout", "file_path": "c.py"}], ' \
                  '"affected_modules": ["Billing"]}'
    p = gitnexus.GitNexusImpactProvider(
        command_runner=_runner({"gitnexus impact foo": {"exit_code": 0, "stdout": impact_json}}),
        available=True)
    out = p.assess(Path("."), {"seed_candidates": ["foo"]})
    assert out["status"] == "verified"
    row = out["impact"][0]
    assert row["risk"] == "HIGH"
    assert row["affected_processes"][0]["name"] == "checkout"
    assert row["affected_modules"] == ["Billing"]
    ok, reason = impact.validate_impact_assessment(out)   # provider output must validate
    assert ok is True, reason


def test_assess_ambiguous_seed_blocks_with_options():
    ambiguous = '{"candidates": ["pkg.Foo", "other.Foo"]}'
    p = gitnexus.GitNexusImpactProvider(
        command_runner=_runner({"gitnexus impact Foo": {"exit_code": 0, "stdout": ambiguous}}),
        available=True)
    out = p.assess(Path("."), {"seed_candidates": ["Foo"]})
    assert out["status"] == "blocked"
    assert any("disambiguate" in q["question"] for q in out["open_questions"])


def test_assess_timeout_blocks():
    p = gitnexus.GitNexusImpactProvider(
        command_runner=_runner({"gitnexus impact foo": {"exit_code": 124, "stdout": ""}}),
        available=True)
    out = p.assess(Path("."), {"seed_candidates": ["foo"]})
    assert out["status"] == "blocked"
    assert any("timed out" in q["question"] for q in out["open_questions"])
```

Add `from e2e_harness.adapters.evidence import impact` at the top of the test file.

- [ ] **Step 2: Run, expect pass** (module from 2.1 implements these). Fix `gitnexus.py` if needed.
- [ ] **Step 3: Commit** — `git commit -am "test(e2e-dev-harness): impact provider assess() outcomes (Slice 2)"`

---

# Slice 3: Trigger, Bridge, Gate, Dispatch, Re-clarify

## Slice 3-pre: Pure trigger policy

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/impact_trigger.py`
- Test: `skills/e2e-dev-harness/tests/test_impact_trigger.py`

### Task 3.0: Trigger policy

- [ ] **Step 1: Write failing test** — `tests/test_impact_trigger.py`:

```python
from e2e_harness.core import impact_trigger


def _state(request="add a function", tier="standard", contract=None):
    st = {"request": request, "tier": tier, "phases": {}}
    return st


def test_tier_critical_requires_impact():
    reasons = impact_trigger.required_reasons(_state(tier="critical"), repo_root=None)
    assert "tier-critical" in reasons


def test_explicit_impact_request_requires_impact():
    reasons = impact_trigger.required_reasons(
        _state(request="what is the blast radius of changing checkout?"), repo_root=None)
    assert "explicit-impact" in reasons


def test_documentation_only_not_required():
    st = _state(request="update the README documentation and fix a typo", tier="minimal")
    assert impact_trigger.required_reasons(st, repo_root=None) == []
    assert impact_trigger.is_documentation_only(st, repo_root=None) is True


def test_seed_candidates_in_contract_require_impact(tmp_path):
    contract = tmp_path / "acceptance-contract.json"
    contract.write_text('{"schema": "e2e-dev-harness.acceptance-contract.v1", '
                        '"items": [{"id": "AC-001", "criterion": "c", "observable_behavior": "o"}], '
                        '"impact_seed_candidates": ["_phase_request"]}', encoding="utf-8")
    st = {"request": "change planner", "tier": "standard",
          "phases": {"CLARIFIED": {"evidence": {"acceptance_contract": {"path": str(contract)}}}}}
    reasons = impact_trigger.required_reasons(st, repo_root=str(tmp_path))
    assert "existing-symbol" in reasons
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Create `core/impact_trigger.py`**:

```python
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
```

- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** — `git add core/impact_trigger.py tests/test_impact_trigger.py && git commit -m "feat(e2e-dev-harness): pure impact trigger policy (Slice 3)"`

## Slice 3a: Bridge + engine seam

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/impact_bridge.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/engine.py` (`_evaluate_singleton`, top of loop body, ~line 180)
- Test: `skills/e2e-dev-harness/tests/test_impact_bridge.py`

### Task 3a.1: Bridge — mode off is a no-op; not-required → not_applicable; verified

- [ ] **Step 1: Write failing test** — `tests/test_impact_bridge.py`:

```python
import json
from pathlib import Path
from e2e_harness.core import impact_bridge


class _FakeProvider:
    name = "gitnexus"

    def __init__(self, result):
        self._result = result

    def assess(self, repo, request):
        return self._result


def _contract(tmp_path, seeds=("_phase_request",)):
    c = tmp_path / "acceptance-contract.json"
    c.write_text(json.dumps({
        "schema": "e2e-dev-harness.acceptance-contract.v1",
        "items": [{"id": "AC-001", "criterion": "c", "observable_behavior": "o"}],
        "impact_seed_candidates": list(seeds),
    }), encoding="utf-8")
    return c


def _state(tmp_path, mode, contract, tier="standard", request="change the planner module"):
    run_state_path = tmp_path / "run-state.json"
    return {
        "run_id": "r1", "request": request, "tier": tier,
        "impact": {"mode": mode},
        "_run_state_path": str(run_state_path),
        "phases": {"CLARIFIED": {"evidence": {"acceptance_contract": {"path": str(contract)}}}},
    }


def test_mode_off_is_noop(tmp_path):
    st = _state(tmp_path, "off", _contract(tmp_path))
    assert impact_bridge.ensure_assessment_for_planning(st, str(tmp_path)) is None
    assert "impact_assessment" not in st


def test_not_required_writes_not_applicable(tmp_path):
    # doc-only request, minimal tier, no seed candidates -> not required
    st = _state(tmp_path, "auto", _contract(tmp_path, seeds=[]),
                tier="minimal", request="update the documentation")
    decision = impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=_FakeProvider(None))
    assert decision is None
    assert st["impact_assessment"]["status"] == "not_applicable"
    assert st["impact_assessment"]["required"] is False
    assert (tmp_path / "impact-assessment.json").exists()


def test_verified_writes_binding_with_seeds(tmp_path):
    verified = {
        "schema": "e2e-dev-harness.impact-assessment.v1", "status": "verified", "tool": "gitnexus",
        "seeds": [{"kind": "symbol", "name": "_phase_request", "file_path": "x.py", "reason": "r"}],
        "impact": [{"seed": "_phase_request", "direction": "upstream", "risk": "LOW",
                    "summary": {}, "affected_processes": [{"name": "run"}], "affected_modules": []}],
        "open_questions": [], "degradation": None, "approval": None,
    }
    st = _state(tmp_path, "auto", _contract(tmp_path))
    decision = impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=_FakeProvider(verified))
    assert decision is None
    b = st["impact_assessment"]
    assert b["status"] == "verified" and b["required"] is True
    assert b["seeds"] == ["_phase_request"]
    assert b["risk"] == "LOW"
    assert b["contract_sha256"]


def test_blocked_returns_block_and_persists(tmp_path):
    blocked = {"schema": "e2e-dev-harness.impact-assessment.v1", "status": "blocked",
               "seeds": [], "impact": [],
               "open_questions": [{"id": "IQ-001", "question": "Which handler?", "status": "open"}]}
    st = _state(tmp_path, "strict", _contract(tmp_path))
    decision = impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=_FakeProvider(blocked))
    assert decision is not None and decision["status"] == "blocked"
    assert st["impact_assessment"]["status"] == "blocked"


def test_idempotent_on_contract_hash(tmp_path):
    verified = {
        "schema": "e2e-dev-harness.impact-assessment.v1", "status": "verified", "tool": "gitnexus",
        "seeds": [{"kind": "symbol", "name": "_phase_request", "file_path": "x.py", "reason": "r"}],
        "impact": [{"seed": "_phase_request", "direction": "upstream", "risk": "LOW",
                    "summary": {}, "affected_processes": [{"name": "run"}], "affected_modules": []}],
        "open_questions": [], "degradation": None, "approval": None,
    }
    st = _state(tmp_path, "auto", _contract(tmp_path))

    class _CountingProvider(_FakeProvider):
        calls = 0
        def assess(self, repo, request):
            _CountingProvider.calls += 1
            return verified

    prov = _CountingProvider(verified)
    impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=prov)
    impact_bridge.ensure_assessment_for_planning(st, str(tmp_path), provider=prov)
    assert _CountingProvider.calls == 1   # second call served from binding cache
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Create `core/impact_bridge.py`**:

```python
"""Impact assessment bridge (design: Trigger Policy, Evaluation Point).

The single source of truth for "is impact required and satisfied". Called by
engine._evaluate_singleton as the cursor reaches PLANNED. Idempotent on the
acceptance-contract hash: a binding whose contract_sha256 still matches is reused
without touching GitNexus; an amended contract invalidates a stale assessment.

Returns None when the engine may proceed (not_applicable / verified / approved
degraded, or impact.mode == off). Returns {"status": "blocked", ...} when the run
must go back to CLARIFIED (the CLARIFIED edge owns `blocked`, design Status
Ownership).
"""
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.adapters.evidence import hashing, impact as impact_ev
from e2e_harness.core import impact_trigger

BINDING_SCHEMA = "e2e-dev-harness.impact-binding.v1"
_ARTIFACT_NAME = "impact-assessment.json"


def _mode(state: dict) -> str:
    return str((state.get("impact") or {}).get("mode") or "off")


def _contract_entry(state: dict):
    return (state.get("phases", {}).get("CLARIFIED", {})
            .get("evidence", {}).get("acceptance_contract"))


def _contract_path(state: dict, repo_root) -> Path | None:
    entry = _contract_entry(state)
    if not entry:
        return None
    rel = entry["path"] if isinstance(entry, dict) else entry
    full = Path(rel)
    if not full.is_absolute() and repo_root is not None:
        full = Path(repo_root) / rel
    return full if full.is_file() else None


def _contract_sha(state: dict, repo_root) -> str | None:
    p = _contract_path(state, repo_root)
    return hashing.sha256_file(p) if p else None


def _run_dir(state: dict, repo_root) -> Path:
    rsp = state.get("_run_state_path")
    if rsp:
        return Path(rsp).resolve().parent
    return Path(repo_root) / "docs" / "agent-runs" / str(state.get("run_id") or "run")


def _seed_candidates(state: dict, repo_root) -> list[str]:
    p = _contract_path(state, repo_root)
    if not p:
        return []
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cands = obj.get("impact_seed_candidates")
    return [c for c in cands if isinstance(c, str)] if isinstance(cands, list) else []


def _write_artifact(state: dict, repo_root, artifact: dict) -> Path:
    run_dir = _run_dir(state, repo_root)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / _ARTIFACT_NAME
    path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _bind(state: dict, *, path: Path, repo_root, contract_sha: str | None,
          artifact: dict, required: bool) -> dict:
    rsp = state.get("_run_state_path")
    rel = str(path)
    if rsp:
        try:
            rel = str(path.relative_to(Path(rsp).resolve().parent))
        except ValueError:
            rel = str(path)
    binding = {
        "schema": BINDING_SCHEMA,
        "path": rel,
        "sha256": hashing.sha256_file(path),
        "contract_sha256": contract_sha,
        "status": artifact["status"],
        "required": required,
        "risk": impact_ev.max_seed_risk(artifact),
        "seeds": [s["name"] for s in artifact.get("seeds", [])
                  if isinstance(s, dict) and s.get("name")] if artifact["status"] == "verified" else [],
    }
    state["impact_assessment"] = binding
    return binding


def _not_applicable_artifact() -> dict:
    return {"schema": impact_ev.SCHEMA, "status": "not_applicable", "tool": "gitnexus",
            "seeds": [], "impact": [], "planning_constraints": [], "open_questions": [],
            "degradation": None, "approval": None}


def ensure_assessment_for_planning(state, repo_root, *, provider=None) -> dict | None:
    if _mode(state) == "off":
        return None

    contract_sha = _contract_sha(state, repo_root)
    existing = state.get("impact_assessment")
    if (existing and existing.get("contract_sha256") == contract_sha
            and contract_sha is not None):
        # idempotent: fresh binding for this contract -> reuse decision
        return {"status": "blocked"} if existing.get("status") == "blocked" else None

    reasons = impact_trigger.required_reasons(state, repo_root)
    if not reasons:
        path = _write_artifact(state, repo_root, _not_applicable_artifact())
        _bind(state, path=path, repo_root=repo_root, contract_sha=contract_sha,
              artifact=_not_applicable_artifact(), required=False)
        return None

    if provider is None:
        from e2e_harness.adapters.impact.gitnexus import GitNexusImpactProvider
        provider = GitNexusImpactProvider()

    artifact = provider.assess(Path(repo_root) if repo_root else Path("."),
                               {"seed_candidates": _seed_candidates(state, repo_root),
                                "request": state.get("request", ""), "reasons": reasons})
    artifact.setdefault("trigger", {"required": True, "reason_codes": reasons,
                                    "evaluated_at_phase": "CLARIFIED"})
    path = _write_artifact(state, repo_root, artifact)
    _bind(state, path=path, repo_root=repo_root, contract_sha=contract_sha,
          artifact=artifact, required=True)
    if artifact["status"] == "blocked":
        return {"status": "blocked"}
    return None
```

- [ ] **Step 4: Run, expect pass** — `python -m pytest tests/test_impact_bridge.py -v`.
- [ ] **Step 5: Commit** — `git add core/impact_bridge.py tests/test_impact_bridge.py && git commit -m "feat(e2e-dev-harness): impact bridge (Slice 3a)"`

### Task 3a.2: Engine seam — call the bridge at PLANNED

- [ ] **Step 1: Write failing test** — append to `tests/test_impact_bridge.py` an engine-level test that drives `_evaluate_singleton` to PLANNED and asserts a blocked impact reopens CLARIFIED:

```python
from e2e_harness.core import engine, lifecycle


def _spine():
    return lifecycle.build_spine(["CLARIFIED", "PLANNED", "RED", "IMPLEMENTED", "REVIEWED", "VERIFIED"])


def _passing_clarified(tmp_path, contract):
    # minimal evidence so CLARIFIED gate passes: clarification + acceptance_contract present
    clar = tmp_path / "clarification.md"; clar.write_text("done", encoding="utf-8")
    return {"evidence": {"clarification": {"path": str(clar)},
                         "acceptance_contract": {"path": str(contract)}}}


def test_engine_blocks_at_clarified_on_blocked_impact(tmp_path, monkeypatch):
    blocked = {"schema": "e2e-dev-harness.impact-assessment.v1", "status": "blocked",
               "seeds": [], "impact": [],
               "open_questions": [{"id": "IQ-001", "question": "Which handler?", "status": "open"}]}
    monkeypatch.setattr(
        "e2e_harness.core.impact_bridge.ensure_assessment_for_planning",
        lambda state, repo_root, **k: (_persist(state, blocked) or {"status": "blocked"}))

    contract = _contract(tmp_path)
    rsp = tmp_path / "run-state.json"
    state = {"run_id": "r1", "request": "change planner", "tier": "standard",
             "impact": {"mode": "strict"}, "current_phase": "PLANNED",
             "_run_state_path": str(rsp),
             "phases": {"CLARIFIED": _passing_clarified(tmp_path, contract)}}
    res = engine.evaluate(_spine(), state, str(tmp_path))
    assert res["blocked_phase"] == "CLARIFIED"
    assert state["current_phase"] == "CLARIFIED"


def _persist(state, artifact):
    state["impact_assessment"] = {"schema": "e2e-dev-harness.impact-binding.v1",
                                  "status": artifact["status"], "required": True,
                                  "path": "impact-assessment.json"}
    return None
```

(Use `monkeypatch` to keep the engine test independent of the provider.)

- [ ] **Step 2: Run, expect fail** — engine does not yet call the bridge; it would block at PLANNED for missing plan/module_plan instead of CLARIFIED.

- [ ] **Step 3: Edit `core/engine.py`** — in `_evaluate_singleton`, insert the bridge call at the **top of the loop body**, immediately after `rec = state.get("phases", {}).get(name, {})` and **before** `ok, missing = gates.gate_passes(...)`:

```python
        phase = by_name[name]
        rec = state.get("phases", {}).get(name, {})
        # Impact bridge (design: Evaluation Point). Reached when the cursor arrives
        # at PLANNED — covers BOTH the forward CLARIFIED->PLANNED edge (the walk just
        # advanced here) and re-entry at a stored PLANNED cursor (resume/migrate/
        # amended contract). Idempotent on the contract hash. A `blocked` decision is
        # owned by the CLARIFIED edge: leave the cursor at CLARIFIED and surface its
        # blocker (next.py merges the IQ-* questions).
        if (phase.name == "PLANNED" and repo_root is not None
                and "CLARIFIED" in by_name):
            from e2e_harness.core import impact_bridge
            decision = impact_bridge.ensure_assessment_for_planning(state, repo_root)
            if decision is not None and decision.get("status") == "blocked":
                state["current_phase"] = "CLARIFIED"
                clarified = by_name["CLARIFIED"]
                return {
                    "complete": False,
                    "blocked_phase": "CLARIFIED",
                    "missing_evidence": ["impact_assessment"],
                    "next_action": dispatch.worker_packet(
                        clarified, state.get("_run_state_path", "")),
                }
        ok, missing = gates.gate_passes(phase, rec, repo_root, state=state)
```

- [ ] **Step 4: Run, expect pass** — `python -m pytest tests/test_impact_bridge.py -v`.
- [ ] **Step 5: Run full suite** — `python -m pytest tests/ -q` → still **675 passed** (+ new). Existing runs have no `impact.mode` → bridge returns None → no behavior change.
- [ ] **Step 6: Commit** — `git commit -am "feat(e2e-dev-harness): call impact bridge from engine at PLANNED (Slice 3a)"`

## Slice 3b: Re-clarification bridge

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/clarification.py` (`pending_from_state`)
- Test: `skills/e2e-dev-harness/tests/test_impact_bridge.py` (append) or a focused test in `test_dispatch_impact_context.py`

### Task 3b.1: Merge IQ-* questions from a blocked impact artifact

- [ ] **Step 1: Write failing test** — append to `tests/test_impact_bridge.py`:

```python
from e2e_harness.adapters.evidence import clarification


def test_pending_merges_impact_iq_questions(tmp_path):
    contract = tmp_path / "acceptance-contract.json"
    contract.write_text(json.dumps({
        "schema": "e2e-dev-harness.acceptance-contract.v1",
        "items": [{"id": "AC-001", "criterion": "c", "observable_behavior": "o"}],
        "open_questions": [{"id": "OQ-001", "question": "Scope?", "status": "open"}],
    }), encoding="utf-8")
    art = tmp_path / "impact-assessment.json"
    art.write_text(json.dumps({
        "schema": "e2e-dev-harness.impact-assessment.v1", "status": "blocked",
        "seeds": [], "impact": [],
        "open_questions": [{"id": "IQ-001", "question": "Which handler?", "status": "open"}],
    }), encoding="utf-8")
    state = {"_run_state_path": str(tmp_path / "run-state.json"),
             "impact_assessment": {"status": "blocked", "path": "impact-assessment.json"},
             "phases": {"CLARIFIED": {"evidence": {"acceptance_contract": {"path": str(contract)}}}}}
    pending = clarification.pending_from_state(state, str(tmp_path))
    ids = {q["id"] for q in pending}
    assert {"OQ-001", "IQ-001"} <= ids
```

- [ ] **Step 2: Run, expect fail** (only OQ-001 returned today).

- [ ] **Step 3: Edit `adapters/evidence/clarification.py`** — extend `pending_from_state` to append IQ-* from a blocked impact artifact. Add after computing the acceptance questions:

```python
from e2e_harness.adapters.evidence import impact as impact_ev


def pending_from_state(state: dict, repo_root) -> list[dict]:
    """[{id, question}] still-open questions: acceptance OQ-* plus blocked-impact IQ-*."""
    out = _acceptance_pending(state, repo_root)
    out.extend(_impact_pending(state, repo_root))
    return out


def _acceptance_pending(state: dict, repo_root) -> list[dict]:
    entry = (state.get("phases", {}).get("CLARIFIED", {})
             .get("evidence", {}).get("acceptance_contract"))
    if not entry:
        return []
    rel = entry["path"] if isinstance(entry, dict) else entry
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel
    try:
        obj = json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return acceptance.pending_questions(obj)


def _impact_pending(state: dict, repo_root) -> list[dict]:
    binding = state.get("impact_assessment")
    if not binding or binding.get("status") != "blocked":
        return []
    rel = binding.get("path")
    if not rel:
        return []
    full = Path(rel)
    if not full.is_absolute():
        base = state.get("_run_state_path")
        base_dir = Path(base).resolve().parent if base else Path(repo_root)
        full = base_dir / rel
    try:
        obj = json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return impact_ev.open_questions(obj)
```

(Keep the original module docstring; this replaces the single-function body. `_impact_pending` resolves the artifact path relative to the run dir, matching how the bridge stores it.)

- [ ] **Step 4: Run, expect pass** — `python -m pytest tests/test_impact_bridge.py -v`.
- [ ] **Step 5: Full suite** — `python -m pytest tests/ -q` (existing clarification tests must still pass; no binding → `_impact_pending` returns []).
- [ ] **Step 6: Commit** — `git commit -am "feat(e2e-dev-harness): merge blocked-impact IQ questions into re-clarify (Slice 3b)"`

## Slice 3c: Dispatch context injection

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py` (`run()`, after the language profile block ~line 88)
- Test: `skills/e2e-dev-harness/tests/test_dispatch_impact_context.py`

### Task 3c.1: Append the artifact path to `context_paths` by phase + status

- [ ] **Step 1: Write failing test** — `tests/test_dispatch_impact_context.py`. Reuse the existing dispatch test conventions (see `tests/test_dispatch_domain.py` for how a run-state + args are built). Skeleton:

```python
import json
from pathlib import Path
from types import SimpleNamespace

from e2e_harness.core import run_state
from e2e_harness.cli.commands import dispatch


def _mk_run(tmp_path, current_phase, status):
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"
    run_dir.mkdir(parents=True)
    state_path = run_dir / "run-state.json"
    art = run_dir / "impact-assessment.json"
    art.write_text(json.dumps({"schema": "e2e-dev-harness.impact-assessment.v1",
                               "status": status, "seeds": [], "impact": [],
                               "open_questions": []}), encoding="utf-8")
    st = run_state.new_run_state("r1", "feat", "change the planner", tier="standard", pipeline="standard")
    st["current_phase"] = current_phase
    st["impact"] = {"mode": "auto"}
    st["impact_assessment"] = {"status": status, "path": "impact-assessment.json"}
    # give the current phase a worker_skill by using a real built-in pipeline spine
    run_state.save(state_path, st)
    return state_path


def _args(state_path, tmp_path):
    return SimpleNamespace(state=str(state_path), repo=str(tmp_path), runtime="codex",
                           team_profile=None, max_workers=None, json=False)


def test_planned_packet_includes_impact_path(tmp_path):
    state_path = _mk_run(tmp_path, "PLANNED", "verified")
    code, packet = dispatch.run(_args(state_path, tmp_path))
    paths = packet["agent_team_plan"]["workers"][0]  # see assertion note below
    # The artifact path must appear in the phase request context_paths:
    req = packet["agent_team_plan"]
    assert any("impact-assessment.json" in p for p in _context_paths(packet))


def _context_paths(packet):
    # context_paths live on the phase request inside the team plan; helper keeps the
    # assertion resilient to packet shape. Inspect packet/team_plan for the request.
    blob = json.dumps(packet)
    return [seg for seg in [blob] if "impact-assessment.json" in seg]
```

> Note: confirm the exact packet field carrying `context_paths` by reading `tests/test_dispatch_domain.py` first; assert on that field directly (e.g. the request's `context_paths`) rather than a JSON-blob substring. Adjust `_mk_run` so the current phase has a `worker_skill` (use a built-in pipeline; PLANNED has one in the default spine).

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Edit `cli/commands/dispatch.py`** — in `run()`, after the language profile append (after line 88, before the multitrack fan-out block ~line 89), add:

```python
    # Impact evidence (design: dispatch seam). Transport ONLY — never interpreted
    # here. Inclusion is gated by phase + artifact status.
    binding = state.get("impact_assessment")
    if binding:
        art_path = _impact_artifact_path(args, binding)
        if art_path is not None and _impact_visible(name, binding.get("status")):
            extra.append(str(art_path))
```

Add module-level helpers near the top of `dispatch.py`:

```python
def _impact_artifact_path(args, binding) -> Path | None:
    rel = binding.get("path")
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = Path(args.state).resolve().parent / rel
    return p if p.is_file() else None


_IMPACT_VISIBLE = {
    "CLARIFIED": {"blocked"},
    "PLANNED": {"verified", "degraded", "not_applicable"},
    "RED": {"verified", "degraded"},
    "IMPLEMENTED": {"verified", "degraded"},
    "REVIEWED": {"verified", "degraded"},
}


def _impact_visible(phase_name: str, status: str | None) -> bool:
    base = phase_name.split("#", 1)[0]   # module-namespaced phases share the base rule
    return status in _IMPACT_VISIBLE.get(base, set())
```

- [ ] **Step 4: Run, expect pass.** Add a second test: CLARIFIED + blocked includes the path; CLARIFIED + verified does NOT.
- [ ] **Step 5: Full suite** — `python -m pytest tests/ -q` (no binding → no extra path → existing dispatch tests unchanged).
- [ ] **Step 6: Commit** — `git commit -am "feat(e2e-dev-harness): inject impact artifact into dispatch context (Slice 3c)"`

## Slice 3d: PLANNED supplemental gate

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/impact_gate.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/gates.py` (`gate_passes`, after the `missing` loop ~line 38)
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/navigation.py` (thread `state`)
- Test: `skills/e2e-dev-harness/tests/test_impact_gate.py`, `tests/test_navigation_impact_consistency.py`

### Task 3d.1: `impact_gate.planned_missing`

- [ ] **Step 1: Write failing test** — `tests/test_impact_gate.py`:

```python
import json
from pathlib import Path
from e2e_harness.core import impact_gate


def _module_plan(tmp_path, impact_refs=None):
    mp = {"schema": "e2e-dev-harness.module-plan.v1",
          "modules": [{"id": "m1", "name": "M1", "depends_on": [], "acceptance_ids": ["AC-001"]}]}
    if impact_refs is not None:
        mp["modules"][0]["impact_refs"] = impact_refs
    p = tmp_path / "module-plan.json"
    p.write_text(json.dumps(mp), encoding="utf-8")
    return p


def _planned_rec(mp_path):
    return {"evidence": {"module_plan": {"path": str(mp_path)}}}


def test_no_binding_no_block(tmp_path):
    assert impact_gate.planned_missing({}, str(tmp_path), {}) == []


def test_not_required_no_block(tmp_path):
    st = {"impact_assessment": {"required": False, "status": "not_applicable"}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == []


def test_blocked_not_reported_here(tmp_path):
    st = {"impact_assessment": {"required": True, "status": "blocked"}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == []   # owned by CLARIFIED edge


def test_verified_requires_refs(tmp_path):
    mp = _module_plan(tmp_path, impact_refs=None)
    st = {"impact_assessment": {"required": True, "status": "verified", "seeds": ["_phase_request"]}}
    assert impact_gate.planned_missing(st, str(tmp_path), _planned_rec(mp)) == ["impact_refs"]


def test_verified_with_matching_refs_passes(tmp_path):
    mp = _module_plan(tmp_path, impact_refs=[{"seed": "_phase_request",
                                              "affected_processes": ["run"], "test_focus": ["x"]}])
    st = {"impact_assessment": {"required": True, "status": "verified", "seeds": ["_phase_request"]}}
    assert impact_gate.planned_missing(st, str(tmp_path), _planned_rec(mp)) == []


def test_degraded_without_matching_approval_blocks(tmp_path):
    art = tmp_path / "impact-assessment.json"
    art.write_text(json.dumps({"schema": "e2e-dev-harness.impact-assessment.v1",
                               "status": "degraded", "seeds": [], "impact": [],
                               "approval": {"sha256": "abc"}}), encoding="utf-8")
    st = {"_run_state_path": str(tmp_path / "run-state.json"),
          "approvals": {"impact_degradation": {"sha256": "MISMATCH"}},
          "impact_assessment": {"required": True, "status": "degraded", "path": "impact-assessment.json"}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == ["impact_degradation_approval"]


def test_missing_binding_but_required_is_backstop(tmp_path):
    # No binding, but the trigger says required -> backstop reports impact_assessment.
    contract = tmp_path / "acceptance-contract.json"
    contract.write_text(json.dumps({"schema": "e2e-dev-harness.acceptance-contract.v1",
                                    "items": [{"id": "AC-001", "criterion": "c", "observable_behavior": "o"}],
                                    "impact_seed_candidates": ["_phase_request"]}), encoding="utf-8")
    st = {"request": "change planner", "tier": "critical", "impact": {"mode": "strict"},
          "phases": {"CLARIFIED": {"evidence": {"acceptance_contract": {"path": str(contract)}}}}}
    assert impact_gate.planned_missing(st, str(tmp_path), {}) == ["impact_assessment"]
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Create `core/impact_gate.py`**:

```python
"""PLANNED supplemental impact gate (design: PLANNED Supplemental Gate).

Pure: reads the run-state binding and the submitted module_plan only — no
subprocess, no replay. Status ownership (design): `blocked` is owned by the
CLARIFIED edge and is NOT reported here; this gate owns `impact_refs`,
`impact_degradation_approval`, and the missing-binding backstop.
"""
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.adapters.evidence import impact as impact_ev
from e2e_harness.core import impact_trigger


def planned_missing(state: dict, repo_root, phase_record: dict) -> list[str]:
    binding = state.get("impact_assessment")
    if not binding:
        # Backstop: a caller reached the gate without the engine's just-ran helper.
        # Only a defect if the pure trigger says impact was required.
        if str((state.get("impact") or {}).get("mode") or "off") == "off":
            return []
        return ["impact_assessment"] if impact_trigger.required_reasons(state, repo_root) else []

    if not binding.get("required"):
        return []
    status = binding.get("status")
    if status in (None,):
        return ["impact_assessment"]
    if status == "blocked":
        return []   # owned by CLARIFIED edge; never double-reported
    if status == "not_applicable":
        return []
    if status == "degraded":
        obj = _load_artifact(state, binding, repo_root)
        if obj is None or not impact_ev.approval_matches(obj, state):
            return ["impact_degradation_approval"]
        return []
    # verified: the module plan must reference every binding seed
    seeds = set(binding.get("seeds") or [])
    if not seeds:
        return []
    covered = _covered_seeds(phase_record, repo_root)
    return [] if seeds.issubset(covered) else ["impact_refs"]


def _load_artifact(state: dict, binding: dict, repo_root):
    rel = binding.get("path")
    if not rel:
        return None
    full = Path(rel)
    if not full.is_absolute():
        base = state.get("_run_state_path")
        base_dir = Path(base).resolve().parent if base else Path(repo_root)
        full = base_dir / rel
    try:
        return json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _covered_seeds(phase_record: dict, repo_root) -> set[str]:
    entry = (phase_record or {}).get("evidence", {}).get("module_plan")
    if not entry:
        return set()
    rel = entry["path"] if isinstance(entry, dict) else entry
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel
    try:
        obj = json.loads(full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    covered: set[str] = set()
    for mod in obj.get("modules", []) if isinstance(obj, dict) else []:
        for ref in (mod.get("impact_refs") or []) if isinstance(mod, dict) else []:
            if isinstance(ref, dict) and isinstance(ref.get("seed"), str):
                covered.add(ref["seed"])
    return covered
```

- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** — `git add core/impact_gate.py tests/test_impact_gate.py && git commit -m "feat(e2e-dev-harness): PLANNED supplemental impact gate (Slice 3d)"`

### Task 3d.2: Wire the gate into `gates.gate_passes`

- [ ] **Step 1: Write failing test** — append to `tests/test_impact_gate.py`:

```python
from e2e_harness.core import gates, lifecycle


def test_gate_passes_reports_impact_refs_for_planned(tmp_path):
    mp = _module_plan(tmp_path, impact_refs=None)
    rec = _planned_rec(mp)
    rec["evidence"]["plan"] = {"path": str(_plain(tmp_path, "plan.md"))}
    planned = next(p for p in lifecycle.build_spine(["CLARIFIED", "PLANNED"]) if p.name == "PLANNED")
    st = {"impact_assessment": {"required": True, "status": "verified", "seeds": ["_phase_request"]}}
    ok, missing = gates.gate_passes(planned, rec, str(tmp_path), state=st)
    assert ok is False and "impact_refs" in missing


def test_gate_passes_no_state_skips_impact(tmp_path):
    mp = _module_plan(tmp_path, impact_refs=None)
    rec = _planned_rec(mp)
    rec["evidence"]["plan"] = {"path": str(_plain(tmp_path, "plan.md"))}
    planned = next(p for p in lifecycle.build_spine(["CLARIFIED", "PLANNED"]) if p.name == "PLANNED")
    ok, missing = gates.gate_passes(planned, rec, str(tmp_path))   # no state
    assert "impact_refs" not in missing


def _plain(tmp_path, name):
    p = tmp_path / name; p.write_text("x", encoding="utf-8"); return p
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Edit `core/gates.py`** — in `gate_passes`, after the per-key `missing` loop and before the failures loop (after line ~38), add:

```python
    # PLANNED supplemental impact gate (design). State-aware and pure: only with a
    # threaded run-state, and only for PLANNED, so base-gate unit tests that pass no
    # state legitimately skip it.
    if state is not None and phase.name == "PLANNED":
        from e2e_harness.core import impact_gate
        missing.extend(impact_gate.planned_missing(state, repo_root, rec))
```

- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Full suite** — `python -m pytest tests/ -q`. Existing PLANNED tests pass no `impact_assessment` binding; with `state` threaded by the engine, `planned_missing` returns `[]` when `impact.mode` is off/absent and no binding → no change.
- [ ] **Step 6: Commit** — `git commit -am "feat(e2e-dev-harness): wire impact gate into PLANNED gate_passes (Slice 3d)"`

### Task 3d.3: Thread `state` into navigation (F2 presence-gate consistency)

- [ ] **Step 1: Write failing test** — `tests/test_navigation_impact_consistency.py`: build a run parked at PLANNED with a verified-required binding and a module_plan lacking refs; assert `navigation_map`'s PLANNED row reports `impact_refs` missing and `next` points at PLANNED — matching `all_gates_pass`.

```python
import json
from pathlib import Path
from e2e_harness.core import navigation, lifecycle, run_state


def test_navigation_planned_row_reflects_impact_gate(tmp_path):
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"; run_dir.mkdir(parents=True)
    mp = run_dir / "module-plan.json"
    mp.write_text(json.dumps({"schema": "e2e-dev-harness.module-plan.v1",
                              "modules": [{"id": "m1", "name": "M1", "depends_on": [],
                                           "acceptance_ids": ["AC-001"]}]}), encoding="utf-8")
    plan = run_dir / "plan.md"; plan.write_text("p", encoding="utf-8")
    spine = lifecycle.build_spine(["CLARIFIED", "PLANNED", "RED", "IMPLEMENTED", "REVIEWED", "VERIFIED"])
    state = {"current_phase": "PLANNED", "impact": {"mode": "strict"},
             "impact_assessment": {"required": True, "status": "verified", "seeds": ["s1"]},
             "phases": {"PLANNED": {"evidence": {"plan": {"path": str(plan)},
                                                 "module_plan": {"path": str(mp)}}}}}
    nav = navigation.navigation_map(spine, state, str(tmp_path))
    planned_row = next(p for p in nav["phases"] if p["name"] == "PLANNED")
    assert "impact_refs" in planned_row["gate"]["missing"]
```

- [ ] **Step 2: Run, expect fail** (per-phase navigation calls omit `state`).

- [ ] **Step 3: Edit `core/navigation.py`** — thread `state` into the per-phase `gate_passes` calls:
  - `_phase_status` (lines 60, 63): change signature to accept `state` and pass `state=state`.
  - `navigation_map` main loop (line 81): pass `state=state`.
  - `_track_lanes` (line 25): pass `state=state` (harmless for module-band phases; keeps the rule uniform).
  - Update `_phase_status` callers to pass `state`.

Concretely:

```python
def _phase_status(spine, state, idx, repo_root=None, *, skip_replay=True):
    ...
    if idx < cur_idx:
        ok, _ = gates.gate_passes(phase, rec, repo_root, skip_replay=skip_replay, state=state)
        return "done" if ok else "blocked"
    if idx == cur_idx:
        ok, _ = gates.gate_passes(phase, rec, repo_root, skip_replay=skip_replay, state=state)
        ...
```
```python
# navigation_map main loop:
        ok, missing = gates.gate_passes(p, rec, repo_root, skip_replay=skip_replay, state=state)
```
```python
# _track_lanes:
            ok, missing = gates.gate_passes(phase, rec, repo_root, skip_replay=skip_replay, state=state)
```

- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Full suite** — `python -m pytest tests/ -q`. **Watch for scope_manifest regressions**: threading `state` switches the VERIFIED `scope_manifest` validator from tables-only to state-grounded in navigation rows. If a navigation/scope test breaks, narrow the change to pass `state` only for the `PLANNED` row (gate it on `p.name == "PLANNED"`), since impact is the only state-dependent navigation key being added.
- [ ] **Step 6: Commit** — `git commit -am "fix(e2e-dev-harness): thread state into navigation so impact gate is display-consistent (Slice 3d/F2)"`

---

# Slice 4: Module Plan References

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/module_plan.py` (`_validate_module`)
- Test: `skills/e2e-dev-harness/tests/test_module_plan_impact_refs.py`

### Task 4.1: Accept optional `impact_refs` shape; enforcement stays in the gate

- [ ] **Step 1: Write failing test** — `tests/test_module_plan_impact_refs.py`:

```python
from e2e_harness.core import module_plan


def _plan(refs):
    return {"schema": "e2e-dev-harness.module-plan.v1",
            "modules": [{"id": "m1", "name": "M1", "depends_on": [], "acceptance_ids": ["AC-001"],
                         "impact_refs": refs}]}


def test_optional_impact_refs_absent_is_valid():
    ok, reason = module_plan.validate_module_plan(
        {"schema": "e2e-dev-harness.module-plan.v1",
         "modules": [{"id": "m1", "name": "M1", "depends_on": [], "acceptance_ids": ["AC-001"]}]})
    assert ok is True and reason is None   # back-compat preserved


def test_valid_impact_refs_accepted():
    ok, reason = module_plan.validate_module_plan(
        _plan([{"seed": "_phase_request", "affected_processes": ["run"], "test_focus": ["x"]}]))
    assert ok is True and reason is None


def test_impact_refs_must_be_list():
    ok, reason = module_plan.validate_module_plan(_plan("nope"))
    assert ok is False and reason.startswith("bad-impact-refs")


def test_impact_ref_requires_seed():
    ok, reason = module_plan.validate_module_plan(_plan([{"affected_processes": ["run"]}]))
    assert ok is False and reason.startswith("bad-impact-ref")
```

- [ ] **Step 2: Run, expect fail** (`bad-impact-refs`/`bad-impact-ref` not produced yet; or the `"nope"` string is silently accepted).

- [ ] **Step 3: Edit `core/module_plan.py`** — in `_validate_module`, before `return mid, None`, add:

```python
    refs = mod.get("impact_refs", [])
    if not isinstance(refs, list):
        return mid, f"bad-impact-refs:{mid}"
    for ref in refs:
        if not isinstance(ref, dict) or not _nonempty_str(ref.get("seed")):
            return mid, f"bad-impact-ref:{mid}"
        procs = ref.get("affected_processes", [])
        focus = ref.get("test_focus", [])
        if not isinstance(procs, list) or not isinstance(focus, list):
            return mid, f"bad-impact-ref-fields:{mid}"
    return mid, None
```

- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Full suite** — `python -m pytest tests/ -q` (existing module_plan tests must stay green; `impact_refs` is optional).
- [ ] **Step 6: Commit** — `git add core/module_plan.py tests/test_module_plan_impact_refs.py && git commit -m "feat(e2e-dev-harness): module_plan accepts optional impact_refs (Slice 4)"`

> Requirement enforcement (impact_refs required when impact is required+verified) is already implemented and tested in Slice 3d (`impact_gate.planned_missing` → `impact_refs`). No further enforcement code is added here, by design (module_plan validation is pure structure; the gate owns the requirement).

---

# Slice 5: Tier Derivation + Coordinator Approval Command

## Slice 5a: Pure impact → scope.gitnexus derivation

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/impact_scope.py`
- Test: `skills/e2e-dev-harness/tests/test_tier_recommend_impact.py`

> Scope note (verified gap): there is no existing post-clarification re-tier call site — `recommend_tier` runs once in `start.py` before CLARIFIED. So Slice 5 ships the **canonical, pure reduction** (design F6) plus a regression check that `recommend_tier` reacts correctly to a derived `scope.gitnexus`. Wiring an actual post-clarification re-tier command is intentionally out of scope (no consumer exists yet); `recommend.py` stays pure and unchanged.

### Task 5a.1: Derivation helper + recommender reaction

- [ ] **Step 1: Write failing test** — `tests/test_tier_recommend_impact.py`:

```python
from e2e_harness.adapters.tier import impact_scope, recommend


def _artifact(status, risks):
    return {"schema": "e2e-dev-harness.impact-assessment.v1", "status": status,
            "seeds": [{"name": f"s{i}"} for i, _ in enumerate(risks)],
            "impact": [{"seed": f"s{i}", "risk": r, "summary": {}, "affected_processes": [{"name": "p"}]}
                       for i, r in enumerate(risks)]}


def test_derivation_max_risk_and_verified_flag():
    scope = impact_scope.scope_gitnexus_from_artifact(_artifact("verified", ["LOW", "HIGH"]))
    assert scope == {"impact_summary": {"risk": "HIGH"}, "verified": True}


def test_derivation_degraded_not_verified():
    scope = impact_scope.scope_gitnexus_from_artifact(_artifact("degraded", ["MEDIUM"]))
    assert scope["verified"] is False
    assert scope["impact_summary"]["risk"] == "MEDIUM"


def test_derivation_no_seeds_unset_risk():
    scope = impact_scope.scope_gitnexus_from_artifact(_artifact("not_applicable", []))
    assert "risk" not in scope["impact_summary"]


def test_high_impact_floors_recommend_to_critical():
    scope = {"gitnexus": impact_scope.scope_gitnexus_from_artifact(_artifact("verified", ["HIGH"]))}
    result = recommend.recommend_tier("rename a helper function", scope=scope, selected_tier="auto")
    assert result["recommended_tier"] == "critical"


def test_degraded_cross_service_keeps_critical_warning():
    scope = {"dependencies": [{"source_service": "a", "target_service": "b"}],
             "gitnexus": impact_scope.scope_gitnexus_from_artifact(_artifact("degraded", ["MEDIUM"]))}
    result = recommend.recommend_tier("rename a helper function", scope=scope, selected_tier="auto")
    assert result["recommended_tier"] == "critical"
    assert any("not verified" in r for r in result["reasons"])
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Create `adapters/tier/impact_scope.py`**:

```python
"""Pure reduction from an impact-assessment artifact to the scope.gitnexus shape
recommend_tier consumes (design F6). The artifact is the source of truth; the
control plane derives scope.gitnexus from it instead of workers maintaining a
second value. recommend.py stays pure and unchanged.
"""
from __future__ import annotations

from e2e_harness.adapters.evidence import impact as impact_ev


def scope_gitnexus_from_artifact(obj: dict) -> dict:
    """{"impact_summary": {...}, "verified": bool}. risk = max seed risk (unset when
    no seeds); verified iff artifact status == "verified"."""
    summary: dict = {}
    risk = impact_ev.max_seed_risk(obj)
    if risk is not None:
        summary["risk"] = risk
    return {"impact_summary": summary,
            "verified": (obj.get("status") == "verified")}
```

- [ ] **Step 4: Run, expect pass** — `python -m pytest tests/test_tier_recommend_impact.py -v`.
- [ ] **Step 5: Regression** — `python -m pytest tests/test_tier_recommend.py -v` (the pure recommender contract is unchanged).
- [ ] **Step 6: Commit** — `git add adapters/tier/impact_scope.py tests/test_tier_recommend_impact.py && git commit -m "feat(e2e-dev-harness): pure impact->scope.gitnexus tier derivation (Slice 5a)"`

## Slice 5b: `approve-impact-degradation` coordinator command

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/approve_impact_degradation.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py` (register command; add `--impact-mode` to `start`)
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py` (persist `impact.mode`)
- Test: `skills/e2e-dev-harness/tests/test_approve_impact_degradation.py`

### Task 5b.1: Coordinator approval command writes the trust anchor

- [ ] **Step 1: Write failing test** — `tests/test_approve_impact_degradation.py`:

```python
import json
from pathlib import Path
from types import SimpleNamespace
from e2e_harness.core import run_state
from e2e_harness.cli.commands import approve_impact_degradation as cmd


def test_records_run_state_approval(tmp_path):
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"; run_dir.mkdir(parents=True)
    state_path = run_dir / "run-state.json"
    st = run_state.new_run_state("r1", "f", "req", tier="critical", pipeline="critical")
    run_state.save(state_path, st)
    approval = run_dir / "gitnexus-degradation.md"
    approval.write_text("Approval: user-approved\nReason: GitNexus unavailable\n"
                        "Fallback Evidence: manual review\n", encoding="utf-8")

    args = SimpleNamespace(state=str(state_path), approval=str(approval), reason="env has no gitnexus")
    code, result = cmd.run(args)
    assert code == 0
    saved = run_state.load(state_path)
    block = saved["approvals"]["impact_degradation"]
    assert block["source"] == "user-approved"
    assert block["recorded_by"] == "coordinator"
    assert len(block["sha256"]) == 64


def test_rejects_missing_approval_markers(tmp_path):
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"; run_dir.mkdir(parents=True)
    state_path = run_dir / "run-state.json"
    run_state.save(state_path, run_state.new_run_state("r1", "f", "req"))
    approval = run_dir / "bad.md"; approval.write_text("nope", encoding="utf-8")
    args = SimpleNamespace(state=str(state_path), approval=str(approval), reason="x")
    code, result = cmd.run(args)
    assert code == 2 and "error" in result
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Create `cli/commands/approve_impact_degradation.py`**:

```python
"""approve-impact-degradation: coordinator records the degradation trust anchor.

Degraded impact evidence is trusted ONLY when state.approvals.impact_degradation
exists and its sha256 matches the artifact's approval hash (design: Degraded
Approval). A worker-authored markdown file is fallback evidence, not the anchor —
this command is the coordinator-owned write that the validator checks against.
"""
from __future__ import annotations

import re
from pathlib import Path

from e2e_harness.core import run_state
from e2e_harness.adapters.evidence import hashing

_REQUIRED = ("approval: user-approved",)


def run(args) -> tuple[int, dict]:
    approval = Path(args.approval)
    if not approval.is_file():
        return 2, {"error": f"approval file not found: {approval}"}
    text = approval.read_text(encoding="utf-8", errors="replace").lower()
    for marker in _REQUIRED:
        if marker not in text:
            return 2, {"error": f"approval missing required marker: {marker!r}"}
    if "reason:" not in text:
        return 2, {"error": "approval missing 'Reason:'"}
    if "fallback evidence:" not in text and "compensating evidence:" not in text:
        return 2, {"error": "approval missing 'Fallback Evidence:'"}

    sha = hashing.sha256_file(approval)

    def _record(state):
        state.setdefault("approvals", {})["impact_degradation"] = {
            "source": "user-approved",
            "approval_path": str(args.approval),
            "sha256": sha,
            "recorded_by": "coordinator",
            "reason": getattr(args, "reason", None) or "",
        }

    run_state.mutate(args.state, _record,
                     events_path=run_state.events_path_if_active(args.state))
    return 0, {"schema": "e2e-dev-harness.impact-degradation-approval.v1",
               "state": str(args.state), "sha256": sha, "recorded_by": "coordinator"}
```

- [ ] **Step 4: Edit `cli/main.py`** — register the command and add `--impact-mode` to `start`:
  - Import: add `approve_impact_degradation` to the `from e2e_harness.cli.commands import (...)` block.
  - `_COMMANDS`: add `"approve-impact-degradation": approve_impact_degradation.run,`.
  - In `build_parser`, after the `start` options block, add:
    ```python
    s.add_argument("--impact-mode", choices=["off", "auto", "strict"], default="off",
                   help="GitNexus impact assessment mode for this run (default off)")
    ```
  - Add a subparser:
    ```python
    ai = sub.add_parser("approve-impact-degradation")
    ai.add_argument("--state", required=True)
    ai.add_argument("--approval", required=True)
    ai.add_argument("--reason", default=None)
    ```

- [ ] **Step 5: Edit `cli/commands/start.py`** — persist the mode into run-state. After `st["tier_recommendation"] = tier_recommendation` (line 127), add:
    ```python
    st["impact"] = {"mode": getattr(args, "impact_mode", "off") or "off"}
    ```

- [ ] **Step 6: Run, expect pass** — `python -m pytest tests/test_approve_impact_degradation.py -v`.
- [ ] **Step 7: Full suite** — `python -m pytest tests/ -q`. (`start` default `--impact-mode off` keeps every existing start/e2e test byte-compatible in behavior; the added `impact` block is inert when off.)
- [ ] **Step 8: Commit** — `git add cli/commands/approve_impact_degradation.py cli/main.py cli/commands/start.py tests/test_approve_impact_degradation.py && git commit -m "feat(e2e-dev-harness): approve-impact-degradation command + start --impact-mode (Slice 5b)"`

### Task 5b.2: End-to-end strict-mode integration test

- [ ] **Step 1: Write an integration test** — `tests/test_impact_e2e.py`: start a run with `--impact-mode strict` and a request that names code surfaces, drive `next` with a fake provider (monkeypatch `impact_bridge`'s default provider or set `provider` via a seam) to return `blocked`, assert `next` reports CLARIFIED with IQ-* questions; then make it `verified`, submit a module_plan WITH `impact_refs`, assert PLANNED can pass; submit WITHOUT refs, assert `impact_refs` blocks. Use the real CLI command entrypoints (`start.run`, `next.run`, `submit.run`) the way `tests/test_cli_e2e.py` does.

> Read `tests/test_cli_e2e.py` first and mirror its run-driving harness exactly. Keep the provider injected (monkeypatch `e2e_harness.adapters.impact.gitnexus.GitNexusImpactProvider` to a fake) so the test never shells out to real GitNexus.

- [ ] **Step 2–4:** Run → fix → pass.
- [ ] **Step 5: Full suite** — `python -m pytest tests/ -q`.
- [ ] **Step 6: Commit** — `git commit -am "test(e2e-dev-harness): strict-mode impact gate end-to-end (Slice 5b)"`

---

## Final verification

- [ ] `python -m pytest tests/ -q` — all green (675 baseline + new tests).
- [ ] `git log --oneline` — one commit per task, messages reference slices.
- [ ] Sanity: a run started WITHOUT `--impact-mode` (or `off`) behaves byte-identically to pre-feature (no `impact-assessment.json`, no gate change).
- [ ] Update `skills/e2e-dev-harness/SKILL.md` if it documents lifecycle gates (add the impact gate + `--impact-mode` + `approve-impact-degradation`); commit separately as docs.

## Self-review notes (spec coverage)

- Artifact contract + validator → Slice 1. ✅ (status enum, verified rigor, blocked questions, degraded approval split.)
- Provider interface + GitNexus normalization, stale/unavailable/timeout/ambiguity → Slice 2. ✅
- Trigger policy (one helper) → Slice 3-pre + bridge idempotency on `contract_sha256` → Slice 3a. ✅
- Evaluation Point (forward edge + PLANNED re-entry via single loop-top injection) → Slice 3a Task 3a.2. ✅
- Status Ownership (`blocked` → CLARIFIED edge; PLANNED owns refs/approval/backstop) → bridge + `impact_gate` + tests. ✅
- Re-clarify merge of IQ-* → Slice 3b. ✅
- Dispatch transport-only injection by phase+status → Slice 3c. ✅
- PLANNED supplemental gate + F2 navigation consistency → Slice 3d. ✅
- module_plan optional `impact_refs`; requirement enforced in gate → Slice 4 (+3d). ✅
- Tier derivation F6 (max risk; verified iff status verified) → Slice 5a. ✅
- Degraded approval trust anchor command → Slice 5b. ✅
- Compatibility: `impact.mode` default off; validator not in STRUCTURED_KEYS; additive run-state — preserves 675 green tests. ✅

**Deviations from the design (documented):**
1. **`impact.mode` switch — default `auto` (ON).** Per user direction, GitNexus impact is on by default. An unverifiable assessment does not stall: the run blocks at `CLARIFIED` and `next` surfaces a degrade offer (`impact.degradation_available`), so the coordinator asks the user to resolve or approve degradation; a recorded approval converts the blocked assessment to an auditable `degraded` one. `--impact-mode off` opts a run out. The one existing test that drives an audited run to completion in an unindexed temp repo pins `off` (it tests an orthogonal gate chain); the impact on-path + degradation flow are covered by `test_impact_e2e.py`.
2. **Binding carries `seeds`** — added so `impact_gate.planned_missing` is purely in-memory for the refs check (design intent), rather than re-reading the artifact.
3. **Slice 5 ships only the pure derivation**, not a post-clarification re-tier command — no such call site exists today; inventing one is out of scope.
4. **pytest, not `unittest`** — the design's `python -m unittest discover` commands do not collect this project's plain-function tests.
