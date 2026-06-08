# U5 — DomainAdapter seam (M4 frontend) Implementation Plan (condensed)

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Steps use `- [ ]`. TDD throughout. Run before build: `npx gitnexus analyze` (index stale). All paths relative to repo root; harness pkg root is `skills/e2e-dev-harness-v2/`.

**Goal:** Add a config-producer `DomainAdapter` seam so the untouched core drives a frontend fixture repo to `VERIFIED`, backend as the default adapter (byte-identical parity).

**Architecture:** Adapter selected at `start`; emits scope + pipeline-spec overrides via U4's config layer; embeds a self-describing `domain` block in run-state (omitted for backend default). Core `lifecycle/engine/gates/dispatch/navigation/pipeline_validate/pipeline.py` get **zero** edits.

**Tech Stack:** Python 3, pytest, pyyaml. Spec: `docs/superpowers/specs/2026-06-08-harness-v2-u5-domain-adapter-design.md`.

**Test command (from pkg root):** `cd skills/e2e-dev-harness-v2 && python -m pytest tests/ -q`

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/harness_v2/adapters/domain/base.py` | `DomainAdapter` Protocol + `domain_block()` helper |
| `scripts/harness_v2/adapters/domain/registry.py` | `select(repo, explicit)` + `_REGISTRY`/default |
| `scripts/harness_v2/adapters/domain/backend.py` | backend adapter (overrides `{}`) |
| `scripts/harness_v2/adapters/domain/frontend.py` | frontend adapter |
| `scripts/harness_v2/adapters/domain/__init__.py` | re-export `select`, `DomainAdapter` |
| `scripts/harness_v2/adapters/scanner/frontend.py` | `scan_frontend(repo)->scanner-scope.v1` |
| `scripts/harness_v2/adapters/scanner/__init__.py` (mod) | re-export `scan_frontend` |
| `scripts/harness_v2/core/run_state.py` (mod) | additive `domain` kwarg, omitted when `None` |
| `scripts/harness_v2/pipeline.py` — **NO EDIT** | merge lives in start.py to keep core untouched |
| `scripts/harness_v2/cli/commands/start.py` (mod) | select adapter, merge overrides, embed domain |
| `scripts/harness_v2/cli/commands/dispatch.py` (mod) | read domain block → `extra_context` |
| `scripts/harness_v2/cli/main.py` (mod) | `--adapter`, `--scan` on `start` |
| `tests/test_domain_adapter.py` | detect/select/unknown |
| `tests/test_domain_backend_parity.py` | byte-identical parity |
| `tests/test_domain_overrides_merge.py` | override channel |
| `tests/test_domain_frontend_scan.py` | frontend scope |
| `tests/test_cli_frontend_e2e.py` | start→VERIFIED (simulated) |
| `tests/fixtures/frontend_app/` | package.json + src/App.tsx + App.test.tsx (data) |

> **Merge placement decision:** the spec lists `pipeline.py` as protected. So the spec-merge + embed-rule live in `start.py` (CLI), not `pipeline.py`. A pure helper `merge_overrides(spec, overrides)` goes in `adapters/domain/base.py` (new file, not core).

---

## Task 1: DomainAdapter Protocol + merge helper

**Files:** Create `scripts/harness_v2/adapters/domain/base.py`, `scripts/harness_v2/adapters/domain/__init__.py`; Test `tests/test_domain_overrides_merge.py`

- [ ] **Step 1: Failing test** (`tests/test_domain_overrides_merge.py`)
```python
from harness_v2.adapters.domain import base
from harness_v2 import pipeline
from harness_v2.core import pipeline_validate

def test_merge_applies_overrides_and_stays_valid():
    spec = pipeline.load_spec("standard")  # phases: CREATED..VERIFIED (bare strings)
    overrides = {"RED": {"produces": ["failing_tests"], "exit_gate": ["failing_tests"],
                         "worker_skill": "e2e-harness-tdd-red"}}
    merged = base.merge_overrides(spec, overrides)
    red = next(e for e in merged["phases"] if (e if isinstance(e, str) else e["phase"]) == "RED")
    assert isinstance(red, dict) and red["worker_skill"] == "e2e-harness-tdd-red"
    ok, errors = pipeline_validate.validate_spec(merged)
    assert ok, errors

def test_merge_empty_overrides_is_identity():
    spec = pipeline.load_spec("standard")
    assert base.merge_overrides(spec, {}) == spec
