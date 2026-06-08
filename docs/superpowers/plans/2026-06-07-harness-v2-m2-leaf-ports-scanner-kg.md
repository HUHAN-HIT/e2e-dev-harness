# Harness v2 — M2 Leaf Ports: scanner + kg-evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the two clean, test-backed leaves deferred from M2 — `kg-evidence` (`kg_refresh`) and `scanner` (`cross_service_dependency_scan` + scanners facade) — into `skills/e2e-dev-harness-v2/` behind narrow interfaces, bringing their legacy tests green, with zero logic edits (design §5 "作为库 port,逻辑不动,只包一层窄接口").

**Architecture:** Each leaf is vendored verbatim into a self-contained flat module dir `harness_v2/adapters/<leaf>/_legacy/` (keeping the legacy flat imports working unchanged), exposed to v2 callers through a thin `__init__.py` shim that inserts that dir on `sys.path` once and re-exports the public functions. The legacy tests are copied verbatim into the v2 test dir, changing **only** the path constant that points at the vendored modules. The two leaves are independent and separately committable — kg lands first (small, clean), scanner second (heavier: 1055L scan module + 291L plugin_registry + 674L test).

**Tech Stack:** Python 3.13, pytest + stdlib `unittest`, existing v2 `tests/conftest.py` sys.path convention.

---

## Baseline

Before starting, confirm the current suite is green and note the leaf sources.

- [ ] **Step 0: Baseline green**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: `63 passed`.

Leaf sources (legacy, do **not** modify these — M5 owns them):
- kg: `skills/e2e-dev-harness/scripts/kg_refresh.py` (309L), shared `skills/e2e-dev-harness/scripts/common.py` (93L); test `tests/test_kg_refresh.py` (110L).
- scanner: `skills/e2e-dev-harness/scripts/cross_service_dependency_scan.py` (1055L), `skills/e2e-dev-harness/scripts/plugin_registry.py` (291L), `skills/e2e-dev-harness/scripts/e2e_harness/adapters/scanners/{__init__,generic,java_spring}.py` (19/23L + facade), shared `common.py`; tests `tests/test_scanner.py` (674L) + `tests/test_scanner_ast.py` (177L, auto-skips without `tree_sitter`).

Key facts that make this a faithful copy (verified during scoping):
- Legacy tests resolve modules by **flat name** (`import kg_refresh`, `import cross_service_dependency_scan`) after `sys.path.insert(0, SCRIPTS)`.
- Neither scanner nor kg test imports the legacy CLI `e2e_dev_harness` — **no CLI coupling** (this is what made `memory_capture` hard; these two are clean).
- `plugin_registry.py` imports stdlib only (`importlib, inspect, sys, pathlib`) — no `from common`.
- `kg_refresh.py` needs `from common import DEFAULT_SUBPROCESS_TIMEOUT_SECONDS, SKIP_DIRS, parse_modules, posix, split_command`.
- `cross_service_dependency_scan.py` needs `from common import DEFAULT_SUBPROCESS_TIMEOUT_SECONDS, SKIP_DIRS, posix` and `import plugin_registry`.
- `scanners/java_spring.py` does `import cross_service_dependency_scan`; `scanners/generic.py` is standalone.

**Vendoring rule (applies to every copy step):** copy the file **byte-for-byte**, no edits to the body. Flat imports keep working because the vendored dir goes on `sys.path` via the shim and the ported test. `common.py` is vendored per-leaf (small, keeps each leaf independently shippable).

---

## GROUP A — kg-evidence (land first; small & clean)

### Task A1: Vendor the kg leaf verbatim

**Files:**
- Create dir: `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/kg/_legacy/`
- Create (copy verbatim): `.../adapters/kg/_legacy/common.py` ← `skills/e2e-dev-harness/scripts/common.py`
- Create (copy verbatim): `.../adapters/kg/_legacy/kg_refresh.py` ← `skills/e2e-dev-harness/scripts/kg_refresh.py`

- [ ] **Step 1: Copy the two legacy modules verbatim (no body edits)**

```bash
cd "C:/Users/14907/Documents/Codex/2026-05-23/skill-skill-superpowers-skill-tdd-graphify"
mkdir -p skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/kg/_legacy
cp skills/e2e-dev-harness/scripts/common.py     skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/kg/_legacy/common.py
cp skills/e2e-dev-harness/scripts/kg_refresh.py skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/kg/_legacy/kg_refresh.py
```

