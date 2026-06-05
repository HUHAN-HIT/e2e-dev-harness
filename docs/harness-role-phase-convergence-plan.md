# Harness 角色/阶段收敛实施计划（B 方案）

> 状态：待确认 · 日期：2026-06-04 · 范围：`skills/e2e-dev-harness/scripts` 调度链路
> 前置分析见本文件「附录：散落点全清单」。

## 目标（验收标准）

1. `LIFECYCLE_SATISFIED_PHASES` 只有一份定义，`agent_scheduler` 与 `dispatcher` 不可能再 diverge（用测试钉死相等）。
2. 阶段排序知识（depends_on / allowed / satisfied / role_group / name→phase）全部从 `agent_roles` 的单一注册表派生。
3. `subagent_kind` 要么真正驱动运行时路由、要么删除——不留两张皮。
4. `ROLE_TEMPLATE_FILES`、`start.py:ROLE_TEMPLATE_DETAILS` 由 registry 派生，不再各存一份。
5. 全量测试绿；`detect_changes` 仅命中预期符号。

## 约束与原则

- **行为零回归**：每步先写/扩测试（TDD），保留所有调用点的 `.get()` 默认值（scheduler 用 `""`，planning 用 `"coordination"`）。
- 遵守项目规约：改每个高扇出符号前先 `gitnexus_impact(upstream)`，改完 `gitnexus_detect_changes()`。
- `agent_roles` 仍只做 planning data，不碰 spawn/调度，保持 runtime-portable 不变量。
- `domain/schedule.py` 的 `from agent_scheduler import *` 要求 `LIFECYCLE_SATISFIED_PHASES` 等保留为 `agent_scheduler` 的模块级名字（可绑定到 `agent_roles` 的值）。

---

## Step 0 — 基线与影响面（只读，不改）

- 跑全量 `tests/` 取绿色基线。
- 对将改符号做 upstream 影响分析：`LIFECYCLE_SATISFIED_PHASES`、`LIFECYCLE_ALLOWED_PHASES`、`depends_on_for_phase`、`phase_for_agent`、`role_group_for_phase`、`runtime_subagent_type_for_phase`、`ROLE_TEMPLATE_FILES`、`start.ROLE_TEMPLATE_DETAILS`。
- 任一项 HIGH/CRITICAL 先停下确认。

## Step 1 — 在 `agent_roles` 建 `PHASE_REGISTRY` + `LIFECYCLE_REGISTRY`（TDD，核心）

先写 `test_agent_roles` 新用例：

- `PHASE_REGISTRY` 覆盖 9 个 phase，每条含 `order / role_group / depends_on`。
- 派生函数：`depends_on_for_phase(phase)`、`phase_role_group(phase)`、`role_to_phase(role_key)`。
- `LIFECYCLE_REGISTRY` 提供 `lifecycle_allowed_phases` 与 `lifecycle_satisfied_phases` 两张表（按 lifecycle 键）。
- 钉死：`PHASE_ROLE_GROUPS` 与新派生结果一致（保留旧名，做派生别名）。

**决策点（实现时核验，不臆断）**：两份 `LIFECYCLE_SATISFIED_PHASES` 对 `SERVICE_DESIGN_REQUIRED` 不一致——`dispatcher` 多了 `r1-review`。实现时读 `run_state` 的 lifecycle 语义 + 现有 gate 测试判定哪份正确，**默认倾向 dispatcher 的超集（含 r1-review）**（它是运行时实际 gating 用的表）；最终值用一条专门测试固定并在提交说明里标注。

## Step 2 — 统一 `LIFECYCLE_SATISFIED_PHASES`（消灭真实 bug）

- 先加 RED 测试：`agent_scheduler.LIFECYCLE_SATISFIED_PHASES == dispatcher.LIFECYCLE_SATISFIED_PHASES`（当前红）。
- `agent_scheduler.LIFECYCLE_SATISFIED_PHASES`、`dispatcher.LIFECYCLE_SATISFIED_PHASES`/`LIFECYCLE_ALLOWED_PHASES` 改为引用 `agent_roles` 的派生值（保留模块级名字以兼容 `import *`）。
- 测试转绿即证明 divergence 根除。

## Step 3 — `orchestration_plan` 阶段函数改为派生

- `depends_on_for_phase` → 委托 `agent_roles.depends_on_for_phase`（保留 `["plan"]` 默认）。
- `phase_for_agent(name)` → 改为 `resolve_role_key(name)` → `role_to_phase`，删掉第二套独立 substring 匹配；保留无匹配时的 `"plan"` 回退。
- 先扩 `test_orchestration`：对现有 name 矩阵断言新旧 `phase_for_agent` 结果逐一相等，再替换实现。

## Step 4 — 让 `subagent_kind` 成为活数据

- `runtime_subagent_type_for_phase` 的"review/coverage 走 reviewer"判定改为：经 `role_to_phase` 反查该 phase 的 canonical role → 读其 `subagent_kind == "reviewer"`。
- 加测试：`subagent_kind` 与 `PHASE_ROLE_GROUPS in {review,coverage}` 必须自洽（任一改动另一处不同步即红）。声明与路由合一。

