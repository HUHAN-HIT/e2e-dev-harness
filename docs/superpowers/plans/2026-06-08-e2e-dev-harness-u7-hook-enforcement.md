# U7 �?e2e-dev-harness Hook 强制�?Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** �?e2e-dev-harness 一个工具层 PreToolUse + Stop hook 强制�?使非实现 phase 阻止 code write,补回 legacy `phase_guard` 的核�?TDD/phase 纪律�?
**Architecture:** 声明式判�?(`Phase.allows_code_write` + `pipeline.can_write_code`) 作单一真相�?两个�?hook (`phase_guard` / `stop_guard`) �?e2e-dev-harness run-state 并复用从 legacy port 的路径无关逻辑 (`adapters/hooks/paths.py`);claude + opencode �?runtime �?example config �?skill 提供 (installer 安装落在 U6)�?
**Tech Stack:** Python 3 (stdlib only: `json`/`pathlib`/`argparse`), pytest, PyYAML (既有), Claude Code PreToolUse/Stop hook 协议, opencode plugin (`tool.execute.before`)�?
**Design source:** [docs/superpowers/specs/2026-06-08-e2e-dev-harness-u7-hook-enforcement-design.md](../specs/2026-06-08-e2e-dev-harness-u7-hook-enforcement-design.md)

---

## 执行约定 (per CLAUDE.md / 分支约束)

- **测试命令:** `cd skills/e2e-dev-harness && python -m pytest tests/ -q`
- **单文件测�?** `cd skills/e2e-dev-harness && python -m pytest tests/<file>::<test> -v`
- **修改既有 e2e-dev-harness symbol �?(Task 1/2/3 触及 `lifecycle.Phase`/`pipeline`/`pipeline_validate`):** �?`cd skills/e2e-dev-harness && npx gitnexus analyze`(当前索引 stale),�?`gitnexus_impact({target, direction:"upstream", repo:"e2e-dev-workflow"})`,HIGH/CRITICAL 风险须先报告。新建文�?(Task 4�? 主体) 无既�?symbol,�?impact�?- **dispatch 损坏** �?全程内联落地,不走 subagent 两阶�?每完成一�?Task commit,�?plan 完成�?`/code-review`�?- **完成�?* `gitnexus_detect_changes({scope:"unstaged"})` 校验影响面�?- **installer �?hook 不在�?plan** �?�?U6 Stage 2/3(design §6/§8),�?plan 只产�?example 模板�?
---

## File Structure

**新建:**
- `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/__init__.py` �?包标�?- `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/paths.py` �?路径无关分类 + run-state 发现 (port �?legacy,纯逻辑)
- `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/phase_guard.py` �?PreToolUse 薄壳
- `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/stop_guard.py` �?Stop 薄壳
- `skills/e2e-dev-harness/hooks/claude-code-settings.example.json` �?claude hook 模板
- `skills/e2e-dev-harness/hooks/opencode-plugin.example.js` �?opencode plugin 模板
- `skills/e2e-dev-harness/tests/test_can_write_code.py`
- `skills/e2e-dev-harness/tests/test_hook_paths.py`
- `skills/e2e-dev-harness/tests/test_phase_guard.py`
- `skills/e2e-dev-harness/tests/test_stop_guard.py`
- `skills/e2e-dev-harness/tests/test_hook_examples.py`
- `skills/e2e-dev-harness/tests/test_phase_guard_e2e.py`

**修改:**
- `skills/e2e-dev-harness/scripts/e2e_harness/core/lifecycle.py` �?`Phase` �?`allows_code_write: bool = False`
- `skills/e2e-dev-harness/scripts/e2e_harness/pipeline.py` �?`_OVERRIDE_FIELDS` �?`allows_code_write`;`_entry_name_and_overrides` 收集�?非catalog `Phase(...)` 传它;新增 `can_write_code(state)`
- `skills/e2e-dev-harness/scripts/e2e_harness/core/pipeline_validate.py` �?接受可�?`allows_code_write` (bool 校验)
- `skills/e2e-dev-harness/pipelines/minimal.yaml` �?`IMPLEMENTED` 升级 mapping `allows_code_write: true`
- `skills/e2e-dev-harness/pipelines/standard.yaml` �?同上
- `skills/e2e-dev-harness/pipelines/critical.yaml` �?同上
- `skills/e2e-dev-harness/pipelines/audited.yaml` �?同上

