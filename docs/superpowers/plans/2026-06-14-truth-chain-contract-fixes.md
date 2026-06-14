# Truth-chain / 契约一致性 5 修 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉 e2e-dev-harness 的 5 处契约/审计语义缝隙(strict 诱导降级、evidence under-claim 漏检、降级 reason 脱锚、活锁误删、文档失同步),全部 TDD、不破坏 761 passed 基线。

**Architecture:** 贯穿原则=**单一真相源**。D1/D3 把"同一事实的两处独立判断"收敛到权威处(bridge 盖 `degradation_available`、reason 只认被哈希的 JSON);D2 给 `detect_drift` 补 evidence 的 under-claim 对称分支;D4 用同机 pid 探活守护锁活性;D5 同步文档。

**Tech Stack:** Python 3(零运行期依赖)、pytest、stdlib(`os`/`socket`/`ctypes`/`json`)。源码在 `skills/e2e-dev-harness/scripts/e2e_harness/`,测试在 `skills/e2e-dev-harness/tests/`,`tests/conftest.py` 已把 `scripts/` 注入 sys.path。

设计依据:[2026-06-14-truth-chain-contract-fixes-design.md](../specs/2026-06-14-truth-chain-contract-fixes-design.md)

---

## Cross-cutting discipline(每个改代码的 Task 都做)

本项目受 GitNexus 索引,`CLAUDE.md` 是硬规则:

1. **编辑某 symbol 前**先 `gitnexus_impact({target: "<symbol>", direction: "upstream"})`,把 blast radius(直接 caller / 受影响 process / 风险级别)报出来;**HIGH/CRITICAL 必须先警示**再改。
2. **commit 前**先 `gitnexus_detect_changes({scope: "unstaged"})`,确认只命中预期 symbol/flow。
3. 每个 Task 末尾跑该 fix 的定向测试 + 收尾跑全量 `python -m pytest tests/ -q`,守住 761 passed。

> 所有 `pytest` / `git` 命令都假设当前目录在 `skills/e2e-dev-harness/`(`cd skills/e2e-dev-harness` 一次即可)。

---

## Task 0: 开工作分支 + 把设计 spec 纳入版本

当前在默认分支 `master` 且工作树已脏。先开分支,再把已落盘但未跟踪的设计 spec 作为分支首个提交(spec 随实现走,即设计阶段定的 option b)。

**Files:**
- Commit: `docs/superpowers/specs/2026-06-14-truth-chain-contract-fixes-design.md`(已存在,未跟踪)
- Commit: `docs/superpowers/plans/2026-06-14-truth-chain-contract-fixes.md`(本文件)

- [ ] **Step 1: 建分支**

```bash
git checkout -b fix/truth-chain-contract-fixes
```

- [ ] **Step 2: 提交设计文档与计划**

```bash
git add docs/superpowers/specs/2026-06-14-truth-chain-contract-fixes-design.md \
        docs/superpowers/plans/2026-06-14-truth-chain-contract-fixes.md
git commit -m "docs(e2e-harness): truth-chain contract fixes design + plan"
```

---

## Task 1: D1a — bridge 在 blocked binding 盖 `degradation_available`

**目标 symbol:** `e2e_harness.core.impact_bridge.ensure_assessment_for_planning`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/impact_bridge.py`(在 `_bind` 调用后,约 185 行)
- Test: `skills/e2e-dev-harness/tests/test_impact_bridge.py`

- [ ] **Step 1: 写失败测试**(追加到 `test_impact_bridge.py` 末尾;`_state`/`_contract`/`_FakeProvider`/`_blocked_artifact` 均为该文件现有 helper)

```python
def test_blocked_binding_marks_degradation_available_in_auto(tmp_path):
    st = _state(tmp_path, "auto", _contract(tmp_path))
    impact_bridge.ensure_assessment_for_planning(
        st, str(tmp_path), provider=_FakeProvider(_blocked_artifact()))
    assert st["impact_assessment"]["status"] == "blocked"
    assert st["impact_assessment"]["degradation_available"] is True


