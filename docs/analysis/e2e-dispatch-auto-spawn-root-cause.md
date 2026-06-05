# e2e-dev-harness：澄清阶段无法自动派发子 Agent —— 根因与优化方案

- **日期**：2026-06-04
- **范围**：`skills/e2e-dev-harness` 派发链路（dispatch / next / session-checkpoint / runtime-hook）
- **现象**：工程处于澄清阶段，harness 处于 `manual-dispatch`，无法自动 spawn subagent
- **结论**：非单点 bug，而是「长隐式前置链 + 静默降级 + 失败信息分散」三个设计问题叠加

---

## 0. 修复状态（2026-06-05）

本文件第 1-9 节记录的是修复前根因快照。对应修复已分批落地：

- `ba68de7`：hook 缺失 / generic runtime 不再静默降级为 manual，dispatch 返回显式 blocker 与 `install_hooks` 单步修复指引；显式 `--runtime manual` 仍保留手动出口。
- `3948171`：未知 runtime fallback 暴露 `warning` / `unknown_runtime` / `fallback_runtime`，`runtime-capabilities` 输出 `warnings`。
- `b8486d0`：`doctor` 输出 bootstrap guide：`start -> install_hooks -> next -> dispatch-beat` 与 `next_single_action`。
- `b8e0867`：`skills/e2e-dev-harness/SKILL.md` 写明 hook bootstrap 顺序和 dispatch hook blocking 语义。
- `42b4f53`：提交本根因分析文档和 GitNexus 索引元数据更新。

修复后还发现已安装 skill 副本曾落后于仓库源码：`C:\Users\14907\.codex\skills\e2e-dev-harness`、`C:\Users\14907\.claude\skills\e2e-dev-harness`、`C:\Users\14907\.agents\skills\e2e-dev-harness` 仍含旧 `SKILL.md` / dispatch 脚本。已执行：

```powershell
node tools\install-e2e-dev-harness.mjs --sync --yes --json
```

安装器已备份旧副本，并同步三个 runtime 目标。同步后关键文件（`SKILL.md`、`coordinator_flow.py`、`preflight.py`、`runtime_adapters.py`、`harness_doctor.py`、`e2e_harness/engine/dispatch_engine.py`）与仓库版本 SHA256 一致；从安装副本实跑 `runtime-capabilities --runtime bogus --json` 可见 unknown runtime warning，实跑 `doctor --json` 可见 `bootstrap_guide.next_single_action`。

---

## 1. 现象

在澄清（clarify）阶段，coordinator 期望 harness 自动派发 `requirements-clarifier` 子 agent，但实际 dispatch 一直停在 `waiting_dispatch`（`coordinator_action="pause_for_manual_worker"`），不产出任何 `Task` spawn 请求。

---

## 2. 实证状态（当前仓库）

```
docs/agent-runs            → 不存在（没有任何 run）
run-state.json             → 无
session-checkpoint.json    → 无（从未跑过 next）
.claude/                   → 只有 skills/ 与 worktrees/，无 settings.json、无 phase_guard
.opencode/                 → 无
```

`runtime-capabilities` 实跑对照：

| runtime | supports_subagent | dispatch_mode | spawn_tool |
|---|---|---|---|
| claude-code | `True` | native-subagent | `Task` |
| manual | `False` | manual-dispatch | —（不产出 spawn 请求） |

→ 四个派发前置（start / next / checkpoint / runtime-hook）全部缺失。

---

## 3. 派发的真实前置链

`dispatch-beat` / `dispatch-next` 不直达 `dispatcher.dispatch_beat`，而是被 `coordinator_flow._dispatch_with_hook_guard` 包了两道闸门。

### 闸门 1：session 检验（context budget gate）

`dispatch_context_budget_gate`（`coordinator_flow.py:69`）：

```python
budget = session_checkpoint.context_budget(state_file, state)
checkpoint = session_checkpoint.validate(repo, state_file)
if budget.get("handoff_recommended") and not checkpoint["ready"]:
    blocked.append("Session checkpoint required: ... run next to create a fresh checkpoint before dispatching more workers.")
```

