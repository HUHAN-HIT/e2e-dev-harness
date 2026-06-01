# 协调者上下文 & 子 Agent 调度 重构方案（合并版）

> 日期：2026-06-02
> 状态：草案（待评审）
> 回归基线：现有 **779** 测试（已核验真实），每步改完 `python -m pytest tests/ -q` 必须仍全绿。

## 0. 背景与目标

针对 `skills/e2e-dev-harness` 的两个问题做实测评估并给出可落地方案：

1. **主 agent（协调者）上下文爆炸** —— 实测确认为真问题。
2. **子 agent 是否能调度起来** —— 实测端到端跑通，需补无 hook 环境的防破防。

## 1. 实测证据（协调者每步真实吞入字节）

| 命令 | 单次 stdout 字节 | ≈tokens | 频次 | 备注 |
|---|---|---|---|---|
| `start` | 13,284 | ~3.3k | 一次性 | — |
| `next` | **19,932** | **~5k** | **每阶段重调** | 乘性来源 #1 |
| `orchestration_plan`（discovery） | 257 | ~60 | 低频 | 精简反例 |
| `dispatch-next` | **17,944** | **~4.5k** | **每任务调** | 乘性来源 #2 |
| 前 4 条累计 | **51,417** | **~13k** | — | 尚未读任何代码/worker 结果 |

其它实测事实：
- 单次 `next` 内绝对仓库路径重复 **8 次**、`dispatch-next` **6 次**；`hook_status` 诊断块内嵌于 `next`。
- 全仓仅 `verify` 有 `--summary-json/--summary-md`；`next`/`gate`/`dispatch-*` **无任何精简模式**。
- `context_pack.py` 给 worker 设 12 文件 / 120KB 硬上限并会 BLOCK；**协调者侧零预算（不对称）**。
- `dispatch-next` 实测产出合法 `tool:"Task"` + `subagent_type:"general-purpose"` + prompt，task `claimed`、`awaiting_runtime_spawn`；`dispatch-complete` 有 ack 强校验防伪造 → **调度机制本就可用**。
- 本环境实测 hook 缺失：`next` 报 `hook config not found`、`PostToolUse audit-only`。

## 2. 根因

| # | 缺陷 | 性质 |
|---|---|---|
| D1 | 热路径命令无精简模式（`next` 20KB/阶段、`dispatch-next` 18KB/任务，乘性增长） | 治标点 |
| D2 | 输出冗余（绝对路径×8、`hook_status` 噪声内嵌） | 治标点 |
| D3 | 协调者侧无对称上下文预算 | 治本点 |
| S1 | 角色坍缩（worker 全 `general-purpose`，隔离仅提示级） | 结构 |
| S2 | 无 hook 时调度完整性（可自报 worker_running） | 结构 |
| S3 | god-file `e2e_dev_harness.py`（2985 行 / 21 命令） | 可维护性 |

## 3. 解决方案（低风险 → 高风险，逐项 TDD）

### 优先级
```
P0 防破防       → 步骤1
P1 治标(最高ROI) → 步骤2 + 缺口A
P2 治本(瘦协调者) → 步骤5 + 步骤4 + 缺口B
P3 结构门禁      → 步骤3
P4 可维护性(高风险) → 步骤6 + phase_guard 单列
```

### P0 — 步骤1：hook 缺失即强制 WAITING_DISPATCH
- 能力探测无 `spawn_tool` → 硬置 `waiting_dispatch`，禁止自报 `worker_running`。
- **验收**：无 hook 环境下 `dispatch-complete` 必被阻断 + 新增测试。
- 注：本环境 hook 实测缺失，非假设。