def test_blocked_binding_marks_no_degradation_in_strict(tmp_path):
    st = _state(tmp_path, "strict", _contract(tmp_path))
    impact_bridge.ensure_assessment_for_planning(
        st, str(tmp_path), provider=_FakeProvider(_blocked_artifact()))
    assert st["impact_assessment"]["status"] == "blocked"
    assert st["impact_assessment"]["degradation_available"] is False
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd skills/e2e-dev-harness
python -m pytest tests/test_impact_bridge.py::test_blocked_binding_marks_no_degradation_in_strict tests/test_impact_bridge.py::test_blocked_binding_marks_degradation_available_in_auto -v
```
Expected: FAIL —— `KeyError: 'degradation_available'`(字段尚不存在)。

- [ ] **Step 3: 编辑前跑 impact**

```
gitnexus_impact({target: "ensure_assessment_for_planning", direction: "upstream"})
```
报出 blast radius;HIGH/CRITICAL 先警示。

- [ ] **Step 4: 实现**(在 `impact_bridge.py` 的 `_bind(...)` 调用与 `if artifact["status"] == "degraded" and approval:` 之间插入)

把这段:
```python
    path = _write_artifact(state, repo_root, artifact)
    _bind(state, path=path, repo_root=repo_root, contract_sha=contract_sha,
          artifact=artifact, required=True)
    if artifact["status"] == "degraded" and approval:
        state["impact_assessment"]["approval_sha256"] = approval["sha256"]
```
改成:
```python
    path = _write_artifact(state, repo_root, artifact)
    _bind(state, path=path, repo_root=repo_root, contract_sha=contract_sha,
          artifact=artifact, required=True)
    if artifact["status"] == "blocked":
        # Single source of truth for "can a recorded approval degrade this?": the
        # binding self-describes it so `next` reads the policy instead of re-deriving
        # mode (the drift that let strict runs advertise a no-op approval).
        state["impact_assessment"]["degradation_available"] = (mode != "strict")
    if artifact["status"] == "degraded" and approval:
        state["impact_assessment"]["approval_sha256"] = approval["sha256"]
```

- [ ] **Step 5: 跑测试确认通过**

```bash
python -m pytest tests/test_impact_bridge.py -v
```
Expected: PASS(含两个新测试 + 既有 `test_strict_mode_blocks_instead_of_degrading` 等不回归)。

- [ ] **Step 6: commit 前 detect_changes**

```
gitnexus_detect_changes({scope: "unstaged"})
```
确认只命中 `impact_bridge` 评估流程。

- [ ] **Step 7: 提交**

```bash
git add scripts/e2e_harness/core/impact_bridge.py tests/test_impact_bridge.py
git commit -m "fix(e2e-harness): stamp degradation_available on blocked impact binding"
```

---

## Task 2: D1b — `next` 数据驱动,strict 不再吐 `approve_with`

**目标 symbol:** `e2e_harness.cli.commands.next.run`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/next.py:48-56`
- Test: `skills/e2e-dev-harness/tests/test_impact_e2e.py`

- [ ] **Step 1: 写失败测试**(追加到 `test_impact_e2e.py` 末尾;结构镜像同文件现有的 `test_impact_degradation_flow`,但 strict 且止于 blocked 断言)

```python
def test_impact_strict_blocked_offers_no_degradation(tmp_path, monkeypatch):
    """strict + blocked:next 不得宣传 bridge 会拒绝的降级出路——
    degradation_available 为 False 且无 approve_with。"""
    monkeypatch.setattr(
        "e2e_harness.adapters.impact.gitnexus.GitNexusImpactProvider", _FakeProvider)
    _FakeProvider.result = _blocked()
    repo = tmp_path

    code, res = start_cmd.run(_start_args(tmp_path, impact_mode="strict"))
    assert code == 0
    state_path = Path(res["run_state"])
    run_dir = state_path.parent

    _next(tmp_path, state_path)  # -> CLARIFIED (needs evidence)
    clar = _write(repo, run_dir, "clarification.md", "# clarified\n")
    contract = _write(repo, run_dir, "acceptance-contract.json",
                      _contract(["checkout_handler"], marker="v1"))
    _submit(tmp_path, state_path, "CLARIFIED", "clarification", clar)
    _submit(tmp_path, state_path, "CLARIFIED", "acceptance_contract", contract)

    _code, nres = _next(tmp_path, state_path)
    assert nres["blocked_phase"] == "CLARIFIED"
    assert nres["impact"]["status"] == "blocked"
    assert nres["impact"]["degradation_available"] is False
    assert "approve_with" not in nres["impact"]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/test_impact_e2e.py::test_impact_strict_blocked_offers_no_degradation -v
```
Expected: FAIL —— 现 `next.py` 硬编码 `degradation_available: True` 且带 `approve_with`,故 `is False` 与 `not in` 两断言失败。

- [ ] **Step 3: 编辑前跑 impact**

