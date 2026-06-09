# e2e-dev-harness e2e-dev-harness �?M1 走骨�?Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在新�?`skills/e2e-dev-harness/` 建立一个能�?`start` 跑到 `VERIFIED` �?*保证终止**的最小多 agent 编排骨架(minimal tier)�?

**Architecture:** 单一事实�?`run-state.json` + 声明式阶段状态机(可终止主�?+ 单一 dispatch 状态枚�?+ 派生导航地图 + 指针�?worker packet(�?agent 自加�?Superpowers skill)。核心领域无�?后端为默�?adapter�?

**Tech Stack:** Python 3.13、stdlib only(`dataclasses`/`enum`/`json`/`argparse`/`pathlib`)、pytest�?

**Spec:** `docs/superpowers/specs/2026-06-07-e2e-dev-harness-redesign-design.md`(本计划仅实现 §14 �?M1)�?

---

## 文件结构 (M1)

```
skills/e2e-dev-harness/
  scripts/
    e2e_harness/
      __init__.py
      core/
        __init__.py
        run_state.py      # SSOT: schema + new/load/save
        lifecycle.py      # Phase 记录 + 阶段目录 + build_spine
        gates.py          # gate_passes (证据满足) + gate_closure_ok (I2)
        dispatch.py       # DispatchStatus 枚举 + worker_packet 构�?
        navigation.py     # �?spine+state 派生导航地图
        engine.py         # evaluate(): 推进主干 (I1 可终�? + submit_evidence()
      pipeline.py         # tier -> 活跃阶段�?(minimal)
      cli/
        __init__.py
        main.py           # argparse, 6 动词
        commands/
          __init__.py
          start.py
          next.py
          dispatch.py
          submit.py
          gate.py
          status.py
    e2e_dev_harness.py # 入口 shim -> e2e_harness.cli.main:main
  tests/
    conftest.py           # �?scripts/ 注入 sys.path
    test_run_state.py
    test_lifecycle_spine.py
    test_gate_closure.py      # I2
    test_gates.py
    test_dispatch.py
    test_navigation.py
    test_engine_termination.py # I1
    test_cli_e2e.py            # start -> VERIFIED 终止
    test_worker_skills_delegate.py
    test_skill_md.py
  SKILL.md
```

每个文件单一职责;`core/` 领域无关;`pipeline.py` �?tier→阶段映�?`cli/` 只做编排不含业务逻辑�?

---

## 关键数据契约 (跨任务一�?务必照抄签名)

**run-state.json**(schema `e2e-dev-harness.run-state.v1`):
```json
{
  "schema": "e2e-dev-harness.run-state.v1",
  "run_id": "20260607T120000Z-demo",
  "feature": "demo", "request": "do x", "tier": "minimal", "pipeline": "minimal",
  "current_phase": "CREATED",
  "phases": { "CLARIFIED": { "dispatch": "done", "evidence": { "clarification": "path.md" } } },
  "created_at": "20260607T120000Z", "updated_at": "20260607T120000Z"
}
```

**Phase**(`core/lifecycle.py`,frozen dataclass):
`Phase(name:str, worker_role:str, worker_skill:str, produces:tuple[str,...], exit_gate:tuple[str,...], next_phase:str|None)`

**DispatchStatus**(`core/dispatch.py`,str Enum): `PENDING="pending"`, `DISPATCHED="dispatched"`, `RUNNING="running"`, `DONE="done"`, `FAILED="failed"`�?

**minimal 活跃阶段顺序**: `("CREATED","CLARIFIED","RED","IMPLEMENTED","VERIFIED")`�?

---

### Task 1: 包脚手架 + 入口 shim

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/__init__.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/__init__.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/cli/__init__.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/__init__.py`
- Create: `skills/e2e-dev-harness/tests/conftest.py`
- Test: `skills/e2e-dev-harness/tests/test_run_state.py`(占位 import smoke)

- [ ] **Step 1: �?conftest 注入 sys.path**

`skills/e2e-dev-harness/tests/conftest.py`:
```python
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
```

- [ ] **Step 2: 写失败的 import smoke 测试**

`skills/e2e-dev-harness/tests/test_run_state.py`:
```python
def test_package_imports():
    import e2e_harness
    import e2e_harness.core
    assert e2e_harness is not None
```

- [ ] **Step 3: 运行,确认失败**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_run_state.py -v`
Expected: FAIL �?`ModuleNotFoundError: No module named 'e2e_harness'`

- [ ] **Step 4: 建空 `__init__.py`(4 �?**

四个文件内容均为单行注释:
```python
"""e2e-dev-harness e2e-dev-harness package."""
```
(`cli/commands/__init__.py` 同样)

- [ ] **Step 5: 运行,确认通过**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_run_state.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness skills/e2e-dev-harness/tests
git commit -m "feat(e2e-dev-harness): scaffold package + test path"
```

---

### Task 2: SSOT run-state

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/run_state.py`
- Test: `skills/e2e-dev-harness/tests/test_run_state.py`

- [ ] **Step 1: 追加失败测试**

�?`test_run_state.py` 追加:
```python
from e2e_harness.core import run_state


def test_new_run_state_shape():
    st = run_state.new_run_state("r1", "feat", "req")
    assert st["schema"] == "e2e-dev-harness.run-state.v1"
    assert st["current_phase"] == "CREATED"
    assert st["tier"] == "minimal"
    assert st["pipeline"] == "minimal"
    assert st["phases"] == {}


def test_save_then_load_roundtrip(tmp_path):
    st = run_state.new_run_state("r1", "feat", "req")
    p = tmp_path / "run-state.json"
    run_state.save(p, st)
    loaded = run_state.load(p)
    assert loaded["run_id"] == "r1"
    assert loaded["current_phase"] == "CREATED"


def test_save_refreshes_updated_at(tmp_path):
    st = run_state.new_run_state("r1", "feat", "req", now="20260607T000000Z")
    p = tmp_path / "run-state.json"
    run_state.save(p, st, now="20260607T010101Z")
    assert run_state.load(p)["updated_at"] == "20260607T010101Z"
```

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_run_state.py -v`
Expected: FAIL �?`ModuleNotFoundError`/`AttributeError`

- [ ] **Step 3: 实现 run_state.py**

```python
"""SSOT run-state: one JSON file, versioned schema."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "e2e-dev-harness.run-state.v1"


def _stamp(now: str | None = None) -> str:
    if now:
        return now
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def new_run_state(run_id: str, feature: str, request: str,
                  tier: str = "minimal", pipeline: str = "minimal",
                  now: str | None = None) -> dict:
    ts = _stamp(now)
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "feature": feature,
        "request": request,
        "tier": tier,
        "pipeline": pipeline,
        "current_phase": "CREATED",
        "phases": {},
        "created_at": ts,
        "updated_at": ts,
    }


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: str | Path, state: dict, now: str | None = None) -> None:
    state = dict(state)
    state["updated_at"] = _stamp(now)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
```

- [ ] **Step 4: 运行,确认通过**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_run_state.py -v`
Expected: PASS(4 �?

- [ ] **Step 5: 提交**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/run_state.py skills/e2e-dev-harness/tests/test_run_state.py
git commit -m "feat(e2e-dev-harness): SSOT run-state load/save"
```

---

### Task 3: 阶段目录 + build_spine + minimal pipeline

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/lifecycle.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/pipeline.py`
- Test: `skills/e2e-dev-harness/tests/test_lifecycle_spine.py`

- [ ] **Step 1: 写失败测�?*

`test_lifecycle_spine.py`:
```python
from e2e_harness.core import lifecycle
from e2e_harness import pipeline


def test_minimal_spine_order_and_links():
    spine = lifecycle.build_spine(pipeline.active_phase_names("minimal"))
    names = [p.name for p in spine]
    assert names == ["CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"]
    assert spine[0].next_phase == "CLARIFIED"
    assert spine[-1].next_phase is None  # VERIFIED 终�?


def test_created_phase_has_empty_gate():
    spine = lifecycle.build_spine(pipeline.active_phase_names("minimal"))
    assert spine[0].name == "CREATED"
    assert spine[0].exit_gate == ()


def test_clarified_phase_binds_worker_skill():
    spine = lifecycle.build_spine(pipeline.active_phase_names("minimal"))
    clar = next(p for p in spine if p.name == "CLARIFIED")
    assert clar.worker_skill == "e2e-harness-clarification"
    assert clar.exit_gate == ("clarification",)
    assert clar.produces == ("clarification",)
```

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_lifecycle_spine.py -v`
Expected: FAIL �?`ModuleNotFoundError`

- [ ] **Step 3: 实现 lifecycle.py**

```python
"""Declarative phase catalog + spine builder (领域无关)."""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Phase:
    name: str
    worker_role: str
    worker_skill: str
    produces: tuple[str, ...]
    exit_gate: tuple[str, ...]
    next_phase: str | None


# 全量阶段目录 (最长主�?;tier 从中选子�?(M2/§11)�?
_CATALOG: dict[str, Phase] = {
    "CREATED":     Phase("CREATED", "", "", (), (), None),
    "CLARIFIED":   Phase("CLARIFIED", "requirements-clarifier", "e2e-harness-clarification", ("clarification",), ("clarification",), None),
    "PLANNED":     Phase("PLANNED", "implementation-planner", "e2e-harness-planning", ("plan",), ("plan",), None),
    "RED":         Phase("RED", "tdd-red", "e2e-harness-tdd-red", ("failing_tests",), ("failing_tests",), None),
    "IMPLEMENTED": Phase("IMPLEMENTED", "code-developer", "e2e-harness-implementation", ("passing_tests",), ("passing_tests",), None),
    "REVIEWED":    Phase("REVIEWED", "semantic-reviewer", "e2e-harness-review", ("review",), ("review",), None),
    "VERIFIED":    Phase("VERIFIED", "coverage-reviewer", "e2e-harness-completion", ("verification",), ("verification",), None),
}


def catalog() -> dict[str, Phase]:
    return dict(_CATALOG)


def build_spine(phase_names: list[str]) -> list[Phase]:
    spine: list[Phase] = []
    for i, name in enumerate(phase_names):
        base = _CATALOG[name]
        nxt = phase_names[i + 1] if i + 1 < len(phase_names) else None
        spine.append(replace(base, next_phase=nxt))
    return spine
```

- [ ] **Step 4: 实现 pipeline.py**

```python
"""Pipeline config: tier -> active phase names (M1 内建 minimal)."""
from __future__ import annotations

_PIPELINES: dict[str, tuple[str, ...]] = {
    "minimal": ("CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"),
}


def active_phase_names(pipeline: str) -> list[str]:
    if pipeline not in _PIPELINES:
        raise KeyError(f"unknown pipeline: {pipeline}")
    return list(_PIPELINES[pipeline])
```

- [ ] **Step 5: 运行,确认通过**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_lifecycle_spine.py -v`
Expected: PASS(3 �?

- [ ] **Step 6: 提交**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/lifecycle.py skills/e2e-dev-harness/scripts/e2e_harness/pipeline.py skills/e2e-dev-harness/tests/test_lifecycle_spine.py
git commit -m "feat(e2e-dev-harness): phase catalog + minimal pipeline spine"
```

---

### Task 4: 门禁 + 闭包不变�?I2

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/gates.py`
- Test: `skills/e2e-dev-harness/tests/test_gates.py`, `skills/e2e-dev-harness/tests/test_gate_closure.py`

- [ ] **Step 1: 写失败测�?(gate_passes)**

`test_gates.py`:
```python
from e2e_harness.core import lifecycle, gates
from e2e_harness import pipeline


def _phase(name):
    return next(p for p in lifecycle.build_spine(pipeline.active_phase_names("minimal")) if p.name == name)


def test_gate_blocks_when_evidence_missing():
    ok, missing = gates.gate_passes(_phase("CLARIFIED"), {"evidence": {}})
    assert ok is False
    assert missing == ["clarification"]


def test_gate_passes_when_evidence_present():
    rec = {"evidence": {"clarification": "h.md"}}
    ok, missing = gates.gate_passes(_phase("CLARIFIED"), rec)
    assert ok is True
    assert missing == []


def test_empty_gate_always_passes():
    ok, missing = gates.gate_passes(_phase("CREATED"), {})
    assert ok is True
    assert missing == []
```

- [ ] **Step 2: 写失败测�?(I2 闭包)**

`test_gate_closure.py`:
```python
from dataclasses import replace

from e2e_harness.core import lifecycle, gates
from e2e_harness import pipeline


def test_minimal_pipeline_is_gate_closed():
    spine = lifecycle.build_spine(pipeline.active_phase_names("minimal"))
    ok, unmet = gates.gate_closure_ok(spine)
    assert ok is True, f"unsatisfiable evidence: {unmet}"


def test_closure_detects_unproduced_evidence():
    spine = lifecycle.build_spine(pipeline.active_phase_names("minimal"))
    broken = list(spine)
    broken[1] = replace(broken[1], exit_gate=("clarification", "ghost"))
    ok, unmet = gates.gate_closure_ok(broken)
    assert ok is False
    assert "ghost" in unmet
```

- [ ] **Step 3: 运行,确认失败**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_gates.py skills/e2e-dev-harness/tests/test_gate_closure.py -v`
Expected: FAIL �?`ModuleNotFoundError`

- [ ] **Step 4: 实现 gates.py**

```python
"""Declarative gate evaluation + closure invariant (I2)."""
from __future__ import annotations

from e2e_harness.core.lifecycle import Phase


def gate_passes(phase: Phase, phase_record: dict | None) -> tuple[bool, list[str]]:
    evidence = (phase_record or {}).get("evidence", {})
    missing = [k for k in phase.exit_gate if k not in evidence]
    return (not missing, missing)


def gate_closure_ok(spine: list[Phase]) -> tuple[bool, list[str]]:
    produced: set[str] = set()
    required: set[str] = set()
    for p in spine:
        produced.update(p.produces)
        required.update(p.exit_gate)
    unmet = sorted(required - produced)
    return (not unmet, unmet)
```

- [ ] **Step 5: 运行,确认通过**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_gates.py skills/e2e-dev-harness/tests/test_gate_closure.py -v`
Expected: PASS(5 �?

- [ ] **Step 6: 提交**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/gates.py skills/e2e-dev-harness/tests/test_gates.py skills/e2e-dev-harness/tests/test_gate_closure.py
git commit -m "feat(e2e-dev-harness): declarative gates + I2 closure invariant"
```

---

### Task 5: dispatch 状态枚�?+ worker packet (指针)

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/dispatch.py`
- Test: `skills/e2e-dev-harness/tests/test_dispatch.py`

- [ ] **Step 1: 写失败测�?*

`test_dispatch.py`:
```python
from e2e_harness.core import lifecycle, dispatch
from e2e_harness import pipeline


def test_status_values():
    assert dispatch.DispatchStatus.PENDING.value == "pending"
    assert dispatch.DispatchStatus.DONE.value == "done"
    assert {s.value for s in dispatch.DispatchStatus} == {
        "pending", "dispatched", "running", "done", "failed"}


def test_worker_packet_is_pointer_only():
    spine = lifecycle.build_spine(pipeline.active_phase_names("minimal"))
    clar = next(p for p in spine if p.name == "CLARIFIED")
    packet = dispatch.worker_packet(clar, run_state_path="docs/agent-runs/r1/run-state.json")
    assert packet["role"] == "requirements-clarifier"
    assert packet["skill"] == "e2e-harness-clarification"
    assert packet["expected_outputs"] == ["clarification"]
    assert "docs/agent-runs/r1/run-state.json" in packet["context_paths"]
    # 指针包不得内联指令文�?
    assert "instructions" not in packet
```

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_dispatch.py -v`
Expected: FAIL �?`ModuleNotFoundError`

- [ ] **Step 3: 实现 dispatch.py**

```python
"""Single dispatch status enum + pointer worker packet."""
from __future__ import annotations

from enum import Enum

from e2e_harness.core.lifecycle import Phase

PACKET_SCHEMA = "e2e-dev-harness.worker-packet.v1"


class DispatchStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def worker_packet(phase: Phase, run_state_path: str,
                  extra_context: list[str] | None = None) -> dict:
    return {
        "schema": PACKET_SCHEMA,
        "role": phase.worker_role,
        "skill": phase.worker_skill,
        "context_paths": [run_state_path, *(extra_context or [])],
        "expected_outputs": list(phase.produces),
    }
```

- [ ] **Step 4: 运行,确认通过**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_dispatch.py -v`
Expected: PASS(2 �?

- [ ] **Step 5: 提交**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/dispatch.py skills/e2e-dev-harness/tests/test_dispatch.py
git commit -m "feat(e2e-dev-harness): single dispatch enum + pointer worker packet"
```

---

### Task 6: 引擎 �?evaluate (I1 可终�? + submit_evidence

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/engine.py`
- Test: `skills/e2e-dev-harness/tests/test_engine_termination.py`

- [ ] **Step 1: 写失败测�?(I1 + submit)**

`test_engine_termination.py`:
```python
from e2e_harness.core import lifecycle, engine, run_state
from e2e_harness import pipeline


def _spine():
    return lifecycle.build_spine(pipeline.active_phase_names("minimal"))


def test_evaluate_auto_advances_created_then_blocks_on_clarified():
    st = run_state.new_run_state("r1", "f", "r")
    res = engine.evaluate(_spine(), st)
    assert st["current_phase"] == "CLARIFIED"   # CREATED 空门禁自动越�?
    assert res["complete"] is False
    assert res["blocked_phase"] == "CLARIFIED"
    assert res["next_action"]["skill"] == "e2e-harness-clarification"


def test_submit_then_evaluate_advances():
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(_spine(), st)                # -> CLARIFIED (blocked)
    engine.submit_evidence(st, "CLARIFIED", "clarification", "h1.md")
    engine.evaluate(_spine(), st)
    assert st["current_phase"] == "RED"


def test_full_run_terminates_at_verified_in_bounded_steps():
    spine = _spine()
    st = run_state.new_run_state("r1", "f", "r")
    steps = 0
    res = {"complete": False}
    while steps < 100:
        steps += 1
        res = engine.evaluate(spine, st)
        if res["complete"]:
            break
        ph = res["blocked_phase"]
        phase = next(p for p in spine if p.name == ph)
        for key in phase.produces:               # 模拟 worker 提交证据
            engine.submit_evidence(st, ph, key, f"{ph}-{key}.md")
    assert st["current_phase"] == "VERIFIED"
    assert res["complete"] is True
    assert steps <= len(spine) + 1               # I1: 有界终止


def test_evaluate_idempotent_after_complete():
    spine = _spine()
    st = run_state.new_run_state("r1", "f", "r")
    for _ in range(len(spine)):
        engine.evaluate(spine, st)
        phase = next(p for p in spine if p.name == st["current_phase"])
        for key in phase.produces:
            engine.submit_evidence(st, st["current_phase"], key, "e.md")
    res = engine.evaluate(spine, st)
    assert res["complete"] is True
    assert engine.evaluate(spine, st)["complete"] is True  # 再调用不回退/不报�?
```

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_engine_termination.py -v`
Expected: FAIL �?`ModuleNotFoundError`

- [ ] **Step 3: 实现 engine.py**

```python
"""Engine: terminating advance (I1) + evidence submission."""
from __future__ import annotations

from e2e_harness.core import gates, dispatch
from e2e_harness.core.lifecycle import Phase


def _phase_record(state: dict, name: str) -> dict:
    return state.setdefault("phases", {}).setdefault(name, {})


def submit_evidence(state: dict, phase_name: str, key: str, path: str) -> None:
    rec = _phase_record(state, phase_name)
    rec.setdefault("evidence", {})[key] = path
    rec["dispatch"] = dispatch.DispatchStatus.DONE.value


def _by_name(spine: list[Phase]) -> dict[str, Phase]:
    return {p.name: p for p in spine}


def evaluate(spine: list[Phase], state: dict) -> dict:
    """Advance current_phase past every gate that already passes; stop at first
    blocker or terminal. Guarantees termination: each pass advances >=0 phases
    along a finite spine and then blocks or completes."""
    by_name = _by_name(spine)
    name = state.get("current_phase", spine[0].name)
    while True:
        phase = by_name[name]
        rec = state.get("phases", {}).get(name, {})
        ok, missing = gates.gate_passes(phase, rec)
        if not ok:
            state["current_phase"] = name
            return {
                "complete": False,
                "blocked_phase": name,
                "missing_evidence": missing,
                "next_action": dispatch.worker_packet(phase, state.get("_run_state_path", "")),
            }
        if phase.next_phase is None:
            state["current_phase"] = name
            return {"complete": True, "blocked_phase": None, "missing_evidence": [], "next_action": {}}
        name = phase.next_phase
```

> 说明: `CREATED` 空门�?�?立即越过;终�?`VERIFIED` 门禁满足 �?`complete`。循环沿有限 spine 单向推进,必然�?≤len(spine) 次内返回�?

- [ ] **Step 4: 运行,确认通过**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_engine_termination.py -v`
Expected: PASS(4 �?

- [ ] **Step 5: 提交**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/engine.py skills/e2e-dev-harness/tests/test_engine_termination.py
git commit -m "feat(e2e-dev-harness): terminating engine (I1) + evidence submit"
```

---

### Task 7: 导航地图 (整段旅程,避免局部最�?

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/core/navigation.py`
- Test: `skills/e2e-dev-harness/tests/test_navigation.py`

- [ ] **Step 1: 写失败测�?*

`test_navigation.py`:
```python
from e2e_harness.core import lifecycle, navigation, run_state, engine
from e2e_harness import pipeline


def _spine():
    return lifecycle.build_spine(pipeline.active_phase_names("minimal"))


def test_map_shows_full_journey_and_goal():
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(_spine(), st)   # -> CLARIFIED
    m = navigation.navigation_map(_spine(), st)
    assert [p["name"] for p in m["phases"]] == ["CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"]
    assert m["goal"] == "VERIFIED"
    assert m["you_are_here"] == "CLARIFIED"


def test_map_status_and_progress():
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(_spine(), st)
    m = navigation.navigation_map(_spine(), st)
    status = {p["name"]: p["status"] for p in m["phases"]}
    assert status["CREATED"] == "done"
    assert status["CLARIFIED"] == "current"
    assert status["RED"] == "pending"
    assert m["progress"] == "1/5"   # CREATED done


def test_map_marks_skipped_phases():
    st = run_state.new_run_state("r1", "f", "r")
    m = navigation.navigation_map(_spine(), st)
    full = {p["name"]: p["status"] for p in m["full_catalog"]}
    assert full["PLANNED"] == "skipped"
    assert full["REVIEWED"] == "skipped"
```

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_navigation.py -v`
Expected: FAIL �?`ModuleNotFoundError`

- [ ] **Step 3: 实现 navigation.py**

```python
"""Derived whole-journey navigation map (no hand-maintained state)."""
from __future__ import annotations

from e2e_harness.core import gates
from e2e_harness.core.lifecycle import Phase, catalog

GOAL = "VERIFIED"


def _phase_status(spine: list[Phase], state: dict, idx: int) -> str:
    names = [p.name for p in spine]
    cur = state.get("current_phase", spine[0].name)
    cur_idx = names.index(cur) if cur in names else 0
    phase = spine[idx]
    rec = state.get("phases", {}).get(phase.name, {})
    if idx < cur_idx:
        return "done"
    if idx == cur_idx:
        ok, _ = gates.gate_passes(phase, rec)
        if phase.next_phase is None and ok:
            return "done"
        return "current"   # 当前阶段�?你该做这�?;blocked 细分留给 M2
    return "pending"


def navigation_map(spine: list[Phase], state: dict) -> dict:
    phases = [{"name": p.name, "status": _phase_status(spine, state, i)}
              for i, p in enumerate(spine)]
    active = {p.name for p in spine}
    full = []
    for name in catalog():
        if name in active:
            st = next(x["status"] for x in phases if x["name"] == name)
        else:
            st = "skipped"
        full.append({"name": name, "status": st})
    done = sum(1 for p in phases if p["status"] == "done")
    return {
        "schema": "e2e-dev-harness.navigation-map.v1",
        "goal": GOAL,
        "you_are_here": state.get("current_phase", spine[0].name),
        "phases": phases,
        "full_catalog": full,
        "progress": f"{done}/{len(spine)}",
    }
```

- [ ] **Step 4: 运行,确认通过**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_navigation.py -v`
Expected: PASS(3 �?

- [ ] **Step 5: 提交**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/navigation.py skills/e2e-dev-harness/tests/test_navigation.py
git commit -m "feat(e2e-dev-harness): derived whole-journey navigation map"
```

---

### Task 8: CLI 6 动词 + 入口 shim

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/{start,next,dispatch,submit,gate,status}.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`
- Test: `skills/e2e-dev-harness/tests/test_cli_e2e.py`

- [ ] **Step 1: 写失败的 e2e 终止测试**

`test_cli_e2e.py`:
```python
import json
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness.py"


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def test_start_then_drive_to_verified_terminates(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    assert code == 0
    state_path = res["run_state"]
    steps = 0
    nres = {"complete": False}
    while steps < 50:
        steps += 1
        code, nres = _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
        if nres["complete"]:
            break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            _run("submit", "--state", state_path, "--phase", phase,
                 "--key", key, "--path", f"{phase}-{key}.md",
                 "--repo", str(tmp_path), cwd=tmp_path)
    assert nres["complete"] is True
    assert nres["navigation_map"]["you_are_here"] == "VERIFIED"
    assert steps <= 6


def test_dispatch_returns_pointer_packet(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    code, dres = _run("dispatch", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    assert dres["skill"] == "e2e-harness-clarification"
    assert dres["expected_outputs"] == ["clarification"]
```

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_cli_e2e.py -v`
Expected: FAIL �?entry 不存�?/ JSON 解析失败

- [ ] **Step 3: 实现 commands/start.py**

```python
"""start: create the one run-state."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from e2e_harness.core import run_state


def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.feature
    rel = Path("docs/agent-runs") / run_id / "run-state.json"
    path = repo / rel
    st = run_state.new_run_state(run_id, args.feature, args.request)
    run_state.save(path, st)
    return 0, {"schema": "e2e-dev-harness.start.v1", "run_id": run_id,
               "run_state": str(path), "current_phase": "CREATED"}
```

- [ ] **Step 4: 实现 commands/next.py**

```python
"""next: advance spine or return single blocker + navigation map."""
from __future__ import annotations

from e2e_harness.core import run_state, lifecycle, engine, navigation
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    state["_run_state_path"] = str(args.state)
    spine = lifecycle.build_spine(pipeline.active_phase_names(state.get("pipeline", "minimal")))
    res = engine.evaluate(spine, state)
    state.pop("_run_state_path", None)
    run_state.save(args.state, state)
    res["navigation_map"] = navigation.navigation_map(spine, state)
    res["run_state"] = str(args.state)
    return 0, res
```

- [ ] **Step 5: 实现 commands/dispatch.py**

```python
"""dispatch: emit one pointer worker packet for the current phase."""
from __future__ import annotations

from e2e_harness.core import run_state, lifecycle, dispatch
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    spine = lifecycle.build_spine(pipeline.active_phase_names(state.get("pipeline", "minimal")))
    name = state.get("current_phase")
    phase = next((p for p in spine if p.name == name), None)
    if phase is None or not phase.worker_skill:
        return 2, {"error": f"no dispatchable worker at phase {name}"}
    rec = state.setdefault("phases", {}).setdefault(name, {})
    rec["dispatch"] = dispatch.DispatchStatus.DISPATCHED.value
    run_state.save(args.state, state)
    return 0, dispatch.worker_packet(phase, str(args.state))
```

- [ ] **Step 6: 实现 commands/submit.py**

```python
"""submit: record worker evidence and mark dispatch done."""
from __future__ import annotations

from e2e_harness.core import run_state, engine


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    engine.submit_evidence(state, args.phase, args.key, args.path)
    run_state.save(args.state, state)
    return 0, {"schema": "e2e-dev-harness.submit.v1", "phase": args.phase,
               "key": args.key, "recorded": args.path}
```

- [ ] **Step 7: 实现 commands/gate.py**

```python
"""gate: run a phase's declarative exit_gate."""
from __future__ import annotations

from e2e_harness.core import run_state, lifecycle, gates
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    spine = lifecycle.build_spine(pipeline.active_phase_names(state.get("pipeline", "minimal")))
    name = args.phase or state.get("current_phase")
    phase = next((p for p in spine if p.name == name), None)
    if phase is None:
        return 2, {"error": f"unknown phase {name}"}
    rec = state.get("phases", {}).get(name, {})
    ok, missing = gates.gate_passes(phase, rec)
    return (0 if ok else 1), {"phase": name, "passed": ok, "missing_evidence": missing}
```

- [ ] **Step 8: 实现 commands/status.py**

```python
"""status: human-readable navigation map (same source as next)."""
from __future__ import annotations

from e2e_harness.core import run_state, lifecycle, navigation
from e2e_harness import pipeline


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    spine = lifecycle.build_spine(pipeline.active_phase_names(state.get("pipeline", "minimal")))
    return 0, {"navigation_map": navigation.navigation_map(spine, state)}
```

- [ ] **Step 9: 实现 cli/main.py**

```python
"""Unified e2e-dev-harness CLI: 6 verbs."""
from __future__ import annotations

import argparse
import json
import sys

from e2e_harness.cli.commands import start, next as next_cmd, dispatch, submit, gate, status

_COMMANDS = {
    "start": start.run, "next": next_cmd.run, "dispatch": dispatch.run,
    "submit": submit.run, "gate": gate.run, "status": status.run,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="e2e-dev-harness")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("start"); s.add_argument("--repo", default=".")
    s.add_argument("--feature", required=True); s.add_argument("--request", required=True)

    for verb in ("next", "dispatch", "status"):
        sp = sub.add_parser(verb); sp.add_argument("--state", required=True); sp.add_argument("--repo", default=".")

    sm = sub.add_parser("submit"); sm.add_argument("--state", required=True); sm.add_argument("--repo", default=".")
    sm.add_argument("--phase", required=True); sm.add_argument("--key", required=True); sm.add_argument("--path", required=True)

    g = sub.add_parser("gate"); g.add_argument("--state", required=True); g.add_argument("--repo", default=".")
    g.add_argument("--phase", default=None)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    code, result = _COMMANDS[args.command](args)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 10: 实现入口 shim e2e_dev_harness.py**

```python
#!/usr/bin/env python3
"""Entry shim -> e2e_harness.cli.main."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_harness.cli.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 11: 运行,确认通过**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_cli_e2e.py -v`
Expected: PASS(2 �?——`start �?VERIFIED` �?�? 步内终止

- [ ] **Step 12: 提交**

```bash
git add skills/e2e-dev-harness/scripts skills/e2e-dev-harness/tests/test_cli_e2e.py
git commit -m "feat(e2e-dev-harness): 6-verb CLI + e2e start->VERIFIED terminates"
```

---

### Task 9: worker skills 改造为 Superpowers 委派�?(minimal 路径 4 �?

**Files:**
- Modify: `skills/e2e-harness-clarification/SKILL.md`(追加于文件末�?
- Modify: `skills/e2e-harness-tdd-red/SKILL.md`(追加于文件末�?
- Modify: `skills/e2e-harness-implementation/SKILL.md`(追加于文件末�?
- Modify: `skills/e2e-harness-completion/SKILL.md`(追加于文件末�?
- Test: `skills/e2e-dev-harness/tests/test_worker_skills_delegate.py`

> 说明: 这些 skill �?markdown(非代�?symbol),改动�?*新增** Superpowers 委派段与 e2e-dev-harness 产物契约,不删�?CLI �?避免破坏�?skill,spec §16)�?

- [ ] **Step 1: 写失败测�?(校验委派 + 产物契约存在)**

`test_worker_skills_delegate.py`:
```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAP = {
    "e2e-harness-clarification": "superpowers:brainstorming",
    "e2e-harness-tdd-red": "superpowers:test-driven-development",
    "e2e-harness-implementation": "superpowers:test-driven-development",
    "e2e-harness-completion": "superpowers:verification-before-completion",
}
OUTPUTS = {
    "e2e-harness-clarification": "clarification",
    "e2e-harness-tdd-red": "failing_tests",
    "e2e-harness-implementation": "passing_tests",
    "e2e-harness-completion": "verification",
}


def test_worker_skills_delegate_and_declare_outputs():
    for skill, sp in MAP.items():
        text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert sp in text, f"{skill} 未委�?{sp}"
        assert OUTPUTS[skill] in text, f"{skill} 未声明产�?{OUTPUTS[skill]}"
        assert "expected_outputs" in text, f"{skill} 缺产物契约段"
```

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_worker_skills_delegate.py -v`
Expected: FAIL �?现有 skill 未含 Superpowers 委派/产物契约

- [ ] **Step 3: �?e2e-harness-clarification/SKILL.md**

在文件末�?现第 16 行之�?追加:
```markdown

## e2e-dev-harness 契约 (e2e-dev-harness)

- **方法委派**: �?`superpowers:brainstorming` 完成澄清(意图、验收标准、影响、开放问�?。本 skill 只持 harness 专属胶水,不重造方法�?
- **expected_outputs**: 产出证据�?`clarification` —�?�?`docs/agent-runs/<run>/handoffs/01-requirements-clarifier.md`,然后:
  `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase CLARIFIED --key clarification --path <handoff-path>`
- **上下�?*: 不继�?coordinator 对话;只用 packet �?`context_paths`�?
```

- [ ] **Step 4: �?e2e-harness-tdd-red/SKILL.md**

文件末尾追加:
```markdown

## e2e-dev-harness 契约 (e2e-dev-harness)

- **方法委派**: �?`superpowers:test-driven-development`(红阶�?写出证明验收标准的失败测试�?
- **expected_outputs**: 产出证据�?`failing_tests` —�?提交失败测试证据�?
  `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase RED --key failing_tests --path <evidence-path>`
- **上下�?*: 不继�?coordinator 对话;只用 packet �?`context_paths`�?
```

- [ ] **Step 5: �?e2e-harness-implementation/SKILL.md**

文件末尾追加:
```markdown

## e2e-dev-harness 契约 (e2e-dev-harness)

- **方法委派**: �?`superpowers:test-driven-development`(绿阶�?写最小实现让红测转绿;遇阻�?`superpowers:systematic-debugging`�?
- **expected_outputs**: 产出证据�?`passing_tests` —�?测试转绿�?
  `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase IMPLEMENTED --key passing_tests --path <evidence-path>`
- **上下�?*: 不继�?coordinator 对话;只用 packet �?`context_paths`�?
```

- [ ] **Step 6: �?e2e-harness-completion/SKILL.md**

文件末尾追加:
```markdown

## e2e-dev-harness 契约 (e2e-dev-harness)

- **方法委派**: �?`superpowers:verification-before-completion` 做完成前验证(全测通过、验收对�?�?
- **expected_outputs**: 产出证据�?`verification` —�?验证通过�?
  `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase VERIFIED --key verification --path <evidence-path>`
- **上下�?*: 不继�?coordinator 对话;只用 packet �?`context_paths`�?
```

- [ ] **Step 7: 运行,确认通过**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_worker_skills_delegate.py -v`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add skills/e2e-harness-clarification/SKILL.md skills/e2e-harness-tdd-red/SKILL.md skills/e2e-harness-implementation/SKILL.md skills/e2e-harness-completion/SKILL.md skills/e2e-dev-harness/tests/test_worker_skills_delegate.py
git commit -m "feat(e2e-dev-harness): worker skills delegate to Superpowers + e2e-dev-harness output contract"
```

---

### Task 10: e2e-dev-harness SKILL.md (coordinator 控制面入�? + 全量回归

**Files:**
- Create: `skills/e2e-dev-harness/SKILL.md`
- Test: `skills/e2e-dev-harness/tests/test_skill_md.py`

- [ ] **Step 1: 写失败测�?*

`test_skill_md.py`:
```python
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


def test_skill_md_has_frontmatter_and_verbs():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name: e2e-dev-harness" in text
    for verb in ("start", "next", "dispatch", "submit", "gate", "status"):
        assert verb in text
    assert "指针" in text or "pointer" in text   # coordinator 控制面纪�?
    assert "VERIFIED" in text
```

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_skill_md.py -v`
Expected: FAIL �?SKILL.md 不存�?

- [ ] **Step 3: �?SKILL.md**

```markdown
---
name: e2e-dev-harness
description: Use when a feature/bugfix/refactor needs a multi-agent dev workflow that reliably runs to completion �?clarification, TDD, review, verification �?with a single source of truth, declarative tier-scaled gates, and worker subagents that self-load Superpowers skills.
---

# E2E Dev Harness e2e-dev-harness

把需求变�?澄清→TDD→实现→(审查)→验�?的多 agent 流程,**保证跑到 VERIFIED**�?

## Coordinator 纪律 (控制�?only)

- 你只�?run-state、发 worker packet、记证据、推进主干�?*�?*做本地代码探�?设计/TDD/审查/实现�?
- worker packet �?*指针**(role + skill + context_paths + expected_outputs),worker �?agent **首动作是 invoke 自己�?skill**,方法委派�?Superpowers�?
- 每步�?`navigation_map`:全旅�?`CREATED→…→VERIFIED`,始终对照终点目标,避免局部最优�?

## 6 动词

```bash
S=skills/e2e-dev-harness/scripts/e2e_dev_harness.py
python $S start --repo . --feature "<feat>" --request "<原始需�?"   # 创建唯一 run-state
python $S next   --state <run-state>     # 推进主干或返回单一 blocker + navigation_map
python $S dispatch --state <run-state>   # 产出当前阶段的指�?worker packet
python $S submit --state <run-state> --phase <P> --key <k> --path <p>  # 记录 worker 证据
python $S gate   --state <run-state>     # 跑当前阶段声明式门禁
python $S status --state <run-state>     # 人读导航地图
```

## 循环

`start` �?循环{ `next` �?�?`complete` 收尾;否则 `dispatch` 当前阶段 �?spawn worker �?agent(自加�?`next_action.skill`)�?worker `submit` 证据 �?回到 `next` } 直到 `VERIFIED`�?

## tier (M1: minimal)

`minimal` = CREATED→CLARIFIED→RED→IMPLEMENTED→VERIFIED(跳过 PLANNED/REVIEWED)。更�?tier 与用户自定义流水线见后续里程碑�?
```

- [ ] **Step 4: 运行,确认通过**

Run: `python -m pytest skills/e2e-dev-harness/tests/test_skill_md.py -v`
Expected: PASS

- [ ] **Step 5: 全量回归 (e2e-dev-harness + 旧套�?**

Run: `python -m pytest skills/e2e-dev-harness/tests/ -v`
Expected: 全绿(本计划全部测�?

Run: `python -m pytest tests/ -q`
Expected: �?1266 项不受影�?仍全�?

- [ ] **Step 6: 提交**

```bash
git add skills/e2e-dev-harness/SKILL.md skills/e2e-dev-harness/tests/test_skill_md.py
git commit -m "feat(e2e-dev-harness): coordinator SKILL.md + M1 green"
```

---

## 验收 (M1 出口)

- [ ] `python -m pytest skills/e2e-dev-harness/tests/ -v` 全绿�?
- [ ] I1: `test_engine_termination.py` 证明任意路径 ≤len(spine)+1 步终止�?
- [ ] I2: `test_gate_closure.py` 证明 minimal 流水线门禁闭�?且能检出不可满足�?
- [ ] e2e: `test_cli_e2e.py` 证明 `start �?VERIFIED` �?�? 步内 `complete`(�?harness 过不了的那条)�?
- [ ] �?`tests/` 1266 项不受影�? `python -m pytest tests/ -q` 仍全绿�?
- [ ] worker packet 为指�?无内联指�?;4 �?minimal worker skill 委派 Superpowers�?

## 后续里程�?(各自独立计划)

- **M2 后端完整**: standard/critical/audited tier + 阶段裁剪结构�?+ r1/r2/r3 review fan-out + port scanner/KG/task_tier/memory 至窄接口�?
- **M3 配置�?*: `pipelines/*.yaml` + `validate-pipeline`(对任意配置跑 I1/I2)+ 用户自定义流水线�?
- **M4 前端适配**: `DomainAdapter` 前端实现(scanner + test_runner + review_profile)�?
- **M5 切换**: e2e-dev-harness 设默认、迁移文档、删�?skill(无能力损�?�?
```
