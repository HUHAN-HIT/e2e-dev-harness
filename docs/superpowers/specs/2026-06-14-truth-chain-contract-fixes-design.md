# Truth-chain / 契约一致性 5 修 — 设计 Spec

- **日期**: 2026-06-14
- **状态**: 已批准设计,待转 writing-plans
- **范围**: `skills/e2e-dev-harness` —— impact 评估契约、event-log 漂移检测、降级审计锚、run-state 锁、SKILL 文档
- **基线**: 全量测试 761 passed;本次 5 处缺陷均为现有测试未覆盖的契约/审计语义缝隙

## 1. 问题背景

来自一次 review 的 5 条 finding(均已逐行核实成立):

| # | 严重度 | 位置 | 缺陷 |
|---|---|---|---|
| 1 | P1 | `cli/commands/next.py:48` | strict 模式仍向协调器吐 `degradation_available: true` + `approve_with`,但 `core/impact_bridge.py:151/179` 已定义 strict 永不降级 → 诱导用户走永不生效的 approval 流程 |
| 2 | P1 | `core/state_store.py:164` | `detect_drift` 仅在投影**已有** evidence 时比对 evidence key set;投影沉默而 run-state 含 phantom evidence 时漏检(under-claim 缝隙) |
| 3 | P2 | `cli/commands/approve_impact_degradation.py:58` | `reason` 优先取 `args.reason`,但 `sha256` 只锚定 JSON 文件 → 降级产物 reason 可脱离哈希锚定 |
| 4 | P2(偏低) | `core/run_state.py:108` | 锁 payload 写了 pid 却不用,stale 纯看 mtime、持锁不刷新 → 临界区卡顿 >300s 时活锁可能被第二进程误删 |
| 5 | P3 | `SKILL.md:37` | 文档仍写 `--approval <file.md>`,命令已只收 `impact-degradation-approval.v1` JSON → 按文档生成 markdown 会被拒 |

## 2. 设计原则

#1/#2/#3 同源于一种病:**同一事实由两处独立判断,产生漂移**。统一原则为**单一真相源**——事实在权威处落定一次,下游只读不重算。#4 是锁活性判定的健壮化,#5 是文档同步。

## 3. 目标 / 非目标

**目标**
- strict run 的契约层不再暗示一个无效的降级出路。
- evidence key 的 under-claim 漂移与 dispatch/blocker 对称可检。
- 降级 reason 完全由被哈希的审计产物锚定。
- 活锁不因临界区卡顿被误删(D4,可推迟)。
- 文档与命令实际契约一致。

**非目标**
- 不引入自动降级(降级仍是人类决定)。
- 不重写 event-log 写路径/链愈合(Phase 1 之外)。
- 不改 `impact` mode 的三态语义(off/auto/strict)。
- 不做锁的心跳后台线程(D4 采用 pid 探活而非心跳)。

## 4. 逐修设计

### D1 — strict 不再诱导降级(让 binding 自描述)

**根因**:"能否降级"被 bridge(看 `mode`)与 `next`(只看 `status`)两处独立判断。修复把该事实落到 binding,`next` 只读。

**改动**
1. `core/impact_bridge.py` —— 在写出 blocked binding 后(`_bind` 调用之后,约 185 行的 `reasons` 分支内)盖字段:
   ```python
   if artifact["status"] == "blocked":
       state["impact_assessment"]["degradation_available"] = (mode != "strict")
   ```
   - 覆盖所有"新建 blocked binding"路径(当前 178–191)。
   - idempotent 复用分支(当前 145–156)与 strict 早退(151–152)不重建 binding,自动继承首建时盖的字段。
   - `mode == "off"` 早返回 None,永无 blocked binding,不受影响。
2. `cli/commands/next.py:48-56` —— 数据驱动:
   ```python
   if binding and binding.get("status") == "blocked":
       can_degrade = binding.get("degradation_available", True)
       if can_degrade:
           res["impact"] = {
               "status": "blocked",
               "degradation_available": True,
               "approve_with": "approve-impact-degradation",
               "message": "GitNexus impact analysis could not be verified. Resolve the open questions, or ask the user to approve degradation.",
           }
       else:
           res["impact"] = {
               "status": "blocked",
               "degradation_available": False,
               "message": "strict 模式无降级路径:请解决 IQ-* 问题(修订验收契约触发重评)。",
           }
   ```
   strict 下不再输出 `approve_with`。