```
gitnexus_impact({target: "run", direction: "upstream", file_path: "skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/next.py"})
```

- [ ] **Step 4: 实现**(把 `next.py` 的 impact 块替换为数据驱动版)

把这段:
```python
        binding = state.get("impact_assessment")
        if binding and binding.get("status") == "blocked":
            res["impact"] = {
                "status": "blocked",
                "degradation_available": True,
                "approve_with": "approve-impact-degradation",
                "message": ("GitNexus impact analysis could not be verified. Resolve the "
                            "open questions, or ask the user to approve degradation."),
            }
```
改成:
```python
        # strict 模式无降级路径(impact_bridge 拥有该策略并把 degradation_available
        # 盖在 binding 上);next 纯数据驱动,绝不宣传 bridge 会拒绝的 approval。
        binding = state.get("impact_assessment")
        if binding and binding.get("status") == "blocked":
            if binding.get("degradation_available", True):
                res["impact"] = {
                    "status": "blocked",
                    "degradation_available": True,
                    "approve_with": "approve-impact-degradation",
                    "message": ("GitNexus impact analysis could not be verified. Resolve "
                                "the open questions, or ask the user to approve degradation."),
                }
            else:
                res["impact"] = {
                    "status": "blocked",
                    "degradation_available": False,
                    "message": ("strict 模式无降级路径:请解决 IQ-* 问题"
                                "(修订验收契约触发重评)。"),
                }
```

- [ ] **Step 5: 跑测试确认通过**

```bash
python -m pytest tests/test_impact_e2e.py -v
```
Expected: PASS（新 strict 测试 + 既有 `test_impact_degradation_flow` 的 `degradation_available is True` 不回归——auto binding 默认带 True）。

- [ ] **Step 6: commit 前 detect_changes**

```
gitnexus_detect_changes({scope: "unstaged"})
```

- [ ] **Step 7: 提交**

```bash
git add scripts/e2e_harness/cli/commands/next.py tests/test_impact_e2e.py
git commit -m "fix(e2e-harness): next reads degradation_available; strict shows no approve path"
```

---

## Task 3: D3 + D5 — 降级 reason 只认 JSON;同步 SKILL 文档(同一提交)

D3 与 D5 同属 `approve-impact-degradation` 契约面,一起进,避免"文档已改 schema 而 `--reason` 还在"的不一致窗口。

**目标 symbol:** `e2e_harness.cli.commands.approve_impact_degradation.run`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/approve_impact_degradation.py:58`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/main.py:108`（删 `--reason`）
- Modify: `skills/e2e-dev-harness/SKILL.md:37`
- Test: `skills/e2e-dev-harness/tests/test_approve_impact_degradation.py`

- [ ] **Step 1: 写失败测试**(追加到 `test_approve_impact_degradation.py` 末尾)

```python
def test_reason_comes_from_hashed_json_not_cli_override(tmp_path):
    """降级 reason 必须来自被 sha256 锚定的 JSON,而非命令行覆盖,
    否则审计内容脱锚(finding P2)。"""
    run_dir = tmp_path / "docs" / "agent-runs" / "r1"
    run_dir.mkdir(parents=True)
    state_path = run_dir / "run-state.json"
    run_state.save(state_path, run_state.new_run_state(
        "r1", "f", "req", tier="critical", pipeline="critical"))
    approval = run_dir / "gitnexus-degradation.json"
    approval.write_text(json.dumps({
        "schema": "e2e-dev-harness.impact-degradation-approval.v1",
        "approval": "user-approved",
        "reason": "GitNexus unavailable",
        "fallback_evidence": ["manual review"],
    }), encoding="utf-8")
    # 即便 CLI 仍带 reason(旧调用),也必须被忽略,JSON 内 reason 为准。
    args = SimpleNamespace(state=str(state_path), approval=str(approval),
                           reason="OVERRIDE that must be ignored")
    code, result = cmd.run(args)
    assert code == 0
    block = run_state.load(state_path)["approvals"]["impact_degradation"]
    assert block["reason"] == "GitNexus unavailable"
    assert len(block["sha256"]) == 64
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/test_approve_impact_degradation.py::test_reason_comes_from_hashed_json_not_cli_override -v
```
Expected: FAIL —— 现实现 `args.reason or approval_obj["reason"]` 取了 `"OVERRIDE..."`,断言 `== "GitNexus unavailable"` 失败。

- [ ] **Step 3: 编辑前跑 impact**