### P1 — 步骤2 + 缺口A：重输出命令落盘契约（最高性价比）
- 高频/大输出命令默认 `--evidence-file <path>`，stdout 仅回「摘要 + 文件路径」。
- **缺口A（必补）**：原列表「gate/依赖扫描/impact/run-summary」**漏掉实测最大的两个** `next`（20KB/阶段）与 `dispatch-next`（18KB/任务）。
  - 把"盘点直接打全量 JSON 的命令"写成**强制覆盖全部 stdout-JSON 命令**的门禁，显式纳入 `next` 与 `dispatch-next`。
- 顺带治 D2：相对路径替代重复绝对路径；`hook_status` 仅 BLOCK 时展开。
- **验收**：`next`/`dispatch-next` stdout < 1KB（基线 20KB/18KB）；完整 JSON 落盘；779 全绿。

### P2 — 步骤5 + 步骤4 + 缺口B：协调者瘦身（治本）
- **步骤5（行为半边）**：非平凡任务 single-review 设为下限；协调者只「决策 + 派发 + 对账」，不内联干 design/test/code/review；以 `superpowers:subagent-driven-development` 为执行骨架，绑定 role→agent。
- **步骤4（累积半边）**：`session_checkpoint.py` 接成阶段切换必经压缩；协调者上下文设软上限、超限强制 checkpoint。
- **缺口B（必补）**：软上限要可测代理指标（harness 看不到 LLM 真实窗口）——累计 evidence 字节 / 阶段数 / 工具调用数，任一超阈触发；resume 仅重载**精简 run-state 摘要**。
- **验收**：多服务 run 协调者累计吞入下降 ≥80%；checkpoint→resume 后 run-state 重载 < 5KB。

### P3 — 步骤3：single 模式硬护栏
- 角色坍缩前要么机器校验「确属小型低风险单服务」（复用 `orchestration_plan` 判据），要么要求显式用户许可；否则升 single-review。指引变门禁。
- **验收**：多服务/风险关键字场景 `single` 被自动拦截升级，有测试覆盖。

### P4 — 步骤6：拆 god-file（高风险，最后做）
- `e2e_dev_harness.py` 按 编排 / gate / 证据 分模块。
- **单列**：`phase_guard` 正则黑名单 → 真实文件 diff 白名单（风险高，独立立项）。
- 注：此项不减运行时上下文（Python 加载，不进 agent 上下文），属可维护性/测试性。

### 补充项（次要，并入 P1/P2）
- 协调者预加载 13 处 `Read references`（~2400 行）：给协调者「最小读取集」，其余引用仅对应阶段、仅该 worker 读。

## 4. 风险与护栏（不可省）

- **成本翻倍**：team = 多 agent = token 成倍。必须用 harness `auto` **按任务规模决定是否起 team**，小改不起 team。（本方案诞生于已达 CRITICAL 成本的会话——活例。）`auto` 阈值需调优，避免把"上下文爆炸"换成"成本爆炸"。
- **非确定性上升**：保留 gate/evidence 作信任锚，**不得**因 team「能自协调」而拆门禁。
- **非从零**：spawn hook 已在，杠杆是「用足 + 瘦身协调者」，不是重写。
- **回归基线**：779 测试为硬基线，每步全绿。

## 5. 预期效果（量化）

| 指标 | 改造前（实测） | 改造后（目标） |
|---|---|---|
| `next` stdout | 19,932 B/阶段 | < 1KB |
| `dispatch-next` stdout | 17,944 B/任务 | < 1KB |
| 协调者单 run 累计吞入 | 外推 200–500KB | 下降 ≥80% |
| 子 agent 调度 | 已可用 | 保持 + 无 hook 防破防 |

## 6. 落地顺序建议

1. P0 步骤1（防破防，先封破口）。
2. P1 步骤2 + 缺口A（先砍 `next`/`dispatch-next`，立竿见影）。
3. P2 步骤5 → 步骤4 + 缺口B（瘦协调者 + 阶段 compaction）。
4. P3 步骤3（single 硬护栏）。
5. P4 步骤6 + phase_guard 单列（高风险，独立 PR）。