**不变量**:`degradation_available` 只由 bridge 写、`next` 只读;auto→True,strict→False,与 `strict_mode_no_degrade` 同源。

**迁移代价(已知、可接受)**:字段写在 binding dict 上,`next` 用 `binding.get("degradation_available", True)` 兜底。升级前已存在的 **strict-mode blocked binding** 缺该字段、兜底为 True,会继续误导,**直到验收契约 hash 变更触发该 binding 重建**才纠正。这是可接受的迁移代价(strict 在途 run 极少,且重评是常规动作),实现期须在 PR 描述点明。

> 备选(未采纳):把字段写进 `_bind` 内部的 binding dict 让 schema 自描述,代价是 `_bind` 多收一个 `mode` 参数。现方案可读性更好,但隐含"谁负责盖字段"的契约——实现时务必让 bridge 是唯一写入点。

### D2 — evidence under-claim 对称分支

**根因**:dispatch/blocker 有 under-claim 检测(`established and field in real_rec and field not in proj_rec`),evidence 漏了。

**改动**:`core/state_store.py:164-168` 重构:
```python
proj_has_ev = "evidence" in proj_rec
if proj_has_ev:
    proj_keys = set((proj_rec.get("evidence") or {}).keys())
    real_keys = set((real_rec.get("evidence") or {}).keys())
    if proj_keys != real_keys:
        return False, f"drift:phases.{name}.evidence_keys"
elif established and "evidence" in real_rec:          # 新增:投影沉默而 run-state 断言 → under-claim
    return False, f"drift:phases.{name}.evidence_keys"
```

**不会误报的依据**(设计不变量背书):
- `events_path_if_active`(`run_state.py:64`)让 emission **一次定生死、绝不中途 bootstrap**。
- `derive_events`(`state_store.py:79`)在每次 evidence key-set 变化都发 `evidence.keys` 事件。
- 故健康日志的投影必能重建 evidence;新分支只在**截断**(evidence.keys 被丢)时触发。`established` 门挡住"尚未记录"的空投影,不构成漂移。

### D3 — degradation reason 只认被哈希的 JSON

**根因**:`sha256` 锚定 JSON 文件,但 `reason` 可被 `--reason` 覆盖 → 审计内容脱锚。

**决定(抉择 A → A1)**:reason 唯一来自被哈希产物;移除 `--reason` CLI 参数。

**改动**
1. `cli/commands/approve_impact_degradation.py:58` —— `"reason": approval_obj["reason"]`(去掉 `getattr(args, "reason", None) or`)。
2. `cli/main.py:108` —— 删除 `ai.add_argument("--reason", default=None)`。
3. loader 已强制 JSON 内 `reason` 非空(`:34`),故移除后无信息缺失。

**不变量**:`state.approvals.impact_degradation.sha256` 锚定的文件,其 `reason` 即下游 `_degrade`(`impact_bridge.py:125`)写入降级产物的 reason —— 完全同一来源。

### D4 — 活锁保护:stale 判定加 pid 存活(排最后,可推迟)

**根因**:payload 写了 pid 却不用;stale 纯看 mtime、持锁不刷新 → 卡顿 >300s 的活锁会被误删并发写 run-state。

**改动**:`core/run_state.py:108` `_lock_is_stale` 升级为"**同机活进程绝不判 stale**,其余退回 mtime backstop":
```python
def _lock_is_stale(lock: Path) -> bool:
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
        if (payload.get("hostname") == socket.gethostname()
                and _pid_alive(payload.get("pid"))):
            return False                                   # 本机活锁 → 永不回收
    except (OSError, ValueError):
        pass                                               # payload 不可读 → 退回 mtime
    try:
        return (time.time() - lock.stat().st_mtime) > _LOCK_STALE_S
    except OSError:
        return False
```
`_pid_alive(pid)` 跨平台、**best-effort**:
- POSIX:`os.kill(pid, 0)` —— 成功或 `EPERM`(活但非本进程)视为存活,`ESRCH` 视为已死。
- Windows:`ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)`,句柄非 0 视为存活。
- 任何异常/不确定 → 当作"存活"(偏向不删,最坏退化成今天的 mtime 行为)。
- 跨主机无法验活,仍用 300s mtime 兜底。