```
gitnexus_impact({target: "run", direction: "upstream", file_path: "skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/approve_impact_degradation.py"})
```

- [ ] **Step 4a: 实现 — reason 只认 JSON**(`approve_impact_degradation.py` `_record` 内)

把:
```python
            "reason": getattr(args, "reason", None) or approval_obj["reason"],
```
改成:
```python
            "reason": approval_obj["reason"],
```

- [ ] **Step 4b: 实现 — 从 argparse 删 `--reason`**(`main.py` 的 `approve-impact-degradation` 子解析器)

把:
```python
    ai = sub.add_parser("approve-impact-degradation")
    ai.add_argument("--state", required=True)
    ai.add_argument("--approval", required=True)
    ai.add_argument("--reason", default=None)
```
改成:
```python
    ai = sub.add_parser("approve-impact-degradation")
    ai.add_argument("--state", required=True)
    ai.add_argument("--approval", required=True)
```

- [ ] **Step 4c: 实现 — D5 同步 SKILL.md**(`SKILL.md` 第 37 行)

把:
```
e2e-harness approve-impact-degradation --state <run-state> --approval <file.md>  # 记录降级信任锚
```
改成:
```
e2e-harness approve-impact-degradation --state <run-state> --approval <approval.json>  # 记录降级信任锚
# approval.json (impact-degradation-approval.v1): {"schema":"e2e-dev-harness.impact-degradation-approval.v1","approval":"user-approved","reason":"...","fallback_evidence":["..."]}
```

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

```bash
python -m pytest tests/test_approve_impact_degradation.py -v
python -m pytest tests/ -q
```
Expected: 定向 PASS;全量仍 green(既有 `test_records_run_state_approval` 不断言 reason,故不回归;`test_impact_e2e.py` 直接 `.run(SimpleNamespace(..., reason=...))`,cmd 忽略该属性,仍 PASS)。

- [ ] **Step 6: commit 前 detect_changes + 手搜外部 `--reason` 依赖**

```
gitnexus_detect_changes({scope: "unstaged"})
```
并在**消费方仓库 / CI 脚本**手 grep `--reason`(本仓已确认无依赖;移除是 CLI 契约收缩,PR 描述须点明)。

- [ ] **Step 7: 单次提交(D3+D5 一起)**

```bash
git add scripts/e2e_harness/cli/commands/approve_impact_degradation.py \
        scripts/e2e_harness/cli/main.py \
        tests/test_approve_impact_degradation.py \
        SKILL.md
git commit -m "fix(e2e-harness): anchor degradation reason to approval JSON; sync SKILL doc to JSON contract"
```

---

## Task 4: D2 — `detect_drift` 补 evidence under-claim 对称分支

**目标 symbol:** `e2e_harness.core.state_store.detect_drift`

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/state_store.py:164-168`
- Test: `skills/e2e-dev-harness/tests/test_event_log.py`

- [ ] **Step 1: 写测试**(追加到 `test_event_log.py` 末尾——一个 red 驱动 + 一个 established-gate 守卫)

```python
def test_detect_drift_catches_dropped_evidence_keys_under_claim(tmp_path):
    """Evidence under-claim(与 dispatch under-claim 对称):evidence.keys 事件被
    截断,replay 对该 phase 的 evidence 沉默,而 run-state 仍带(phantom 注入的)
    keys。dispatch 与 current_phase 都对齐,孤立出 conflict-only 检查放过的缝隙。"""
    forged_events = [
        {"type": "run.started", "run_id": "r1"},
        {"type": "phase.submitted", "run_id": "r1", "phase": "IMPLEMENTED"},
        {"type": "gate.passed", "run_id": "r1", "phase": "IMPLEMENTED"},
        # evidence.keys for IMPLEMENTED dropped by the truncation
    ]
    real = {"run_id": "r1", "current_phase": "IMPLEMENTED",
            "phases": {"IMPLEMENTED": {"dispatch": "done", "evidence": {
                "passing_tests": {"path": "p.json"},
                "phantom": {"path": "evil.json"},
            }}}}
    ok, reason = state_store.detect_drift(forged_events, real)
    assert ok is False
    assert reason == "drift:phases.IMPLEMENTED.evidence_keys"