**关键设计�?(避循环依�?:** `can_write_code` �?`pipeline.py`(�?import `lifecycle` 且有 `spine_for_state`),而非 design §3.1 字面�?`core/lifecycle`。`lifecycle.py` 仍是 phase **字段** 真相�?`pipeline.py` �?spine **组装** 真相源。`phase_guard` import `pipeline` + `run_state` + `paths`,无环�?
---

## Task 1: `Phase.allows_code_write` 字段 + `can_write_code` 判定

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/lifecycle.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/pipeline.py`
- Test: `skills/e2e-dev-harness/tests/test_can_write_code.py`

- [ ] **Step 0: impact (CLAUDE.md)**

Run: `cd skills/e2e-dev-harness && npx gitnexus analyze` 然后 `gitnexus_impact({target:"Phase", direction:"upstream", repo:"e2e-dev-workflow"})` �?`gitnexus_impact({target:"spec_to_spine", direction:"upstream", repo:"e2e-dev-workflow"})`。报�?blast radius;HIGH/CRITICAL 先告知用户�?
- [ ] **Step 1: 写失败测�?*

Create `skills/e2e-dev-harness/tests/test_can_write_code.py`:

```python
from e2e_harness import pipeline
from e2e_harness.core import lifecycle


def test_phase_defaults_to_no_code_write():
    p = lifecycle.Phase("X", "", "", (), (), None)
    assert p.allows_code_write is False


def test_catalog_phases_all_default_false():
    for name, phase in lifecycle.catalog().items():
        assert phase.allows_code_write is False, name


def _state(current, phases):
    return {"current_phase": current, "pipeline_spec": {"name": "t", "phases": phases}}


def test_mapping_phase_with_flag_allows():
    state = _state("IMPLEMENTED", [
        "CREATED", "CLARIFIED", "RED",
        {"phase": "IMPLEMENTED", "allows_code_write": True},
        "VERIFIED",
    ])
    assert pipeline.can_write_code(state) is True


def test_bare_string_phase_denies():
    state = _state("RED", ["CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"])
    assert pipeline.can_write_code(state) is False


def test_bare_string_implemented_denies_without_flag():
    # bare-string inherits catalog default (False) �?only an explicit flag opens it.
    state = _state("IMPLEMENTED", ["CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"])
    assert pipeline.can_write_code(state) is False


def test_missing_current_phase_denies():
    state = {"pipeline_spec": {"name": "t", "phases": ["CREATED", "VERIFIED"]}}
    assert pipeline.can_write_code(state) is False


def test_current_phase_not_in_spine_denies():
    state = _state("GHOST", ["CREATED", "VERIFIED"])
    assert pipeline.can_write_code(state) is False
```

- [ ] **Step 2: 跑测试确�?fail**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_can_write_code.py -q`
Expected: FAIL (`AttributeError: ... 'allows_code_write'` �?`can_write_code` 不存�?

- [ ] **Step 3: �?`Phase` 加字�?*

Modify `skills/e2e-dev-harness/scripts/e2e_harness/core/lifecycle.py` �?`Phase` dataclass 加末位带默认字段:

```python
@dataclass(frozen=True)
class Phase:
    name: str
    worker_role: str
    worker_skill: str
    produces: tuple[str, ...]
    exit_gate: tuple[str, ...]
    next_phase: str | None
    allows_code_write: bool = False
```

(`_CATALOG` �?6-位置构造不�?新字段默�?False�?

- [ ] **Step 4: `pipeline.py` 收集 override + 新增 `can_write_code`**

Modify `skills/e2e-dev-harness/scripts/e2e_harness/pipeline.py`:

4a. `_OVERRIDE_FIELDS` �?`allows_code_write`:

```python
_OVERRIDE_FIELDS = ("worker_role", "worker_skill", "produces", "exit_gate", "allows_code_write")
```

4b. `_entry_name_and_overrides` �?override 收集循环保持通用(`allows_code_write` �?bool,不走 `produces`/`exit_gate` �?tuple 分支,落入 else 原样取�?——当前实现已满足:

```python
def _entry_name_and_overrides(entry) -> tuple[str, dict]:
    if isinstance(entry, str):
        return entry, {}
    if not isinstance(entry, dict) or "phase" not in entry:
        raise ValueError(f"invalid phase entry: {entry!r}")
    overrides = {}
    for k in _OVERRIDE_FIELDS:
        if k in entry:
            overrides[k] = tuple(entry[k]) if k in ("produces", "exit_gate") else entry[k]
    return entry["phase"], overrides
```

4c. `spec_to_spine` 的非catalog 分支显式�?`allows_code_write`(默认 False):

```python
        else:  # non-catalog phase: must be fully specified (validation enforces)
            spine.append(Phase(
                name=name,
                worker_role=overrides["worker_role"],
                worker_skill=overrides["worker_skill"],
                produces=overrides["produces"],
                exit_gate=overrides["exit_gate"],
                next_phase=nxt,
                allows_code_write=overrides.get("allows_code_write", False),
            ))
```

4d. 文件末尾新增 `can_write_code`:

```python
def can_write_code(state: dict) -> bool:
    """True iff state['current_phase'] resolves to a spine phase declaring allows_code_write.

    Single source of phase code-write authority �?reused by the PreToolUse hook
    and any CLI that needs the same answer. Conservative: unknown / missing phase �?False.
    """
    current = state.get("current_phase")
    if not current:
        return False
    for phase in spine_for_state(state):
        if phase.name == current:
            return bool(phase.allows_code_write)
    return False
```

- [ ] **Step 5: 跑测试确�?pass + 回归**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_can_write_code.py tests/test_lifecycle_spine.py tests/test_pipeline_yaml_load.py tests/test_pipeline_tiers.py -q`
Expected: PASS (新测试绿;既有 spine/yaml/tier 测试未破)

- [ ] **Step 6: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/lifecycle.py \
        skills/e2e-dev-harness/scripts/e2e_harness/pipeline.py \
        skills/e2e-dev-harness/tests/test_can_write_code.py
git commit -m "feat(e2e-dev-harness): U7 Phase.allows_code_write + can_write_code declarative gate"
```

---

## Task 2: `pipeline_validate` 接受可�?`allows_code_write`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/pipeline_validate.py`
- Test: `skills/e2e-dev-harness/tests/test_pipeline_validate.py` (追加)

- [ ] **Step 0: impact**

Run: `gitnexus_impact({target:"validate_spec", direction:"upstream", repo:"e2e-dev-workflow"})`。报�?blast radius�?
- [ ] **Step 1: 追加失败测试**

Append to `skills/e2e-dev-harness/tests/test_pipeline_validate.py`:

```python
def test_allows_code_write_bool_accepted():
    spec = {"name": "c", "phases": [
        "CREATED",
        {"phase": "IMPLEMENTED", "allows_code_write": True},
        "VERIFIED",
    ]}
    ok, errors = pv.validate_spec(spec)
    assert ok is True, errors


def test_allows_code_write_nonbool_rejected():
    spec = {"name": "c", "phases": [
        "CREATED",
        {"phase": "IMPLEMENTED", "allows_code_write": "yes"},
        "VERIFIED",
    ]}
    ok, errors = pv.validate_spec(spec)
    assert ok is False
    assert any("allows_code_write" in e for e in errors)
```

- [ ] **Step 2: 跑测试确�?fail**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_pipeline_validate.py::test_allows_code_write_nonbool_rejected -v`
Expected: FAIL (非bool 当前未被�?�?error �?`allows_code_write`)

- [ ] **Step 3: validate �?bool 校验**

Modify `skills/e2e-dev-harness/scripts/e2e_harness/core/pipeline_validate.py` �?�?mapping-entry 分支�?`for k in ("produces", "exit_gate")` 校验之后、`if pname in seen` 之前,插入:

```python
            if "allows_code_write" in entry and not isinstance(entry["allows_code_write"], bool):
                errors.append(f"phase '{pname}' field 'allows_code_write' must be a boolean")
```

- [ ] **Step 4: 跑测试确�?pass + 回归**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_pipeline_validate.py -q`
Expected: PASS (含既�?10 测试)

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/core/pipeline_validate.py \
        skills/e2e-dev-harness/tests/test_pipeline_validate.py
git commit -m "feat(e2e-dev-harness): U7 pipeline_validate accepts optional allows_code_write bool"
```

---

## Task 3: 内建 pipeline 升级 `IMPLEMENTED` 写码 phase

**Files:**
- Modify: `skills/e2e-dev-harness/pipelines/minimal.yaml`
- Modify: `skills/e2e-dev-harness/pipelines/standard.yaml`
- Modify: `skills/e2e-dev-harness/pipelines/critical.yaml`
- Modify: `skills/e2e-dev-harness/pipelines/audited.yaml`
- Test: `skills/e2e-dev-harness/tests/test_can_write_code.py` (追加)

- [ ] **Step 1: 追加失败测试**

Append to `skills/e2e-dev-harness/tests/test_can_write_code.py`:

```python
import pytest


@pytest.mark.parametrize("name", ["minimal", "standard", "critical", "audited"])
def test_builtin_implemented_allows_code_write(name):
    state = {"current_phase": "IMPLEMENTED", "pipeline": name}
    assert pipeline.can_write_code(state) is True


@pytest.mark.parametrize("name", ["minimal", "standard", "critical", "audited"])
def test_builtin_nonimplemented_phases_deny(name):
    spine = pipeline.build_spine(name)
    for phase in spine:
        if phase.name == "IMPLEMENTED":
            continue
        state = {"current_phase": phase.name, "pipeline": name}
        assert pipeline.can_write_code(state) is False, f"{name}:{phase.name}"
```

- [ ] **Step 2: 跑测试确�?fail**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_can_write_code.py::test_builtin_implemented_allows_code_write -q`
Expected: FAIL (bare-string `IMPLEMENTED` 继承 catalog 默认 False)

- [ ] **Step 3: 4 �?yaml 升级 `IMPLEMENTED`**

将每个文件中 bare-string `  - IMPLEMENTED` 这一行替换为 mapping�?
`skills/e2e-dev-harness/pipelines/minimal.yaml` 全文:

```yaml
name: minimal
phases:
  - CREATED
  - CLARIFIED
  - RED
  - phase: IMPLEMENTED
    allows_code_write: true
  - VERIFIED
```

`skills/e2e-dev-harness/pipelines/standard.yaml` 全文:

```yaml
name: standard
phases:
  - CREATED
  - CLARIFIED
  - PLANNED
  - RED
  - phase: IMPLEMENTED
    allows_code_write: true
  - REVIEWED
  - VERIFIED
```

`skills/e2e-dev-harness/pipelines/critical.yaml` 全文:

```yaml
name: critical
phases:
  - CREATED
  - CLARIFIED
  - PLANNED
  - RED
  - phase: IMPLEMENTED
    allows_code_write: true
  - phase: REVIEWED
    produces: [r1_review, r2_review, r3_review]
    exit_gate: [r1_review, r2_review, r3_review]
  - VERIFIED
```

`skills/e2e-dev-harness/pipelines/audited.yaml` 全文:

```yaml
name: audited
phases:
  - CREATED
  - CLARIFIED
  - PLANNED
  - RED
  - phase: IMPLEMENTED
    allows_code_write: true
  - phase: REVIEWED
    produces: [r1_review, r2_review, r3_review]
    exit_gate: [r1_review, r2_review, r3_review]
  - phase: VERIFIED
    produces: [verification, audit_replay]
    exit_gate: [verification, audit_replay]
```

- [ ] **Step 4: 跑测试确�?pass + spec 校验回归**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_can_write_code.py tests/test_pipeline_validate.py tests/test_pipeline_yaml_load.py -q`
Expected: PASS (内建 spec �?valid;IMPLEMENTED �?tier 放行,其余�?

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/pipelines/minimal.yaml \
        skills/e2e-dev-harness/pipelines/standard.yaml \
        skills/e2e-dev-harness/pipelines/critical.yaml \
        skills/e2e-dev-harness/pipelines/audited.yaml \
        skills/e2e-dev-harness/tests/test_can_write_code.py
git commit -m "feat(e2e-dev-harness): U7 builtin pipelines mark IMPLEMENTED allows_code_write"
```

---

## Task 4: `adapters/hooks/paths.py` �?路径无关逻辑 port

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/__init__.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/paths.py`
- Test: `skills/e2e-dev-harness/tests/test_hook_paths.py`

- [ ] **Step 1: 写失败测�?*

Create `skills/e2e-dev-harness/tests/test_hook_paths.py`:

```python
from pathlib import Path

from e2e_harness.adapters.hooks import paths as hp


def test_code_path_by_suffix(tmp_path):
    assert hp.is_code_path(tmp_path, Path("src/app/foo.py")) is True
    assert hp.is_code_path(tmp_path, Path("src/app/Foo.java")) is True


def test_code_filename(tmp_path):
    assert hp.is_code_path(tmp_path, Path("service/pom.xml")) is True


def test_docs_and_artifacts_not_code(tmp_path):
    assert hp.is_code_path(tmp_path, Path("docs/design/x.md")) is False
    assert hp.is_code_path(tmp_path, Path("docs/agent-runs/r1/run-state.json")) is False
    assert hp.is_code_path(tmp_path, Path("docs/superpowers/plans/p.md")) is False


def test_non_code_suffix(tmp_path):
    assert hp.is_code_path(tmp_path, Path("README.txt")) is False


def test_outside_repo_not_code(tmp_path):
    assert hp.is_code_path(tmp_path, Path("/etc/passwd.py")) is False


def test_control_file_detection(tmp_path):
    assert hp.is_control_file_path(tmp_path, Path("docs/agent-runs/r1/run-state.json")) is True
    assert hp.is_control_file_path(tmp_path, Path("src/run-state.json")) is True
    assert hp.is_control_file_path(tmp_path, Path("src/app.py")) is False


def test_hook_config_detection(tmp_path):
    assert hp.is_hook_config_path(tmp_path, Path(".claude/settings.json")) is True
    assert hp.is_hook_config_path(tmp_path, Path(".opencode/plugins/e2e.js")) is True
    assert hp.is_hook_config_path(tmp_path, Path("src/settings.json")) is False


def test_discover_run_state_picks_latest(tmp_path):
    runs = tmp_path / "docs" / "agent-runs"
    (runs / "old").mkdir(parents=True)
    (runs / "new").mkdir(parents=True)
    old = runs / "old" / "run-state.json"
    new = runs / "new" / "run-state.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    import os, time
    t = time.time()
    os.utime(old, (t - 100, t - 100))
    os.utime(new, (t, t))
    assert hp.discover_run_state(tmp_path) == new


def test_discover_run_state_none_when_absent(tmp_path):
    assert hp.discover_run_state(tmp_path) is None
```

- [ ] **Step 2: 跑测试确�?fail**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_hook_paths.py -q`
Expected: FAIL (`ModuleNotFoundError: e2e_harness.adapters.hooks`)

- [ ] **Step 3: 建包 + 实现**

Create `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/__init__.py` (空文�?:

```python
```

Create `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/paths.py`:

```python
"""Path-agnostic classification ported from legacy phase_guard.

e2e-dev-harness 收敛 (design §3.2): 控制文件�?= {run-state.json}(�?.phase-lock);
hook-config �?claude + opencode。除 `discover_run_state` 外皆为纯函数�?"""
from __future__ import annotations

from pathlib import Path

CODE_SUFFIXES = {
    ".java", ".kt", ".groovy", ".py", ".js", ".jsx", ".ts", ".tsx",
    ".go", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".sql",
    ".xml", ".yml", ".yaml", ".properties", ".gradle",
}
CODE_FILENAMES = {"pom.xml", "build.gradle", "settings.gradle", "Dockerfile"}
ARTIFACT_PREFIXES = ("docs/agent-runs/",)
DOC_PREFIXES = (
    "docs/design/", "docs/requirements/", "docs/review-profiles/",
    "docs/superpowers/", ".e2e/",
)
CONTROL_FILENAMES = {"run-state.json"}
HOOK_CONFIG_PATHS = {".claude/settings.json"}
HOOK_CONFIG_PREFIXES = (".opencode/plugins/", ".opencode/plugin/")


def resolve_for_repo(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def is_inside_repo(repo: Path, path: Path) -> bool:
    resolved = resolve_for_repo(repo, path)
    if not resolved.is_absolute():
        return True
    try:
        resolved.resolve().relative_to(repo.resolve())
        return True
    except ValueError:
        return False


def posix_relative(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/").lstrip("/")


def is_code_path(repo: Path, path: Path) -> bool:
    resolved = resolve_for_repo(repo, path)
    if not is_inside_repo(repo, resolved):
        return False
    relative = posix_relative(repo, resolved)
    if relative.startswith(ARTIFACT_PREFIXES):
        return False
    if relative.startswith(DOC_PREFIXES):
        return False
    return resolved.name in CODE_FILENAMES or resolved.suffix in CODE_SUFFIXES


def is_control_file_path(repo: Path, path: Path) -> bool:
    resolved = resolve_for_repo(repo, path)
    return resolved.name in CONTROL_FILENAMES


def is_hook_config_path(repo: Path, path: Path) -> bool:
    relative = posix_relative(repo, resolve_for_repo(repo, path))
    if relative in HOOK_CONFIG_PATHS:
        return True
    return relative.startswith(HOOK_CONFIG_PREFIXES)


def discover_run_state(repo: Path) -> Path | None:
    """Locate the most recently updated active run-state (the one I/O helper)."""
    runs = Path(repo) / "docs" / "agent-runs"
    if not runs.is_dir():
        return None
    matches = sorted(
        runs.glob("*/run-state.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return matches[0] if matches else None
```

- [ ] **Step 4: 跑测试确�?pass**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_hook_paths.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/__init__.py \
        skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/paths.py \
        skills/e2e-dev-harness/tests/test_hook_paths.py
git commit -m "feat(e2e-dev-harness): U7 hook path classification ported from legacy phase_guard"
```

---

## Task 5: `phase_guard.py` �?PreToolUse 薄壳

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/phase_guard.py`
- Test: `skills/e2e-dev-harness/tests/test_phase_guard.py`

- [ ] **Step 1: 写失败测�?*

Create `skills/e2e-dev-harness/tests/test_phase_guard.py`:

```python
import json
from pathlib import Path

from e2e_harness.adapters.hooks import phase_guard as pg
from e2e_harness.core import run_state


def _write_state(tmp_path, current_phase, pipeline="minimal"):
    state = run_state.new_run_state("r1", "demo", "do x", pipeline=pipeline)
    state["current_phase"] = current_phase
    sp = tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json"
    run_state.save(sp, state)
    return sp


def _hook(tool, **tin):
    return json.dumps({"tool_name": tool, "tool_input": tin})


def test_parse_hook_input_extracts_path_and_command():
    tool, paths, command = pg.parse_hook_input(_hook("Write", file_path="src/a.py", content="x"))
    assert tool == "Write" and paths == ["src/a.py"] and command == ""
    tool, paths, command = pg.parse_hook_input(_hook("Bash", command="echo hi > src/a.py"))
    assert tool == "Bash" and command == "echo hi > src/a.py"


def test_parse_empty_is_safe():
    assert pg.parse_hook_input("") == ("", [], "")
    assert pg.parse_hook_input("not json") == ("", [], "")


def test_code_write_denied_in_non_impl_phase(tmp_path):
    sp = _write_state(tmp_path, "RED")
    d = pg.decide(_hook("Write", file_path=str(tmp_path / "src" / "a.py"), content="x"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "RED" in d["reason"] and "next" in d["reason"]


def test_code_write_allowed_in_impl_phase(tmp_path):
    sp = _write_state(tmp_path, "IMPLEMENTED")
    d = pg.decide(_hook("Write", file_path=str(tmp_path / "src" / "a.py"), content="x"), tmp_path, sp)
    assert d["decision"] == "allow"


def test_non_code_path_allowed(tmp_path):
    sp = _write_state(tmp_path, "RED")
    d = pg.decide(_hook("Write", file_path=str(tmp_path / "docs" / "design" / "x.md"), content="x"), tmp_path, sp)
    assert d["decision"] == "allow"


def test_read_like_tool_no_paths_allowed(tmp_path):
    sp = _write_state(tmp_path, "RED")
    d = pg.decide(_hook("Bash", command="ls -la"), tmp_path, sp)
    assert d["decision"] == "allow"


def test_direct_run_state_write_denied(tmp_path):
    sp = _write_state(tmp_path, "IMPLEMENTED")
    target = tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json"
    d = pg.decide(_hook("Edit", file_path=str(target), new_string="{}"), tmp_path, sp)
    assert d["decision"] == "deny"
    assert "run-state.json" in d["reason"]


def test_shell_redirect_into_run_state_denied(tmp_path):
    sp = _write_state(tmp_path, "IMPLEMENTED")
    d = pg.decide(_hook("Bash", command="echo '{}' > docs/agent-runs/r1/run-state.json"), tmp_path, sp)
    assert d["decision"] == "deny"


def test_settings_json_write_denied(tmp_path):
    sp = _write_state(tmp_path, "IMPLEMENTED")
    d = pg.decide(_hook("Edit", file_path=str(tmp_path / ".claude" / "settings.json"), new_string="{}"), tmp_path, sp)
    assert d["decision"] == "deny"


def test_no_active_run_allows_code_write(tmp_path):
    # require-active-run is deferred (design §7): no run-state �?allow.
    d = pg.decide(_hook("Write", file_path=str(tmp_path / "src" / "a.py"), content="x"), tmp_path, None)
    assert d["decision"] == "allow"


def test_emit_pretooluse_protocol(capsys):
    pg._emit({"decision": "deny", "reason": "nope"})
    out = json.loads(capsys.readouterr().out)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    assert hso["permissionDecisionReason"] == "nope"
```

- [ ] **Step 2: 跑测试确�?fail**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_phase_guard.py -q`
Expected: FAIL (`ModuleNotFoundError: ... phase_guard`)

- [ ] **Step 3: 实现**

Create `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/phase_guard.py`:

```python
"""e2e-dev-harness PreToolUse hook: phase-lock code writes (thin shell over run-state).

Reuses ported path logic (adapters.hooks.paths) and the declarative
pipeline.can_write_code gate. Stdlib only. See design §3.2.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[3]  # .../scripts
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from e2e_harness import pipeline                       # noqa: E402
from e2e_harness.core import run_state                 # noqa: E402
from e2e_harness.adapters.hooks import paths as hook_paths  # noqa: E402

_REDIRECT_TOKENS = (">", ">>", "tee", "set-content", "add-content", "out-file")


def parse_hook_input(text: str) -> tuple[str, list[str], str]:
    if not text.strip():
        return "", [], ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return "", [], ""
    tool = str(data.get("tool_name") or data.get("tool") or "")
    tin = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else data
    paths: list[str] = []
    command = ""
    if isinstance(tin, dict):
        for key in ("file_path", "filePath", "path", "notebook_path", "notebookPath"):
            value = tin.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(value)
        cmd = tin.get("command")
        if isinstance(cmd, str):
            command = cmd
    return tool, paths, command


def _allow() -> dict:
    return {"decision": "allow", "reason": ""}


def _deny(reason: str) -> dict:
    return {"decision": "deny", "reason": reason}


def decide(hook_text: str, repo, run_state_path) -> dict:
    repo = Path(repo)
    _tool, raw_paths, command = parse_hook_input(hook_text)
    paths = [Path(p) for p in raw_paths]

    # Control-file / hook-config direct writes are always denied (bypass guard).
    for p in paths:
        if hook_paths.is_control_file_path(repo, p):
            return _deny(
                f"Direct write to control file {p.name} is not allowed; the harness "
                "CLI owns run-state.json. Use `next` / `gate` / `submit` instead."
            )
        if hook_paths.is_hook_config_path(repo, p):
            return _deny("Direct edit of hook config is not allowed (would bypass the phase guard).")
    low = command.lower()
    if "run-state.json" in low and any(tok in low for tok in _REDIRECT_TOKENS):
        return _deny("Shell redirect into run-state.json is not allowed; the harness CLI owns it.")

    code_paths = [p for p in paths if hook_paths.is_code_path(repo, p)]
    if not code_paths:
        return _allow()

    if run_state_path is None or not Path(run_state_path).is_file():
        return _allow()  # no active run �?require-active-run deferred (design §7)

    state = run_state.load(run_state_path)
    if pipeline.can_write_code(state):
        return _allow()
    phase = state.get("current_phase", "<unknown>")
    return _deny(
        f"Code write blocked: phase {phase} does not allow code writes. Advance the run "
        f"with `python -m e2e_harness next --state {run_state_path}` (then `gate` to satisfy "
        "the exit gate) until an implementation phase is active."
    )


def _emit(result: dict) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": result["decision"],
            "permissionDecisionReason": result["reason"],
        }
    }, ensure_ascii=False))


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--state", default=None)
    parser.add_argument("--hook-input", default="-", help="JSON hook input, or '-' for stdin.")
    args = parser.parse_args(argv)
    text = sys.stdin.read() if args.hook_input == "-" else args.hook_input
    repo = Path(args.repo)
    rsp = Path(args.state) if args.state else hook_paths.discover_run_state(repo)
    _emit(decide(text, repo, rsp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确�?pass**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_phase_guard.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/phase_guard.py \
        skills/e2e-dev-harness/tests/test_phase_guard.py
git commit -m "feat(e2e-dev-harness): U7 phase_guard PreToolUse hook (phase-lock code writes)"
```

---

## Task 6: `stop_guard.py` �?Stop 薄壳

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/stop_guard.py`
- Test: `skills/e2e-dev-harness/tests/test_stop_guard.py`

- [ ] **Step 1: 写失败测�?*

Create `skills/e2e-dev-harness/tests/test_stop_guard.py`:

```python
import json
from pathlib import Path

from e2e_harness.adapters.hooks import stop_guard as sg
from e2e_harness.core import run_state


def _write_state(tmp_path, current_phase):
    state = run_state.new_run_state("r1", "demo", "do x")
    state["current_phase"] = current_phase
    sp = tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json"
    run_state.save(sp, state)
    return sp


def test_unverified_active_run_blocks(tmp_path):
    sp = _write_state(tmp_path, "RED")
    d = sg.decide(sp)
    assert d["decision"] == "block"
    assert "RED" in d["reason"]


def test_verified_allows_stop(tmp_path):
    sp = _write_state(tmp_path, "VERIFIED")
    assert sg.decide(sp)["decision"] == "allow"


def test_no_run_state_allows_stop(tmp_path):
    assert sg.decide(None)["decision"] == "allow"
    assert sg.decide(tmp_path / "missing.json")["decision"] == "allow"


def test_unreadable_run_state_allows_stop(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert sg.decide(bad)["decision"] == "allow"


def test_emit_block_protocol(capsys):
    sg._emit({"decision": "block", "reason": "go on"})
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "block" and out["reason"] == "go on"


def test_emit_allow_is_empty(capsys):
    sg._emit({"decision": "allow", "reason": ""})
    assert json.loads(capsys.readouterr().out) == {}
```

- [ ] **Step 2: 跑测试确�?fail**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_stop_guard.py -q`
Expected: FAIL (`ModuleNotFoundError: ... stop_guard`)

- [ ] **Step 3: 实现**

Create `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/stop_guard.py`:

```python
"""e2e-dev-harness Stop hook: keep going while a run is active and not VERIFIED.

Thin version of legacy harness_stop_guard �?reads only run-state.current_phase.
Stdlib only. See design §3.3.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[3]  # .../scripts
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from e2e_harness.core import run_state                 # noqa: E402
from e2e_harness.adapters.hooks import paths as hook_paths  # noqa: E402

TERMINAL_PHASES = {"VERIFIED"}


def decide(run_state_path) -> dict:
    if run_state_path is None or not Path(run_state_path).is_file():
        return {"decision": "allow", "reason": ""}
    try:
        state = run_state.load(run_state_path)
    except (ValueError, OSError, json.JSONDecodeError):
        return {"decision": "allow", "reason": ""}
    phase = state.get("current_phase", "")
    if phase in TERMINAL_PHASES:
        return {"decision": "allow", "reason": ""}
    return {
        "decision": "block",
        "reason": (
            f"Run {state.get('run_id', '')} is at phase {phase}, not VERIFIED. "
            "Continue advancing the harness (`next` / `gate` / `submit`) instead of stopping."
        ),
    }


def _emit(result: dict) -> None:
    if result["decision"] == "block":
        print(json.dumps({"decision": "block", "reason": result["reason"]}, ensure_ascii=False))
    else:
        print(json.dumps({}, ensure_ascii=False))


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--state", default=None)
    parser.add_argument("--hook-input", default="-", help="JSON hook input, or '-' for stdin.")
    args = parser.parse_args(argv)
    if args.hook_input == "-":
        try:
            sys.stdin.read()
        except (OSError, ValueError):
            pass
    repo = Path(args.repo)
    rsp = Path(args.state) if args.state else hook_paths.discover_run_state(repo)
    _emit(decide(rsp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确�?pass**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_stop_guard.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/stop_guard.py \
        skills/e2e-dev-harness/tests/test_stop_guard.py
git commit -m "feat(e2e-dev-harness): U7 stop_guard Stop hook (continue until VERIFIED)"
```

---

## Task 7: runtime example configs (claude + opencode)

**Files:**
- Create: `skills/e2e-dev-harness/hooks/claude-code-settings.example.json`
- Create: `skills/e2e-dev-harness/hooks/opencode-plugin.example.js`
- Test: `skills/e2e-dev-harness/tests/test_hook_examples.py`

- [ ] **Step 1: 写失败测�?*

Create `skills/e2e-dev-harness/tests/test_hook_examples.py`:

```python
import json
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parents[1] / "hooks"


def test_claude_settings_registers_both_hooks():
    data = json.loads((HOOKS_DIR / "claude-code-settings.example.json").read_text(encoding="utf-8"))
    hooks = data["hooks"]
    pre = json.dumps(hooks["PreToolUse"])
    stop = json.dumps(hooks["Stop"])
    assert "phase_guard.py" in pre
    assert "stop_guard.py" in stop
    assert "__e2e_harness_SCRIPTS__" in pre and "__e2e_harness_SCRIPTS__" in stop


def test_claude_pretooluse_matches_write_tools():
    data = json.loads((HOOKS_DIR / "claude-code-settings.example.json").read_text(encoding="utf-8"))
    matcher = data["hooks"]["PreToolUse"][0]["matcher"]
    for tool in ("Edit", "Write", "MultiEdit", "Bash"):
        assert tool in matcher


def test_opencode_plugin_calls_phase_guard():
    text = (HOOKS_DIR / "opencode-plugin.example.js").read_text(encoding="utf-8")
    assert "phase_guard.py" in text
    assert "tool.execute.before" in text
    assert "permissionDecision" in text
    assert "__e2e_harness_SCRIPTS__" in text
```

- [ ] **Step 2: 跑测试确�?fail**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_hook_examples.py -q`
Expected: FAIL (`FileNotFoundError`)

- [ ] **Step 3: 写两�?example**

Create `skills/e2e-dev-harness/hooks/claude-code-settings.example.json`:

```json
{
  "_comment": "e2e-dev-harness hook template. U6 installer rewrites __e2e_harness_SCRIPTS__ to the installed absolute scripts dir.",
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python __e2e_harness_SCRIPTS__/e2e_harness/adapters/hooks/phase_guard.py --repo . --hook-input -"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python __e2e_harness_SCRIPTS__/e2e_harness/adapters/hooks/stop_guard.py --repo . --hook-input -"
          }
        ]
      }
    ]
  }
}
```

Create `skills/e2e-dev-harness/hooks/opencode-plugin.example.js`:

```javascript
// e2e-dev-harness opencode plugin (example template).
// U6 installer rewrites __e2e_harness_SCRIPTS__ to the installed absolute scripts dir.
const { spawnSync } = require("child_process");

const PHASE_GUARD = "__e2e_harness_SCRIPTS__/e2e_harness/adapters/hooks/phase_guard.py";

module.exports = {
  "tool.execute.before": async (input, output) => {
    const payload = JSON.stringify({ tool_name: input.tool, tool_input: output.args });
    const res = spawnSync("python", [PHASE_GUARD, "--repo", ".", "--hook-input", "-"], {
      input: payload,
      encoding: "utf-8",
    });
    let parsed;
    try {
      parsed = JSON.parse(res.stdout || "{}");
    } catch (e) {
      return; // fail-open on parse error
    }
    const decision = (parsed.hookSpecificOutput || {}).permissionDecision;
    if (decision === "deny") {
      throw new Error((parsed.hookSpecificOutput || {}).permissionDecisionReason || "phase_guard denied this write");
    }
  },
};
```

- [ ] **Step 4: 跑测试确�?pass**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_hook_examples.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/hooks/claude-code-settings.example.json \
        skills/e2e-dev-harness/hooks/opencode-plugin.example.js \
        skills/e2e-dev-harness/tests/test_hook_examples.py
git commit -m "feat(e2e-dev-harness): U7 claude + opencode hook example configs"
```

---

## Task 8: e2e �?start �?越界�?�?gate 推进 �?放行

**Files:**
- Test: `skills/e2e-dev-harness/tests/test_phase_guard_e2e.py`

- [ ] **Step 1: �?e2e 测试**

Create `skills/e2e-dev-harness/tests/test_phase_guard_e2e.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

from e2e_harness.adapters.hooks import phase_guard as pg
from e2e_harness.adapters.evidence import command_evidence as ce

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness.py"


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def _make_artifact(repo: Path, phase: str, key: str) -> str:
    base = repo / "docs" / "agent-runs" / "art"
    base.mkdir(parents=True, exist_ok=True)
    if key in ("failing_tests", "passing_tests"):
        code = 1 if key == "failing_tests" else 0
        ev = ce.record_command(repo, f'"{sys.executable}" -c "import sys; sys.exit({code})"')
        f = base / f"{phase}-{key}.json"
        f.write_text(json.dumps(ev), encoding="utf-8")
    else:
        f = base / f"{phase}-{key}.md"
        f.write_text(f"# {phase} {key}\nreal evidence content\n", encoding="utf-8")
    return str(f.relative_to(repo))


def _code_write_hook(repo: Path) -> str:
    return json.dumps({"tool_name": "Write",
                       "tool_input": {"file_path": str(repo / "src" / "feature.py"),
                                      "content": "print('x')"}})


def test_phase_guard_blocks_early_then_allows_at_implemented(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    assert code == 0
    state_path = res["run_state"]

    # 1) Fresh run sits before IMPLEMENTED: a code write is denied.
    d = pg.decide(_code_write_hook(tmp_path), tmp_path, state_path)
    assert d["decision"] == "deny", d

    # 2) Drive the run via real gates until current_phase == IMPLEMENTED.
    reached_impl = False
    for _ in range(50):
        from e2e_harness.core import run_state
        if run_state.load(state_path)["current_phase"] == "IMPLEMENTED":
            reached_impl = True
            break
        code, nres = _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
        if nres.get("complete"):
            break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            rel = _make_artifact(tmp_path, phase, key)
            _run("submit", "--state", state_path, "--phase", phase,
                 "--key", key, "--path", rel, "--repo", str(tmp_path), cwd=tmp_path)
    assert reached_impl, "run never reached IMPLEMENTED"

    # 3) Same code write is now allowed at IMPLEMENTED.
    d = pg.decide(_code_write_hook(tmp_path), tmp_path, state_path)
    assert d["decision"] == "allow", d
```

- [ ] **Step 2: �?e2e 确认 pass**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/test_phase_guard_e2e.py -q`
Expected: PASS

> �?`current_phase` �?`next` 推进语义下不直接等于 `IMPLEMENTED`(例如 CLI 用中间态命�?,改判据为 `pipeline.can_write_code(run_state.load(state_path))` 为真�?break,并据此断言放行 —�?判定真相源始终是 `can_write_code`,非字符串�?
- [ ] **Step 3: 全套回归**

Run: `cd skills/e2e-dev-harness && python -m pytest tests/ -q`
Expected: PASS (�?176 + �?plan 新增,全绿)

- [ ] **Step 4: Commit**

```bash
git add skills/e2e-dev-harness/tests/test_phase_guard_e2e.py
git commit -m "test(e2e-dev-harness): U7 e2e phase-lock blocks then allows at IMPLEMENTED"
```

---

## 收尾 (plan 完成�?

- [ ] `cd skills/e2e-dev-harness && python -m pytest tests/ -q` 全绿
- [ ] `gitnexus_detect_changes({scope:"unstaged"})` 校验影响面仅限预�?symbol/flow
- [ ] `/code-review`(dispatch �?用内�?review 替代 subagent 两阶�?
- [ ] 更新 roadmap [2026-06-07-e2e-dev-harness-remaining-work-roadmap.md](2026-06-07-e2e-dev-harness-remaining-work-roadmap.md):�?U7 done;U6 "�?legacy" �?gated on U7 �?现已解锁;U6 hook 能力 "deferred to U7" �?"covered by U7"
- [ ] **�?*�?installer / 入口切换 / �?legacy �?全属 U6

---

## Self-Review 记录

- **Spec 覆盖:** §3.1 can_write_code+字段→T1;§3.1 内建标注→T3;validate 新字段→T2;§3.2 phase_guard(路径复用 T4 / 薄壳 T5)→T4+T5;§3.3 stop_guard→T6;§3.4 example configs→T7;§5 测试策略(can_write_code/phase_guard/stop_guard/installer-example/e2e)→T1/T5/T6/T7/T8。installer 真正安装 = U6,�?plan 只到 example(§6/§8 一�?�?- **YAGNI (§7):** require-active-run / session-checkpoint / codex+gemini / 冲突事实强制 �?均不实现;`decide` 在无 active run 时放�?显式落在 T5 `test_no_active_run_allows_code_write`)�?- **类型一�?** `decide(hook_text, repo, run_state_path) -> {"decision","reason"}`、`parse_hook_input -> (tool, paths, command)`、`can_write_code(state) -> bool`、`Phase.allows_code_write: bool` �?T1/T5/T6/T8 一�?`_emit` �?phase_guard 输出 PreToolUse 协议、在 stop_guard 输出 Stop 协议,两者签�?`(_emit(result: dict))` 一致但协议不同(各自测试锚定)�?- **循环依赖:** can_write_code �?pipeline.py(�?lifecycle.py),已在 File Structure 标注理由�?