- [ ] **Step 2: Verify the copies are byte-identical**

Run:
```bash
diff skills/e2e-dev-harness/scripts/common.py     skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/kg/_legacy/common.py
diff skills/e2e-dev-harness/scripts/kg_refresh.py skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/kg/_legacy/kg_refresh.py
```
Expected: no output from either diff (identical).

### Task A2: Narrow interface shim (`adapters/kg/__init__.py`)

**Files:**
- Create: `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/kg/__init__.py`

- [ ] **Step 1: Write the shim that exposes the leaf's public surface**

```python
"""Narrow kg-evidence interface (ported from legacy kg_refresh; logic unchanged).

The legacy module imports its sibling `common` by flat name, so we put the
vendored `_legacy/` dir on sys.path once, then re-export the public surface.
GitNexus / git are invoked via subprocess inside `detect`/`run_command`; callers
without those tools get the same `availability`-gated behavior as legacy.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LEGACY = Path(__file__).resolve().parent / "_legacy"
if str(_LEGACY) not in sys.path:
    sys.path.insert(0, str(_LEGACY))

import kg_refresh  # noqa: E402

detect = kg_refresh.detect
detect_gitnexus_index = kg_refresh.detect_gitnexus_index
choose_tools = kg_refresh.choose_tools
suggested_commands = kg_refresh.suggested_commands
run_command = kg_refresh.run_command

__all__ = [
    "detect",
    "detect_gitnexus_index",
    "choose_tools",
    "suggested_commands",
    "run_command",
]
```

- [ ] **Step 2: Smoke-test the shim imports and re-exports**

Run:
```bash
cd skills/e2e-dev-harness-v2
python -c "from harness_v2.adapters.kg import detect, choose_tools, suggested_commands; print('ok', detect.__name__, choose_tools.__name__)"
```
Expected: `ok detect choose_tools`

### Task A3: Port `test_kg_refresh.py` verbatim (only the path constant changes)

**Files:**
- Create: `skills/e2e-dev-harness-v2/tests/test_kg_refresh.py` (copy of `tests/test_kg_refresh.py`)

- [ ] **Step 1: Copy the legacy test, then change only its path constant**

Copy `tests/test_kg_refresh.py` to `skills/e2e-dev-harness-v2/tests/test_kg_refresh.py` byte-for-byte, then replace lines 16–19. The legacy header is:

```python
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
```

Replace those four lines with (point at the vendored leaf; `parents[1]` is the v2 skill root):

```python
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "harness_v2" / "adapters" / "kg" / "_legacy"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
```

Everything else in the file (the `import kg_refresh` line, all test bodies, all mocks) stays **unchanged**.