def test_detect_drift_evidence_under_claim_silent_on_unestablished_log(tmp_path):
    """守卫 established 门:空(未建立)投影即使 run-state 已带含 evidence 的 phase,
    也不得误报——尚无记录可'落后'。"""
    real = {"run_id": "r1", "current_phase": "CREATED",
            "phases": {"IMPLEMENTED": {"evidence": {"passing_tests": {"path": "p.json"}}}}}
    ok, reason = state_store.detect_drift([], real)
    assert ok is True
    assert reason is None
```

- [ ] **Step 2: 跑测试确认 red 驱动失败**

```bash
python -m pytest tests/test_event_log.py::test_detect_drift_catches_dropped_evidence_keys_under_claim tests/test_event_log.py::test_detect_drift_evidence_under_claim_silent_on_unestablished_log -v
```
Expected: 第一个 FAIL（现 `(True, None)`——投影无 evidence 时整段跳过比对);第二个 PASS（established 门已护,作回归守卫)。

- [ ] **Step 3: 编辑前跑 impact**

```
gitnexus_impact({target: "detect_drift", direction: "upstream"})
```

- [ ] **Step 4: 实现**(`state_store.py` 把 evidence 比对块加上 under-claim 分支)

把:
```python
        if "evidence" in proj_rec:
            proj_keys = set((proj_rec.get("evidence") or {}).keys())
            real_keys = set((real_rec.get("evidence") or {}).keys())
            if proj_keys != real_keys:
                return False, f"drift:phases.{name}.evidence_keys"
```
改成:
```python
        if "evidence" in proj_rec:
            proj_keys = set((proj_rec.get("evidence") or {}).keys())
            real_keys = set((real_rec.get("evidence") or {}).keys())
            if proj_keys != real_keys:
                return False, f"drift:phases.{name}.evidence_keys"
        elif established and "evidence" in real_rec:
            # UNDER-CLAIM:截断后的日志对 run-state 仍断言的 evidence 沉默
            # (与上方 dispatch/blocker 的 under-claim 对称)。
            return False, f"drift:phases.{name}.evidence_keys"
```

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

```bash
python -m pytest tests/test_event_log.py -v
python -m pytest tests/ -q
```
Expected: 全 PASS。重点确认既有 `test_detect_drift_clean_when_evidence_key_projection_matches`、`test_detect_drift_silent_on_empty_log_does_not_false_positive` 不回归。

- [ ] **Step 6: commit 前 detect_changes**

```
gitnexus_detect_changes({scope: "unstaged"})
```

- [ ] **Step 7: 提交**

```bash
git add scripts/e2e_harness/core/state_store.py tests/test_event_log.py
git commit -m "fix(e2e-harness): detect evidence-keys under-claim drift on truncated log"
```

---

## Task 5: D4 —（可推迟）锁 staleness 加同机 pid 探活

> **优先级最低 / 可推迟。** 唯一改 `_lock` 语义且需跨平台 pid 探活。若本轮不做,**在本 PR 开一个 issue 跟踪**,免遗忘。下面给完整可落地版本。

**目标 symbol:** `e2e_harness.core.run_state._lock_is_stale`(新增 helper `_pid_alive`)

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/run_state.py:108-112`(+ 新增 `_pid_alive`)
- Test: `skills/e2e-dev-harness/tests/test_run_state.py`

- [ ] **Step 1: 写失败测试**(追加到 `test_run_state.py` 末尾;文件已 `import os/time/json`,新测试块加 `import socket`)

```python
import socket as _socket_for_lock_tests


def test_lock_not_stale_when_holder_pid_alive(tmp_path, monkeypatch):
    """同机且 pid 存活的锁,即使 mtime 超期也绝不判 stale——保护卡在临界区的活持有者。"""
    lock = tmp_path / "run-state.json.lock"
    lock.write_text(json.dumps({"pid": os.getpid(),
                                "hostname": _socket_for_lock_tests.gethostname(),
                                "timestamp": "now"}), encoding="utf-8")
    old = time.time() - 10_000
    os.utime(lock, (old, old))
    monkeypatch.setattr(run_state, "_LOCK_STALE_S", 0.01, raising=False)
    assert run_state._lock_is_stale(lock) is False


def test_lock_stale_when_holder_pid_dead_and_mtime_old(tmp_path, monkeypatch):
    """同机但 pid 已死且 mtime 超期 → stale(可回收)。"""
    lock = tmp_path / "run-state.json.lock"
    lock.write_text(json.dumps({"pid": 999999,
                                "hostname": _socket_for_lock_tests.gethostname(),
                                "timestamp": "old"}), encoding="utf-8")
    old = time.time() - 10_000
    os.utime(lock, (old, old))
    monkeypatch.setattr(run_state, "_LOCK_STALE_S", 0.01, raising=False)
    assert run_state._lock_is_stale(lock) is True


def test_lock_cross_host_falls_back_to_mtime(tmp_path, monkeypatch):
    """跨主机无法验活 → 退回 mtime backstop(超期即 stale)。"""
    lock = tmp_path / "run-state.json.lock"
    lock.write_text(json.dumps({"pid": os.getpid(), "hostname": "some-other-host",
                                "timestamp": "old"}), encoding="utf-8")
    old = time.time() - 10_000
    os.utime(lock, (old, old))
    monkeypatch.setattr(run_state, "_LOCK_STALE_S", 0.01, raising=False)
    assert run_state._lock_is_stale(lock) is True
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/test_run_state.py::test_lock_not_stale_when_holder_pid_alive -v
```
Expected: FAIL —— 现 `_lock_is_stale` 只看 mtime(超期→True),活锁被判 stale,断言 `is False` 失败。

