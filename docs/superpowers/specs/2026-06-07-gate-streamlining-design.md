# 门禁精炼 — 设计规格 (Gate Streamlining Design Spec)

- **状态**: 已评审通过 (Approved) — 待转 writing-plans (实现另起会话)
- **日期**: 2026-06-07
- **范围**: e2e-dev-harness 全生命周期门禁体系
- **关联**: 提案 `docs/gate-streamlining-proposal.md`
- **目标**: 让 harness 把精力放在核心工作(交付正确、可测的实现),而非反复修补边角与无关完成度

---

## 0. 已确认决策 (来自评审)

| # | 决策点 | 结论 |
|---|---|---|
| D1 | P4 minimal 内联边界 | **单 worker 一趟**跑完整任务;仅作用于 minimal 档 |
| D2 | 是否减负既有档位 | **只加 minimal,basic/standard/critical/audited 完全不动** |
| D3 | 台账生成方式 | **hook 后台异步生成**;门禁不再因台账缺失而阻断 |
| D4 | 防放水安全网 | **金标回归用例集**,每期出口强制通过 |
| D5 | minimal 与 review | **minimal 跳过独立 review** (不派 r1/r2/r3) |

---

## 1. 总体架构

四个杠杆,分四期落地。每期独立可验证、可回滚。

```
P1 (S1+S2): task_tier.py        — 新增 minimal 档 + 收紧分级器 + 金标用例集
P2 (S3):    clarification_gate  — 接 tier + 机械修复内联化
P3 (S4):    台账 hook           — 台账非阻断 + 后台生成
P4 (S5):    lifecycle_policy    — minimal 单 worker 一趟,根治每阶段派工
```

核心原则:**精炼 ≠ 减少检查总量,而是让每道检查只在它真正被消费的阶段出现一次,并随风险缩放。**

---

## 2. S1 — 新增 `minimal` 地板 tier

**文件**: `skills/e2e-dev-harness/scripts/task_tier.py`

### 2.1 tier 序列
`TIERS` 增加 `minimal`,位于 `basic` 之下:
`("auto", "minimal", "basic", "standard", "critical", "audited")`
`ENFORCED_TIERS` 增加 `minimal` 为最低 enforced 档。

### 2.2 minimal 门禁集 (载重 4 道)
```
MINIMAL_GATES = ["clarification", "test-evidence", "task-alignment", "run-state"]
```
- `completion-proof` / `ac-progress` 的语义折叠进 `task-alignment` (放行只认 alignment 一道,内部仍可校验 AC 覆盖)。
- `impact-summary` 不在 minimal (下沉,见 S3)。
- `artifact-registry` / `agent-schedule` / `run-summary` 不在 minimal (转 hook 生成,见 S4)。
- `r1/r2/r3-review` 不在 minimal (D5:跳过独立 review)。

### 2.3 判定规则
`minimal` 触发条件 (D1 阈值):
**无风险关键词命中 + 单服务 + 无跨服务依赖** → `minimal`。
`classify_auto` 在所有升级路径都未命中、且 `not multi_service` 且 `not kinds` 时,返回 `minimal`(替换当前"design-backed → standard / 空 → basic"的兜底)。

### 2.4 basic 及以上不变
`gates_for` 对 basic/standard/critical/audited 的返回值**保持现状**,仅新增 `minimal` 分支。

---

## 3. S2 — 收紧分级器 + 金标安全网

**文件**: `skills/e2e-dev-harness/scripts/task_tier.py` + 新增测试

### 3.1 关键词收紧
弱信号词从"单独触发升级"中降权:
- `WEAK_CONTRACT_KEYWORDS` (`api`/`http`/`rest`/`client`/`endpoint`) 已是弱信号(需配合 multi_service/kinds),**保持**。
- 把 `repository`/`mapper` 从 `DATA_KEYWORDS` 移入新的弱信号集;把 `tag`/`group` 从 `MESSAGING_KEYWORDS` 移入弱信号集;把 `schema` 从 `CONTRACT_KEYWORDS` 移入弱信号集。
- **规则**:弱信号词仅在 `multi_service or kinds` 同时成立时才参与升级 critical;单独出现不升级。
- 强信号词(`payment`/`refund`/`settlement`/`kafka`/`rocketmq`/`migration`/`transaction` 等)**保持单独即可升级**。

### 3.2 放开显式降级
`evaluate`:`downgrade_blocked` 仅对 `audited` 强制;其余档位允许用户带 provenance 降级。
新增返回字段 `downgrade_requires_provenance: true`(供调用方提示记录 `confirmed-by: user @...`)。

### 3.3 金标回归用例集 (D4)
新增 `skills/e2e-dev-harness/tests/test_task_tier_golden.py`(或并入现有 tier 测试),fixtures 至少覆盖:

| 场景 | 期望 tier |
|---|---|
| 支付回调改造 (payment + 跨服务) | critical |
| MQ 通知 + 多服务 | critical |
| 改单表查询 (出现 repository,单服务,无依赖) | minimal |
| 改一个工具函数 (无关键词,单服务) | minimal |
| 单服务 REST 接口新增 (api,单服务,无依赖) | basic 或 standard(按现行弱信号规则,锁定其一) |
| 合规审计任务 (audit/compliance) | audited |