- [ ] **Step 2: Run the ported kg test**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_kg_refresh.py -v`
Expected: same pass/skip outcome as the legacy run — all tests PASS (they mock `subprocess`/git, so no external tool is needed). If any test errors on import, the path constant in Step 1 is wrong; fix it.

- [ ] **Step 3: Run the full v2 suite (no regressions)**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: previous count + the kg tests, all green.

- [ ] **Step 4: Commit GROUP A**

```bash
git add skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/kg/ skills/e2e-dev-harness-v2/tests/test_kg_refresh.py
git commit -m "feat(harness-v2): port kg-evidence leaf (kg_refresh) behind narrow adapter + its test"
```

---

## GROUP B — scanner (heavier; lands second, independently)

Scanner drags three modules + the scanners facade. Same vendoring rule: verbatim copies, flat imports preserved, one shim, test path constants changed.

### Task B1: Vendor the scanner leaf verbatim

**Files (all copies, no body edits):**
- Create dir: `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/scanner/_legacy/`
- `.../scanner/_legacy/common.py` ← `skills/e2e-dev-harness/scripts/common.py`
- `.../scanner/_legacy/plugin_registry.py` ← `skills/e2e-dev-harness/scripts/plugin_registry.py`
- `.../scanner/_legacy/cross_service_dependency_scan.py` ← `skills/e2e-dev-harness/scripts/cross_service_dependency_scan.py`
- `.../scanner/_legacy/scanners/__init__.py` ← `.../e2e_harness/adapters/scanners/__init__.py`
- `.../scanner/_legacy/scanners/generic.py` ← `.../e2e_harness/adapters/scanners/generic.py`
- `.../scanner/_legacy/scanners/java_spring.py` ← `.../e2e_harness/adapters/scanners/java_spring.py`

- [ ] **Step 1: Copy all scanner modules verbatim**

```bash
cd "C:/Users/14907/Documents/Codex/2026-05-23/skill-skill-superpowers-skill-tdd-graphify"
DST=skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/scanner/_legacy
SRC=skills/e2e-dev-harness/scripts
mkdir -p "$DST/scanners"
cp "$SRC/common.py"                        "$DST/common.py"
cp "$SRC/plugin_registry.py"               "$DST/plugin_registry.py"
cp "$SRC/cross_service_dependency_scan.py" "$DST/cross_service_dependency_scan.py"
cp "$SRC/e2e_harness/adapters/scanners/__init__.py"    "$DST/scanners/__init__.py"
cp "$SRC/e2e_harness/adapters/scanners/generic.py"     "$DST/scanners/generic.py"
cp "$SRC/e2e_harness/adapters/scanners/java_spring.py" "$DST/scanners/java_spring.py"
```

- [ ] **Step 2: Verify byte-identical copies**

Run:
```bash
SRC=skills/e2e-dev-harness/scripts
DST=skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/scanner/_legacy
for f in common.py plugin_registry.py cross_service_dependency_scan.py; do diff "$SRC/$f" "$DST/$f"; done
for f in __init__.py generic.py java_spring.py; do diff "$SRC/e2e_harness/adapters/scanners/$f" "$DST/scanners/$f"; done
```
Expected: no output (all identical).

### Task B2: Narrow interface shim (`adapters/scanner/__init__.py`)

**Files:**
- Create: `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/scanner/__init__.py`

- [ ] **Step 1: Write the shim**

The scanners facade (`scanners/__init__.py`) selects `generic` vs `java_spring`; both expose `discover_scope(repo, request)`. We put `_legacy/` on sys.path (so `import cross_service_dependency_scan`, `from common import …` resolve) and `_legacy/scanners` is reachable as the package `scanners`.

```python
"""Narrow scanner interface (ported from legacy scanners facade; logic unchanged).

Exposes `discover_scope(repo, request)` (generic contract) and the java_spring
AST scope discovery. The vendored `_legacy/` dir is placed on sys.path so the
legacy flat imports (`import cross_service_dependency_scan`, `from common import …`)
resolve exactly as they did in the legacy skill.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LEGACY = Path(__file__).resolve().parent / "_legacy"
if str(_LEGACY) not in sys.path:
    sys.path.insert(0, str(_LEGACY))

from scanners import generic as _generic  # noqa: E402
from scanners import java_spring as _java_spring  # noqa: E402

discover_scope = _generic.discover_scope
discover_scope_java_spring = _java_spring.discover_scope

__all__ = ["discover_scope", "discover_scope_java_spring"]
```

- [ ] **Step 2: Smoke-test the shim**

Run:
```bash
cd skills/e2e-dev-harness-v2
python -c "from harness_v2.adapters.scanner import discover_scope; from pathlib import Path; print(discover_scope(Path('.'))['scanner'])"
```
Expected: `generic` (the generic stub returns `scanner: 'generic'`).

### Task B3: Port `test_scanner.py` verbatim (only the path constant changes)

**Files:**
- Create: `skills/e2e-dev-harness-v2/tests/test_scanner.py` (copy of `tests/test_scanner.py`)

- [ ] **Step 1: Copy the legacy test, then change only its path constant**

Copy `tests/test_scanner.py` to `skills/e2e-dev-harness-v2/tests/test_scanner.py` byte-for-byte. The legacy header (lines 16–19) is:

```python
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
```

Replace with:

```python
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "harness_v2" / "adapters" / "scanner" / "_legacy"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
```

All `import cross_service_dependency_scan` (and any `from common import …` / scanners imports) and every test body stays **unchanged** — they resolve against the vendored `_legacy/` dir.

- [ ] **Step 2: Run the ported scanner test**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_scanner.py -v`
Expected: same outcome as the legacy run. Tests that shell out to `mvn`/`git` are already mocked or guarded in the legacy file; any test that was skipped in legacy stays skipped. If a test errors on import resolution, the Step 1 path constant is wrong.

- [ ] **Step 3: Confirm parity with the legacy run (no behavior drift)**

Run the legacy test for the same module and compare the summary line:
```bash
python -m pytest tests/test_scanner.py -q          # legacy (repo-root tests/)
python -m pytest skills/e2e-dev-harness-v2/tests/test_scanner.py -q   # ported
```
Expected: identical passed/skipped counts. A divergence means the vendored copy or path constant differs from legacy — investigate before continuing.

### Task B4: Port `test_scanner_ast.py` (auto-skips without tree_sitter)

**Files:**
- Create: `skills/e2e-dev-harness-v2/tests/test_scanner_ast.py` (copy of `tests/test_scanner_ast.py`)

This test imports the module differently — `import cross_service_dependency_scan as scan_mod` at module top with **no** `sys.path` block — and skips the whole module unless `tree_sitter` + `tree_sitter_java` are installed (legacy lines 12–14).

- [ ] **Step 1: Copy the test and add the path bootstrap**

Copy `tests/test_scanner_ast.py` to `skills/e2e-dev-harness-v2/tests/test_scanner_ast.py` byte-for-byte. The legacy top (lines 1–10) is:

```python
"""AST-backed scanner tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import cross_service_dependency_scan as scan_mod
```

It relies on the legacy `conftest`/`sys.path` to resolve `cross_service_dependency_scan`. In v2, insert the vendored dir **before** that import. Replace the block above with:

```python
"""AST-backed scanner tests."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_LEAF = Path(__file__).resolve().parents[1] / "scripts" / "harness_v2" / "adapters" / "scanner" / "_legacy"
if str(_LEAF) not in sys.path:
    sys.path.insert(0, str(_LEAF))

import cross_service_dependency_scan as scan_mod  # noqa: E402
```

Leave the `tree_sitter` availability guard and all test bodies unchanged.

- [ ] **Step 2: Run the ported AST test**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_scanner_ast.py -v`
Expected: if `tree_sitter`/`tree_sitter_java` are absent (typical here), the module is **skipped** — `SKIPPED` is the correct pass outcome and matches legacy. If present, the AST tests run and PASS.

- [ ] **Step 3: Full v2 suite green**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: prior count + kg tests + scanner tests, all green (AST module may show as skipped).

- [ ] **Step 4: Commit GROUP B**

```bash
git add skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/scanner/ \
        skills/e2e-dev-harness-v2/tests/test_scanner.py \
        skills/e2e-dev-harness-v2/tests/test_scanner_ast.py
git commit -m "feat(harness-v2): port scanner leaf (cross_service scan + facade) behind narrow adapter + its tests"
```

---

## Final verification

- [ ] **Step 1: Full suite**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: all green (with AST module possibly skipped).

- [ ] **Step 2: Confirm change scope (CLAUDE.md requirement)**

Run: `git status --short`
Expected: only **new** files under `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/{kg,scanner}/` and `skills/e2e-dev-harness-v2/tests/test_{kg_refresh,scanner,scanner_ast}.py`. **No** edits to any legacy `skills/e2e-dev-harness/` file (M5 owns those). The pre-existing untracked dirs (`docs/agent-runs/nonexistent/`, `skills/e2e-dev-harness/scripts/.e2e/`, `snapshots/`) are test scratch and unrelated.

Run: `npx gitnexus detect-changes` (or `gitnexus_detect_changes` MCP) and confirm only the two new v2 adapter packages + their tests appear.

---

## Exit checklist (this plan done?)

- [ ] kg-evidence: `kg_refresh` vendored verbatim behind `harness_v2.adapters.kg`; `test_kg_refresh.py` ported and green.
- [ ] scanner: `cross_service_dependency_scan` + `plugin_registry` + scanners facade vendored verbatim behind `harness_v2.adapters.scanner`; `test_scanner.py` ported & green; `test_scanner_ast.py` ported (skips cleanly without tree_sitter).
- [ ] All vendored module bodies are **byte-identical** to legacy (verified by `diff`) — logic unchanged per design §5.
- [ ] Full v2 suite green; only new v2 files changed; no legacy edits.

## Deferred (NOT in this plan)

- **Wire scanner → tier escalation.** `adapters/tier/classify.py` notes multi-service/dependency-report escalation is "intentionally omitted until the scanner leaf is ported." Now unblocked, but it's a **behavior change to a v2 leaf** (classification escalates on scanner output), not a port — give it its own small TDD task/plan with golden-fixture coverage so the escalation thresholds are asserted, not silently introduced.
- **`dir_graph.py`** — separate dir-graph contract feature; `kg_refresh` does not import it and no kg test needs it. Not part of kg-evidence.
- **memory** and **runtime-adapter** leaves — per the earlier scope decision, planned separately (memory: test couples to legacy CLI; runtime: no legacy test + needs `spawn_worker` redesign via brainstorming).