- [ ] **Step 3: 编辑前跑 impact**

```
gitnexus_impact({target: "_lock_is_stale", direction: "upstream"})
```

- [ ] **Step 4: 实现**(`run_state.py` 替换 `_lock_is_stale`,并在其上方新增 `_pid_alive`)

把:
```python
def _lock_is_stale(lock: Path) -> bool:
    try:
        return (time.time() - lock.stat().st_mtime) > _LOCK_STALE_S
    except OSError:
        return False
```
改成:
```python
def _pid_alive(pid) -> bool:
    """Best-effort 跨平台存活判断。不确定一律返回 True(偏向不回收可能仍活的锁;
    真死锁仍由 mtime backstop 兜底),所以绝不会把活锁判反。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if pid <= 0:
        return True
    if sys.platform == "win32":
        try:
            import ctypes
            SYNCHRONIZE = 0x00100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:  # noqa: BLE001 — 不确定即视为存活
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # 存在但非本进程所有
    except OSError:
        return True


def _lock_is_stale(lock: Path) -> bool:
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if isinstance(payload, dict) and payload.get("hostname") == socket.gethostname():
        if _pid_alive(payload.get("pid")):
            return False            # 本机活锁 → 永不回收
    try:
        return (time.time() - lock.stat().st_mtime) > _LOCK_STALE_S
    except OSError:
        return False
```
（`sys`/`os`/`socket`/`json`/`time` 均已在 `run_state.py` 顶部 import。)

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

```bash
python -m pytest tests/test_run_state.py -v
python -m pytest tests/ -q
```
Expected: 全 PASS。重点确认既有 `test_mutate_recovers_stale_lock_file`(pid=999999、hostname="old"≠本机 → 走 mtime → 仍回收)不回归。

- [ ] **Step 6: commit 前 detect_changes**

```
gitnexus_detect_changes({scope: "unstaged"})
```

- [ ] **Step 7: 提交**

```bash
git add scripts/e2e_harness/core/run_state.py tests/test_run_state.py
git commit -m "fix(e2e-harness): guard run-state lock staleness with same-host pid liveness"
```

---

## 收尾

- [ ] **全量回归**:`cd skills/e2e-dev-harness && python -m pytest tests/ -q` —— 应为 761 + 新增用例全 PASS。
- [ ] **最终 detect_changes**:`gitnexus_detect_changes({scope: "all"})` 复核整体改动面,确认只命中 impact/审计/锁/文档预期 flow。
- [ ] 若 Task 5 推迟:确认已开 issue 跟踪 D4。
- [ ] 按 `superpowers:finishing-a-development-branch` 决定 merge / PR。

## Self-Review(写计划者自检)

- **Spec coverage**:D1(Task 1+2)、D2(Task 4)、D3(Task 3)、D4(Task 5)、D5(Task 3 内)—— 5 修全有任务,顺序 = spec §6(D1 → D3+D5 → D2 → D4)。✅
- **Placeholder scan**:无 TBD/TODO;每个代码步都给了完整改前/改后代码块与精确命令、预期输出。✅
- **Type/名一致**:贯穿 `degradation_available`(bool)、`_pid_alive`、`_lock_is_stale`、`detect_drift` 命名前后一致;测试 helper 全部取自已读取的对应测试文件。✅
- **迁移代价**:D1 老 binding 默认 True 直到 contract hash 重建——已在 spec §4 记录,实现期 PR 描述须点明(Task 1 不阻塞,属已知可接受代价)。✅