**优先级**:唯一改 `_lock` 语义且需跨平台 pid 探活,概率最低,收益比偏低。排在最后实现,可作为独立 follow-up 推迟。

### D5 — 文档 `<file.md>` → JSON

`SKILL.md:37` `--approval <file.md>` 改为 `--approval <approval.json>`,并补一行最小 schema 字段示例(`schema` / `approval: "user-approved"` / `reason` / `fallback_evidence` 或 `compensating_evidence`)。纯文档,无测试。

## 5. 测试策略(TDD:先红后绿)

| 修 | 红测要点 | 文件 |
|---|---|---|
| D1 | strict+blocked binding → `degradation_available=False` 且无 `approve_with`;auto+blocked → True 带 `approve_with`;bridge 确实在 blocked binding 盖字段 | `tests/test_impact_bridge.py`、`tests/test_cli_e2e.py`(next) |
| D2 | (a) 截断 evidence.keys + phantom real evidence → `(False,"drift:phases.X.evidence_keys")`;(b) 健康全链 → `(True,None)`;(c) 空/未 established 投影 → 不误报 | `tests/test_event_log.py` |
| D3 | 仅 JSON 提供 reason 时正常记录;无 `--reason` 参数后 CLI 解析仍成功;记录与降级产物 reason 同源于 JSON | `tests/test_approve_impact_degradation.py` |
| D4 | 同机活 pid 即使 mtime 超期也非 stale;死 pid + 超期 → stale;跨主机超期 → stale;payload 不可读 → 退回 mtime | `tests/test_run_state.py` |

每条改前按 `CLAUDE.md` 跑 `gitnexus_impact`(报 blast radius),改后跑 `gitnexus_detect_changes` + 全量测试,守住 761 passed 基线。

## 6. 实现顺序

1. **D1**(strict 提示;next/impact binding 这一处,低逻辑风险,先拿下)
2. **D3 + D5 同一提交**(同属 `approve-impact-degradation` 契约面:移除 `--reason` 与修正 SKILL 文档须一起进,否则 SKILL.md 已改 schema 而 `--reason` 还在,文档/CLI 短暂不一致)
3. **D2**(最谨慎:先把 truncate / 健康 / 未-established 三类红测立起来再补分支)
4. **D4**(排最后;可推迟为独立 follow-up,但即便推迟也在 D1–D3 的 PR 里开一个 issue 跟踪,免得遗忘)

## 7. 风险

- **D2 误报风险**:已由 emission "一次定生死" + "每次 key 变化发事件"两个不变量排除;红测须**同时**写死 (b) 健康全链 → 不漂移、(c) 投影未 established(evidence 事件尚未追上的合法起步窗口)→ 不误报 两个用例,缺一不可——`established` 门(run_id OR current_phase OR phases)是 (c) 的守卫。
- **D3 兼容性**:移除 `--reason` 是 CLI 契约收缩,loader 强制 JSON reason,无功能缺失。依赖核对分两层:
  - **本仓已确认无依赖**:`tests/test_approve_impact_degradation.py` 用 `SimpleNamespace(...)` 直接构造 args、不走 argparse,移除条目不影响测试;仓内无其他 `--reason` 调用点。
  - **实现期须手搜消费方**:仓库外的 coordinator 脚本 / CI 可能在调 `--reason`,移除前需在业务仓库 grep 确认,并在 PR 描述点明此收缩。
- **D4 跨平台**:`_pid_alive` 须在 win32 与 POSIX 都 best-effort 且"不确定即存活",避免把锁活性判反。

## 8. 范围外

- event-log 链愈合 / 中途 bootstrap emission。
- 锁的后台心跳线程。
- impact mode 三态语义变更。