## Step 5 — `ROLE_TEMPLATE_FILES` 派生

- `orchestration_plan.ROLE_TEMPLATE_FILES = {role: f"{role}.md" for role in agent_roles.ROLE_REGISTRY}`（保持插入顺序与现状一致）。
- 测试钉死派生结果等于原字面表。

## Step 6 — 收掉 `start.py:ROLE_TEMPLATE_DETAILS` 拷贝

- `start.py` 改为从 `agent_roles` 取模板；`ROLE_TEMPLATE_DETAILS` / `role_template_text` 保留为薄别名（现有 `LegacyParityTest` 仍引用）。
- parity 测试由"胶水"变为"恒等"，仍绿。

## Step 7 —（较高风险，默认拆为后续 PR）prompt 规则从 role-template 渲染

- `dispatcher.task_prompt()` / `ready_handoff_prompt_lines()` 中重述的角色约束，改为引用 `agent_roles.template_text` 渲染出的 boundary/forbidden，消除规则两处维护。
- 会改变 worker 收到的 prompt 文本、可能触及 prompt 相关测试，**建议单独成 PR**；前 6 步先合。

## Step 8 — 全链路验证

- 全量 `tests/` 绿。
- `gitnexus_detect_changes(unstaged)` 确认只命中 `agent_roles / agent_scheduler / dispatcher / orchestration_plan / start.py` 及对应测试，无意外扩散。
- 汇总每步影响分析结果。

---

## 触及文件

| 文件 | 改动 |
|---|---|
| `skills/e2e-dev-harness/scripts/agent_roles.py` | 新增 `PHASE_REGISTRY` / `LIFECYCLE_REGISTRY` 及派生函数 |
| `skills/e2e-dev-harness/scripts/agent_scheduler.py` | `LIFECYCLE_SATISFIED_PHASES` 改引用 agent_roles |
| `skills/e2e-dev-harness/scripts/dispatcher.py` | `LIFECYCLE_*_PHASES` 改引用 agent_roles |
| `skills/e2e-dev-harness/scripts/orchestration_plan.py` | `phase_for_agent` / `depends_on_for_phase` / `ROLE_TEMPLATE_FILES` / 路由派生 |
| `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py` | `ROLE_TEMPLATE_DETAILS` 改薄别名 |
| `tests/test_agent_roles.py`, `tests/test_orchestration.py`, (新) `tests/test_lifecycle_registry.py` | 钉死契约 |

## 风险点

- Step 2 的 `SERVICE_DESIGN_REQUIRED` 取值是唯一"语义判断"，其余都是纯重构（行为恒等、测试钉死）。该步用证据决定，不猜。
- Step 7 风险最高，默认拆出。

## 执行顺序与依赖

```
Step 0 (基线/影响面)
  └─ Step 1 (注册表) ──┬─ Step 2 (统一 lifecycle 表)
                       ├─ Step 3 (phase 函数派生)
                       ├─ Step 4 (subagent_kind 活化)
                       └─ Step 5 (模板文件派生)
                            └─ Step 6 (start.py 收拢)
                                 └─ Step 8 (全链路验证)
Step 7 (prompt 渲染) —— 独立 PR，后续
```

---

## 附录：散落点全清单（前置分析结论）

| # | 严重度 | 散落点 | 位置 | 计划步骤 |
|---|---|---|---|---|
| 1 | 🔴 | `LIFECYCLE_SATISFIED_PHASES` 两份且 `SERVICE_DESIGN_REQUIRED` 已不一致 | `agent_scheduler.py:32` / `dispatcher.py:229` | Step 1–2 |
| 2 | 🟠 | "phase 排序"被编码 4 次（depends_on / allowed / satisfied×2） | orchestration_plan / dispatcher / agent_scheduler | Step 1–3 |
| 3 | 🟠 | `phase_for_agent` 是第二套独立 name→分类匹配器 | `orchestration_plan.py:961` | Step 3 |
| 4 | 🟡 | `subagent_kind` 为死数据，运行时路由另算 | `agent_roles.py` 定义 vs `orchestration_plan.py:1016` | Step 4 |
| 5 | 🟡 | `ROLE_TEMPLATE_FILES` 重复 registry 的 role keys | `orchestration_plan.py:636` | Step 5 |
| 6 | 🟡 | `start.py:ROLE_TEMPLATE_DETAILS` 整份模板拷贝，靠 parity 测试对齐 | `start.py` | Step 6 |

### agent↔harness 拉扯点

- **角色边界规则两处维护**：`agent_roles` 模板 vs `dispatcher.task_prompt`/`ready_handoff_prompt_lines` 自然语言重述 → Step 7。
- **完成协议多步拉扯**：`dispatch_engine.finish()` 折叠 ack→handoff→complete 是 agent 抄近路 / harness 反复堵的产物；表象已缓解，协议真相仍分散（dispatcher 各函数 + engine facade + manual_worker_packet 字符串）。
- **lifecycle 真相源脆弱**：`dispatcher.recover_main_lifecycle()` 需从多处反推 lifecycle，说明该状态无单一可信落点。