`session_checkpoint.validate`（`session_checkpoint.py:268`）在以下任一情况判 **not ready**：

- checkpoint 文件缺失（**当前正是这种**：从未 next）
- schema / run_id 不符
- lifecycle 与 run-state 不符 → "run next or resume"
- fingerprint stale（gates / owners / updated_at 变动）
- created_at 缺失或超 30 分钟

checkpoint 的**唯一生产者是 `next`**（`coordinator_flow.py:847` → `session_checkpoint.create`），并在生成时把 `dispatch_waves_since_checkpoint` 重置为 0（`session_checkpoint.py:216`）。

### 闸门 2：runtime hook → 强制降级 manual（关键）

`_dispatch_with_hook_guard`（`coordinator_flow.py:747-751`）：

```python
hooks = runtime_hook_status(repo)
forced_waiting = hooks.get("runtime") == "generic" or not hooks.get("ready", False)
if forced_waiting:
    runtime = "manual"
```

当前 `.claude` 无 settings、`.opencode` 不存在 → `runtime_hook_status` 命中「两目录都不存在」分支（`coordinator_flow.py:156-165`）→ 返回 `ready=True` 但 **`runtime="generic"`** → `forced_waiting=True` → runtime 被改写为 `"manual"`。

`manual` 进入 `dispatcher.dispatch_beat` 后命中 `dispatcher.py:1169` 的 `supports_subagent=False` → 返回 `waiting_dispatch_result`、`coordinator_action="pause_for_manual_worker"`，**不产出 Task spawn 请求**。

> 这是「无法自动 spawn subagent」的脚本级真因：**不是 CLI 传错 runtime，而是没装 runtime hook，被上游 hook 守卫自动降级为 manual**。

---

## 4. 因果链

```
澄清阶段没派发子 agent
  └─ dispatch-beat 被 _dispatch_with_hook_guard 拦截
       ├─[闸门1] session_checkpoint.validate → not ready（无 checkpoint）
       │         └─ 无 checkpoint，因为从没跑 next
       │              └─ next 跑不动，因为无 run-state（没 start）
       └─[闸门2] 无 runtime hook → runtime 强制改 manual
                 └─ manual → supports_subagent=False → waiting_dispatch（永不 auto-spawn）
```

闭环续命：每派一波 `dispatch_waves_since_checkpoint += 1`（`dispatcher.py:194`），攒到 4 波（`DEFAULT_MAX_DISPATCH_WAVES`）触发 `handoff_recommended` → 又必须 `next` 重建 checkpoint 才能继续。`next` 既是流程起点钥匙，也是每隔 N 波的续命点。

---

## 5. 关键代码索引

| 关注点 | 位置 |
|---|---|
| dispatch 两道闸门包装 | `coordinator_flow.py:727` `_dispatch_with_hook_guard` |
| session 检验闸门 | `coordinator_flow.py:69` `dispatch_context_budget_gate` |
| hook 状态判定（generic 分支） | `coordinator_flow.py:112-174` `runtime_hook_status` |
| 强制降级 manual | `coordinator_flow.py:747-751` |
| checkpoint 校验 | `session_checkpoint.py:268` `validate` |
| checkpoint 生产 + 重置波计数 | `coordinator_flow.py:847`、`session_checkpoint.py:216` |
| 波计数自增 | `dispatcher.py:194-198` |
| supports_subagent 闸门 | `dispatcher.py:1169` |
| runtime 能力三档 | `runtime_adapters.py:75-105` |
| runtime 静默 fallback manual | `runtime_adapters.py:282-284` |
| 预检聚合（单一下一步） | `preflight.py:220-239` `aggregate_preflight_blockers` |
| next 编排 | `coordinator_flow.py:796` `next_step` |

---

## 6. 问题本质（三条）

1. **前置链长且隐式**：`start → install_hooks → next → dispatch-beat`，缺任一步都失败，但没有一处把这条链作为整体呈现给 coordinator。
2. **静默降级**：hook 没装时静默把 runtime 改成 `manual`，根因只藏在一条 warning；`adapter_for` 对未知/拼错 runtime 也静默 fallback manual。
3. **失败信息分散**：`next` 调了 `aggregate_preflight_blockers`（能产出有序 blocker + `next_single_action`），但 `dispatch-beat` 没走这套，各查各的，没汇成「单一根因 + 单一下一步」。