每期出口必须全绿;此集即"防放水"契约。

---

## 4. S3 — 澄清门禁接 tier + 机械修复内联化

**文件**: `clarification_gate.py` (`validate` @ L758)、`clarification_flow.py`

### 4.1 validate 接 tier
`validate(path, require_intent, require_user_confirmation, tier="standard")`:
- `tier in {minimal, basic}` → 跳过 `impact_summary_gaps` / `change_logic_gaps` / `integration_gaps` 三类 evidence 检查(返回空 gap,不计入放行)。
- 放行条件 [clarification_gate.py:804](../../skills/e2e-dev-harness/scripts/clarification_gate.py):
  - 低 tier:`ready_for_implementation = user_clarification_ready`
  - 高 tier:维持现有 4-AND。
- `tier` 由 `clarification_flow.run` 从 run-state / tier 评估结果读入并透传。

### 4.2 机械修复内联化
`clarification_flow` 中 `_ensure_mechanical_repair_tasks` / `_mechanical_repair_next_required`:
- 纯格式类修复码(`impact_summary_too_long`/`impact_summary_table_too_large`)**不再强制 `dispatch-beat`**,允许 coordinator 一次 Edit 修复。
- 仅"需重做需求/设计判断"的修复(如 `impact_summary_table_incomplete` 缺证据)保留派工。
- `dispatcher.coordinator_worker_only_action` 增加"格式类豁免"判断分支。

---

## 5. S4 — 台账非阻断 + hook 后台生成 (D3)

**文件**: 相关 gate(coverage_gate / 台账校验点)+ 新增 hook 脚本

### 5.1 门禁降级
coverage-matrix / artifact-registry / run-summary 等台账类检查:产物缺失从"阻断/非零退出"改为 **warn**,不影响放行布尔值。

### 5.2 hook 后台生成
新增 Stop(或 PostToolUse)hook:在阶段收尾异步补齐台账文件(artifact-registry / run-summary / coverage-matrix)。
- hook 失败不阻断主流程(写降级证据)。
- 高 tier 仍可保留台账作为审计 evidence,但生成责任移交 hook,放行不再依赖 agent 单独跑。

---

## 6. S5 — P4 根治每阶段派工 (仅 minimal,D1+D5)

**文件**: `lifecycle_policy.py` (`required_todo_list_for_lifecycle` @ L87)

### 6.1 接 tier
`required_todo_list_for_lifecycle(lifecycle, state=None, tier="standard")`:
- **minimal**:返回"单 worker 一趟"todo —— 一个 worker 串行完成 clarify→plan→implement→test,coordinator 仅在出口过载重 4 门禁;**不再每 state 一轮 spawn / dispatch-ack / dispatch-complete**;**不派独立 review**(D5)。
- **basic 及以上**:返回现有逐阶段隔离派工 todo,**完全不变**。

### 6.2 状态机兼容
minimal 仍走 CREATED→...→VERIFIED 状态推进(保证 run-state 门禁),但阶段间不强制 worker 隔离;`next` 对 minimal 放宽"必须有 dispatch 完成证据"的前置(`preflight.clarification_dispatch_blockers` 对 minimal 豁免)。

---

## 7. 受影响核心节点

动前逐个跑 `gitnexus_impact`(CLAUDE.md 强制),HIGH/CRITICAL 先告警:
- `task_tier.evaluate` / `task_tier.classify_auto`
- `clarification_gate.validate`
- `clarification_flow.run`
- `lifecycle_policy.required_todo_list_for_lifecycle`
- `dispatcher.coordinator_worker_only_action`
- `preflight.clarification_dispatch_blockers`

---

## 8. 分期与出口标准

| 期 | 内容 | 出口标准 |
|---|---|---|
| P1 | S1 + S2 | 现有 tier 测试全绿 + 金标用例集通过 + `detect_changes` 仅影响 task_tier |
| P2 | S3 + 机械修复内联 | 澄清门禁低 tier 减负生效 + 机械修复可内联 + 回归全绿 |
| P3 | S4 | 台账缺失不阻断 + hook 生成验证 + 回归全绿 |
| P4 | S5 | minimal 单 worker 跑通端到端 + basic 及以上行为不变 + 回归全绿 |

每期通用出口:`detect_changes` 确认仅影响预期 symbol;新增针对该期行为的回归测试;金标用例集不退化。

---

## 9. 非目标 (YAGNI)

- 不重构 basic/standard/critical/audited 的门禁集(D2)。
- 不删除任何 reviewer 消费的产物(impact/contracts/r3 只下沉/缩放)。
- 不引入新的 tier 之外的配置维度。
- 不在本轮改动 GitNexus / 审计回放(audited)逻辑。

---

## 10. 下次会话续接指引

实现从 P1 开始。续接步骤:
1. 读本 spec + `docs/gate-streamlining-proposal.md`。
2. 对第 7 节核心节点逐个跑 `gitnexus_impact`,HIGH/CRITICAL 告警。
3. 进 `superpowers:writing-plans` 出 P1 实现计划。
4. 按 TDD(先写金标用例集红测)落地 S1+S2。