```

- [ ] **Step 2: Run** `python -m pytest tests/test_domain_overrides_merge.py -q` → FAIL (no module).

- [ ] **Step 3: Implement** `base.py`
```python
"""DomainAdapter Protocol + pure spec-merge helper (domain layer, not core)."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Protocol, runtime_checkable

_OVERRIDE_FIELDS = ("worker_role", "worker_skill", "produces", "exit_gate")


@runtime_checkable
class DomainAdapter(Protocol):
    name: str
    test_runner: str
    review_profile: str
    def detect(self, repo: Path) -> bool: ...
    def scan(self, repo: Path, request: str) -> dict | None: ...
    def pipeline_overrides(self) -> dict: ...


def merge_overrides(spec: dict, overrides: dict) -> dict:
    """Return a copy of `spec` with per-phase `overrides` applied. Bare-string
    phase entries are promoted to `{phase, ...}` mappings. Identity when empty."""
    if not overrides:
        return spec
    out = copy.deepcopy(spec)
    new_phases = []
    for entry in out["phases"]:
        name = entry if isinstance(entry, str) else entry["phase"]
        ov = overrides.get(name)
        if not ov:
            new_phases.append(entry); continue
        merged = {"phase": name} if isinstance(entry, str) else dict(entry)
        for k in _OVERRIDE_FIELDS:
            if k in ov:
                merged[k] = ov[k]
        new_phases.append(merged)
    out["phases"] = new_phases
    return out


def domain_block(adapter: "DomainAdapter") -> dict:
    return {"name": adapter.name, "test_runner": adapter.test_runner,
            "review_profile": adapter.review_profile}
```
`__init__.py`:
```python
from harness_v2.adapters.domain.base import DomainAdapter, merge_overrides, domain_block
from harness_v2.adapters.domain.registry import select
__all__ = ["DomainAdapter", "merge_overrides", "domain_block", "select"]
```
> NOTE: `__init__` imports `registry` (Task 2) — create Task 2 file before running Task 1 Step 4, or temporarily import only from `base` until Task 2 lands. Recommended: do Task 1 + Task 2 then run both.

- [ ] **Step 4: Run** the merge test → PASS. **Commit:** `feat(harness-v2): U5 DomainAdapter protocol + spec-merge helper`

---

## Task 2: Registry + backend & frontend adapters

**Files:** Create `registry.py`, `backend.py`, `frontend.py`, `adapters/scanner/frontend.py`; modify `adapters/scanner/__init__.py`; Test `tests/test_domain_adapter.py`, `tests/test_domain_frontend_scan.py`

- [ ] **Step 1: Failing tests** (`tests/test_domain_adapter.py`)
```python
from pathlib import Path
import pytest
from harness_v2.adapters.domain import select
from harness_v2.adapters.domain import backend, frontend

def _mk(p: Path, name: str, body: str = "{}"):
    f = p / name; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(body); return f

def test_detect_backend_by_pyproject(tmp_path):
    _mk(tmp_path, "pyproject.toml", "[tool]\n")
    assert select(tmp_path).name == "backend"

def test_detect_frontend_by_package_json_with_react(tmp_path):
    _mk(tmp_path, "package.json", '{"dependencies":{"react":"^18"}}')
    assert select(tmp_path).name == "frontend"

def test_empty_repo_falls_back_to_backend_default(tmp_path):
    assert select(tmp_path).name == "backend"

def test_explicit_overrides_marker(tmp_path):
    _mk(tmp_path, "package.json", '{"dependencies":{"react":"^18"}}')
    assert select(tmp_path, explicit="backend").name == "backend"

def test_unknown_adapter_raises(tmp_path):
    with pytest.raises(KeyError):
        select(tmp_path, explicit="mobile")

def test_fullstack_frontend_wins_by_order(tmp_path):
    _mk(tmp_path, "pyproject.toml", ""); _mk(tmp_path, "package.json", '{"dependencies":{"vue":"^3"}}')
    assert select(tmp_path).name == "frontend"
```
(`tests/test_domain_frontend_scan.py`)
```python
from harness_v2.adapters.scanner import scan_frontend

def test_frontend_scan_lists_components(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text("export default function App(){return null}")
    scope = scan_frontend(tmp_path)
    assert scope["schema"].startswith("scanner-scope")
    assert any("App" in c for c in scope["components"])
    assert scope["dependencies"] == []
```

- [ ] **Step 2: Run** both → FAIL.

- [ ] **Step 3: Implement.** `adapters/scanner/frontend.py`:
```python
"""Thin frontend scope discovery (heuristic file-walk; no framework AST)."""
from __future__ import annotations
from pathlib import Path

_EXT = (".tsx", ".jsx", ".vue", ".svelte")

def scan_frontend(repo) -> dict:
    repo = Path(repo); src = repo / "src"
    comps = []
    if src.is_dir():
        for f in sorted(src.rglob("*")):
            if f.suffix in _EXT and f.is_file():
                comps.append(str(f.relative_to(repo)))
    return {"schema": "scanner-scope.v1", "services": comps[:1], "components": comps, "dependencies": []}
```
Append to `adapters/scanner/__init__.py`:
```python
from .frontend import scan_frontend  # noqa: E402
__all__ = ["discover_scope", "discover_scope_java_spring", "scan_frontend"]
```
`adapters/domain/backend.py`:
```python
from __future__ import annotations
from pathlib import Path
from harness_v2.adapters import scanner

_MARKERS = ("pom.xml", "build.gradle", "build.gradle.kts", "pyproject.toml", "setup.py", "go.mod")
_JAVA = ("pom.xml", "build.gradle", "build.gradle.kts")

class BackendAdapter:
    name = "backend"
    review_profile = "backend-default"
    def detect(self, repo: Path) -> bool:
        return any((Path(repo) / m).exists() for m in _MARKERS)
    @property
    def test_runner(self) -> str:
        return "maven" if any((Path(_REPO[0]) / m).exists() for m in _JAVA) else "pytest" if _REPO[0] else "pytest"
    def scan(self, repo: Path, request: str) -> dict | None:
        repo = Path(repo)
        try:
            if any((repo / m).exists() for m in _JAVA):
                return scanner.discover_scope_java_spring(str(repo))
            return scanner.discover_scope(str(repo))
        except Exception:
            return None
    def pipeline_overrides(self) -> dict:
        return {}
```
> SIMPLIFY during build: `test_runner` as a marker-derived property needs the repo. Cleaner: make adapters carry the repo. Recommended concrete shape — construct adapters with the repo in `select`:
```python
# backend.py (preferred final form)
class BackendAdapter:
    name = "backend"; review_profile = "backend-default"
    def __init__(self, repo: Path | None = None): self.repo = Path(repo) if repo else None
    @classmethod
    def detect(cls, repo: Path) -> bool: return any((Path(repo)/m).exists() for m in _MARKERS)
    @property
    def test_runner(self) -> str:
        return "maven" if self.repo and any((self.repo/m).exists() for m in _JAVA) else "pytest"
    def scan(self, repo, request): ...  # as above
    def pipeline_overrides(self): return {}
```
`adapters/domain/frontend.py`:
```python
from __future__ import annotations
import json
from pathlib import Path
from harness_v2.adapters import scanner

_FW = ("react", "vue", "svelte", "@angular/core")

class FrontendAdapter:
    name = "frontend"; test_runner = "vitest"; review_profile = "frontend-default"
    def __init__(self, repo: Path | None = None): self.repo = Path(repo) if repo else None
    @classmethod
    def detect(cls, repo: Path) -> bool:
        repo = Path(repo); pkg = repo / "package.json"
        if not pkg.exists(): return False
        if (repo / "vite.config.ts").exists() or (repo / "vite.config.js").exists() \
           or (repo / "vitest.config.ts").exists() or (repo / "vitest.config.js").exists():
            return True
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except Exception:
            return False
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        return any(fw in deps for fw in _FW)
    def scan(self, repo, request): return scanner.scan_frontend(repo)
    def pipeline_overrides(self): return {}
```
`adapters/domain/registry.py`:
```python
from __future__ import annotations
from pathlib import Path
from harness_v2.adapters.domain.frontend import FrontendAdapter
from harness_v2.adapters.domain.backend import BackendAdapter

_ORDER = [FrontendAdapter, BackendAdapter]   # frontend first (more specific)
_BY_NAME = {c.name: c for c in _ORDER}
_DEFAULT = BackendAdapter

def select(repo, explicit: str | None = None):
    repo = Path(repo)
    if explicit:
        if explicit not in _BY_NAME:
            raise KeyError(f"unknown adapter: {explicit}")
        return _BY_NAME[explicit](repo)
    for cls in _ORDER:
        if cls.detect(repo):
            return cls(repo)
    return _DEFAULT(repo)
```
> Adjust Task 1 `__init__.py`: `merge_overrides`/`domain_block` from `base`, `select` from `registry`. `domain_block` reads `adapter.name/.test_runner/.review_profile` — all present.

- [ ] **Step 4: Run** Task 1 + Task 2 tests → PASS. **Commit:** `feat(harness-v2): U5 domain registry + backend/frontend adapters + frontend scanner`

---

## Task 3: run_state additive `domain` (omitted when None)

**Files:** Modify `core/run_state.py`; Test add to `tests/test_run_state.py`

- [ ] **Step 1: Failing test** (append to `tests/test_run_state.py`)
```python
def test_domain_block_embedded_when_supplied():
    st = run_state.new_run_state("r", "f", "q",
        domain={"name": "frontend", "test_runner": "vitest", "review_profile": "frontend-default"})
    assert st["domain"]["name"] == "frontend"

def test_domain_absent_by_default_byte_identical():
    st = run_state.new_run_state("r", "f", "q")
    assert "domain" not in st   # parity: backend default adds no key
```

- [ ] **Step 2: Run** → FAIL (unexpected kwarg).

- [ ] **Step 3: Implement** — add param to `new_run_state` signature `..., domain: dict | None = None, now=None)` and after the `pipeline_spec` block:
```python
    if domain is not None:
        state["domain"] = domain
```

- [ ] **Step 4: Run** `tests/test_run_state.py` → PASS (existing tests untouched). **Commit:** `feat(harness-v2): U5 run_state additive domain block`

---

## Task 4: start.py wiring (select + merge + embed) & main.py flags

**Files:** Modify `cli/commands/start.py`, `cli/main.py`

- [ ] **Step 1:** Add flags in `main.py` `start` subparser:
```python
    s.add_argument("--adapter", default=None, help="force domain adapter (backend|frontend)")
    s.add_argument("--scan", action="store_true", help="run adapter scan to raise tier floor")
```
- [ ] **Step 2:** Rewrite `start.run` body (after `repo`/`run_id`):
```python
    from harness_v2.adapters.domain import select, merge_overrides, domain_block
    adapter = select(repo, explicit=getattr(args, "adapter", None))   # KeyError -> main.py exit 2
    tier = args.tier; reasons: list[str] = []
    if tier == "auto":
        from harness_v2.adapters.tier import classify
        scope = adapter.scan(repo, args.request) if getattr(args, "scan", False) else None
        tier, reasons = classify.classify_tier(args.request, scope)
    pipeline_ref = getattr(args, "pipeline", None) or tier
    spec = pipeline.load_spec(pipeline_ref)
    merged = merge_overrides(spec, adapter.pipeline_overrides())
    ok, errors = pipeline_validate.validate_spec(merged)
    if not ok:
        return 2, {"error": "invalid pipeline", "pipeline": pipeline_ref, "errors": errors}
    custom = pipeline.is_path(pipeline_ref)
    non_default = custom or bool(adapter.pipeline_overrides()) or adapter.name != "backend"
    dom = domain_block(adapter) if adapter.name != "backend" else None
    rel = Path("docs/agent-runs") / run_id / "run-state.json"; path = repo / rel
    st = run_state.new_run_state(run_id, args.feature, args.request, tier=tier,
        pipeline=pipeline_ref, pipeline_spec=merged if non_default else None, domain=dom)
    run_state.save(path, st)
    return 0, {"schema": "e2e-dev-harness-v2.start.v1", "run_id": run_id,
               "run_state": str(path), "current_phase": "CREATED", "tier": tier,
               "pipeline": pipeline_ref, "tier_reasons": reasons, "domain": adapter.name}
```
- [ ] **Step 3: Run** full suite → existing `test_cli_e2e.py`, `test_cli_custom_pipeline_e2e.py` PASS (backend parity: `domain`/`pipeline_spec` absent for backend). Confirm `start.v1` now has `"domain":"backend"` in output only (not state). **Commit:** `feat(harness-v2): U5 start adapter selection + merge + domain embed`

---

## Task 5: dispatch reads domain block → extra_context

**Files:** Modify `cli/commands/dispatch.py`

- [ ] **Step 1:** In `dispatch.run`, before building packet:
```python
    extra = []
    dom = state.get("domain")
    if dom:
        extra = [f"domain:{dom['name']} test_runner:{dom['test_runner']} review_profile:{dom['review_profile']}"]
    packet = dispatch.worker_packet(phase, str(args.state), extra_context=extra)
```
- [ ] **Step 2: Run** `tests/test_cli_e2e.py::test_dispatch_returns_pointer_packet` → PASS (backend: no domain ⇒ `extra=[]` ⇒ unchanged `context_paths`). **Commit:** `feat(harness-v2): U5 dispatch surfaces domain metadata via extra_context`

---

## Task 6: backend parity + frontend fixture + frontend e2e

**Files:** Create `tests/test_domain_backend_parity.py`, `tests/fixtures/frontend_app/*`, `tests/test_cli_frontend_e2e.py`

- [ ] **Step 1: Parity test** (`tests/test_domain_backend_parity.py`)
```python
from pathlib import Path
from harness_v2.adapters.domain import select, merge_overrides
from harness_v2 import pipeline

def test_backend_overrides_empty_and_spec_identity():
    a = select(Path("."), explicit="backend")
    assert a.pipeline_overrides() == {}
    for tier in ("minimal", "standard", "critical", "audited"):
        spec = pipeline.load_spec(tier)
        assert merge_overrides(spec, a.pipeline_overrides()) == spec
```
- [ ] **Step 2: Fixture.** Create:
  - `tests/fixtures/frontend_app/package.json` → `{"name":"fx","dependencies":{"react":"^18"}}`
  - `tests/fixtures/frontend_app/src/App.tsx` → `export default function App(){return null}`
  - `tests/fixtures/frontend_app/src/App.test.tsx` → `import App from "./App"; it("renders", ()=>{})` (data only)
- [ ] **Step 3: Frontend e2e** (`tests/test_cli_frontend_e2e.py`) — mirror `test_cli_e2e.py`, but copy the fixture into `tmp_path` first and assert domain:
```python
import json, shutil, subprocess, sys
from pathlib import Path
ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness_v2.py"
FIX = Path(__file__).resolve().parent / "fixtures" / "frontend_app"

def _run(*a, cwd):
    p = subprocess.run([sys.executable, str(ENTRY), *a], cwd=cwd, capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout or "{}")

def _artifact(repo: Path, phase: str, key: str) -> str:
    from harness_v2.adapters.evidence import command_evidence as ce
    base = repo / "docs" / "agent-runs" / "art"; base.mkdir(parents=True, exist_ok=True)
    if key in ("failing_tests", "passing_tests"):
        ev = ce.record_command(repo, f'"{sys.executable}" -c "import sys;sys.exit({1 if key=="failing_tests" else 0})"')
        f = base / f"{phase}-{key}.json"; f.write_text(json.dumps(ev))
    else:
        f = base / f"{phase}-{key}.md"; f.write_text("real\n")
    return str(f.relative_to(repo))

def test_frontend_repo_drives_to_verified(tmp_path):
    for item in FIX.iterdir():
        dst = tmp_path / item.name
        shutil.copytree(item, dst) if item.is_dir() else shutil.copy(item, dst)
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo", "--request", "do x", cwd=tmp_path)
    assert code == 0 and res["domain"] == "frontend"
    state = res["run_state"]; steps = 0; nres = {"complete": False}
    while steps < 50:
        steps += 1
        _, nres = _run("next", "--state", state, "--repo", str(tmp_path), cwd=tmp_path)
        if nres["complete"]: break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            _run("submit", "--state", state, "--phase", phase, "--key", key,
                 "--path", _artifact(tmp_path, phase, key), "--repo", str(tmp_path), cwd=tmp_path)
    assert nres["complete"] is True
    assert nres["navigation_map"]["you_are_here"] == "VERIFIED"
    assert steps <= 6
```
> Frontend default tier is `minimal` (text-only, no `--scan`), so spine = CREATED→CLARIFIED→RED→IMPLEMENTED→VERIFIED; ≤6 steps holds. Verify run-state has `domain.name == "frontend"`.
- [ ] **Step 4: Run** full suite `python -m pytest tests/ -q` → all green. **Commit:** `feat(harness-v2): U5 backend parity + frontend fixture + frontend e2e`

---

## Task 7: roadmap update + final verification

- [ ] **Step 1:** Mark U5 ✅ in `docs/superpowers/plans/2026-06-07-harness-v2-remaining-work-roadmap.md` "Done so far" + the U5 row.
- [ ] **Step 2:** `npx gitnexus analyze` then `gitnexus_detect_changes()` — confirm only U5 symbols/flows affected.
- [ ] **Step 3:** Full suite green; **Commit:** `docs(harness-v2): mark U5 (M4 DomainAdapter) done in roadmap`.

---

## Self-Review notes
- **Spec coverage:** §5.1 Protocol→T1; §5.2 registry→T2; §5.3 backend (`{}` + marker detect)→T2/T6; §5.4 frontend + override-channel test→T1(merge)/T2; §5.5 frontend scanner→T2; §6 data flow (select/merge/embed/dispatch)→T4/T5; §7 errors (unknown adapter via `KeyError`→main exit 2; fullstack order; scan-safe)→T2; §8 all 5 test files→T1/T2/T3/T6; §10 byte-identical parity→T3/T6.
- **Open build-time simplification:** adapters take `repo` in `__init__` (final form shown) so `test_runner` resolves without globals — use that form, ignore the first backend sketch.
- **Risk:** subagent dispatch broken → run via `executing-plans` inline; review with `/code-review` after.