---

## 7. 优化方案

### P0｜静默降级 → 显式阻断 + 单一修复指引
`_dispatch_with_hook_guard` 中 `forced_waiting` 不再静默改 `runtime="manual"`，而是 `ready=False` 返回，复用 preflight 的 `next_single_action` 给出 `"运行 install_hooks --runtime claude"`。
保留「用户主动传 `--runtime manual`」的出口，区分「我要手动」与「我忘装 hook」。

### P0｜dispatch 前置统一走 preflight
`dispatch-beat` / `dispatch-next` 入口先调 `aggregate_preflight_blockers`，把「无 run-state / 无新鲜 checkpoint / hook 未就绪 / runtime 将被降级」四类合并成**一条有序 blocker + 一个 next_single_action**。coordinator 永远只看到「下一步该跑哪条命令」。

### P1｜runtime fallback 显式化
`adapter_for`（`runtime_adapters.py:282`）对 `gemini` / `opencode` / 拼写错误的 runtime，不再静默落 manual，而是返回 `warning: "unknown runtime X, falling back to manual"` 或直接报错。消除「传了看似支持的 runtime 却无声降级」的陷阱（SKILL.md 还把 opencode 列为合法选项，更易踩）。

### P1｜bootstrap 引导命令
增强已存在的 `doctor`（`engine/doctor.py`）：空仓库时输出有序引导「1.start 2.install_hooks 3.next 4.dispatch-beat」，每步带确切命令与「为什么」。把隐式链变成可见 checklist。

### P2｜文档化顺序约束
SKILL.md 显式写明：**hook 必须在 start + next 之后安装**（否则 phase_guard 会拦自己的工具调用），以及「无 hook = dispatch 永远降级 manual」。纯文档，零风险。

### 优先级

| 项 | 类型 | 影响 | 建议 |
|---|---|---|---|
| P0 静默降级 → 显式 | 真缺陷 | 高（直接消除本次困惑） | 先做 |
| P0 dispatch 统一 preflight | 真缺陷 | 高（一致的「单一下一步」） | 先做 |
| P1 runtime fallback 显式 | 真缺陷 | 中（隐蔽陷阱） | 次之 |
| P1 doctor 引导 | UX | 中 | 次之 |
| P2 文档 | UX | 低但零风险 | 随手做 |

**统一设计原则**：任何让派发不能 auto-spawn 的前置缺失，都必须冒泡成 `ready=False` + 单一 `next_single_action`，绝不静默降级。

---

## 8. 落地注意

这些改动触及 harness 脚本核心（`coordinator_flow` / `dispatcher` / `runtime_adapters`），被多条 dispatch 流程复用。按本项目 CLAUDE.md：

1. 先 `gitnexus_impact` 评估 blast radius（改 `forced_waiting` 语义属中高风险）。
2. **TDD**：先写失败测试（例：「hook 缺失时 dispatch 返回 install_hooks 指引而非 manual 降级」）。
3. 改完 `gitnexus_detect_changes` 核对影响范围。

---

## 9. 恢复顺序（当前空仓库 → 能 auto-spawn）

1. `start` —— bootstrap 出 `docs/agent-runs/<run>/{run-state.json, agent-schedule.json}`（lifecycle=CREATED）。
2. `install_hooks --runtime claude` —— 写 `.claude/settings.json` 的 phase_guard。**必须在 start + next 之后或紧随其后**，否则 phase_guard 会拦截 coordinator 自己的工具调用。
3. `next` —— 生成首份 session-checkpoint，返回 CREATED 的 `dispatch-beat ... --max-workers 1` 派发命令。
4. `dispatch-beat` —— runtime=claude-code 且 checkpoint ready 时，引擎产出 `requirements-clarifier` 的 `Task` spawn 请求。
5. coordinator 实际调 `Task` spawn（会话层仍需用户授权，与脚本无关）。
