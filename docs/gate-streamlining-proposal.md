# 全流程门禁精炼方案 (Gate Streamlining Proposal)

- **状态**: 草案 (Draft) — 待评审
- **日期**: 2026-06-07
- **作者**: harness 评审
- **范围**: e2e-dev-harness 全生命周期门禁体系 (不限于澄清环节)
- **目标**: 让 harness 把精力放在核心工作上,而不是反复修补边角、无关任务完成度的事项

---

## 1. 问题陈述

当前 harness 在实际运行中,大量时间消耗在**非核心环节**:

- 门禁与 agent 反复拉扯
- 反复返工中间产物文件 (设计文档表格、handoff、台账)
- 简单任务被无差别拖进重型流程

核心矛盾:**流程把"走完调度仪式"本身当成了目标**,而非"交付正确的、可测的实现"。

---

## 2. 关键发现:分级机制已存在,但被架空

harness **已经有一套分级门禁系统** ([`task_tier.py:15-45`](../skills/e2e-dev-harness/scripts/task_tier.py)),按 tier 递增挂门禁:

| tier | 门禁数 | 新增门禁 |
|---|---|---|
| basic | 9 | clarification, impact-summary, test-evidence, completion-proof, task-alignment, run-state, artifact-registry, agent-schedule, run-summary |
| standard | 14 | +r1/r2/r3-review, coverage-matrix, requirements-archive |
| critical | 19 | +gitnexus-impact, contracts, service-plans, handoffs, strict-guard |
| audited | 23 | +harness-policy/replay, completion-replay, state-history |

设计本身合理。但它没有发挥作用,原因是三个系统性缺陷。

### 缺陷 1 — auto 分级几乎把所有任务推到 critical (19 门禁)

[`task_tier.py:155-181`](../skills/e2e-dev-harness/scripts/task_tier.py) `classify_auto`:**只要命中任一风险关键词、或有任一依赖、或多服务,直接判 critical**。而关键词网过宽:

- `DATA_KEYWORDS` 含 `transaction` / `repository` / `mapper` / `audit`
- `MESSAGING_KEYWORDS` 含 `tag` / `group` / `payload` / `send`
- `CONTRACT_KEYWORDS` 含 `schema` / `api`(弱信号)

→ 一个"改个 repository 查询"的小任务,因出现 `repository` 即被判 critical,挂满 19 道闸。
→ [`task_tier.py:196`](../skills/e2e-dev-harness/scripts/task_tier.py) `downgrade_blocked`:**用户想降级都不行**。
→ 最低档 `basic` 仍有 9 道闸,**没有真正的轻量级地板**。

### 缺陷 2 — 澄清门禁完全无视 tier

[`clarification_gate.py`](../skills/e2e-dev-harness/scripts/clarification_gate.py) / [`clarification_flow.py`](../skills/e2e-dev-harness/scripts/e2e_harness/engine/clarification_flow.py) 中对 `tier` 的引用为 **0**。
只要文本命中 `IMPACT_REQUIRED_RE`(同样宽松),无论 tier,强制要求 Impact Summary 六列表格 + Change Logic 四要素 + 调用链。**分级在澄清环节根本没接进来。**

### 缺陷 3 — 每个生命周期阶段都强制"派工往返"

[`lifecycle_policy.py:87-147`](../skills/e2e-dev-harness/scripts/lifecycle_policy.py) `required_todo_list_for_lifecycle`:**每一个 state** 的 todo 都是同一套
`dispatch-beat → spawn worker → dispatch-ack → dispatch-complete → next`,外加 "Do not do X in coordinator chat"。

配合机械修复机制 ([`clarification_flow.py:85-94`](../skills/e2e-dev-harness/scripts/e2e_harness/engine/clarification_flow.py)):**连压缩一个表格都要派一轮 worker + 返工 schedule 文件**。

→ coordinator 在每个阶段都不准直接干活,一切都是 dispatch 往返。这是"反复拉扯 / 耗在非核心"的结构性来源。

---

## 3. 门禁全景分类

判定标准(两把尺子):一道检查值得做成**阻断式门禁**,当且仅当
(a) 判错代价不可逆/昂贵,且 (b) 无法在后续阶段廉价复检。

| 门禁 | 性质 | 处置 |
|---|---|---|
| **clarification** (语义本质) | ✅ 载重 | 保留,收成"用户确认的可测问题"单条 |
| **test-evidence** (red→green TDD) | ✅ 载重 | 保留 — 核心纪律 |
| **task-alignment / completion-proof / ac-progress** | ✅ 载重(三者重叠) | 合并为一道"建对了没有" |
| **run-state** (状态机完整性) | ✅ 结构性、廉价 | 保留 |
| impact-summary / gitnexus-impact | ⚠️ 下游关注点、过早 | 下沉到 plan/implementation,且仅 critical |
| contracts / service-plans / handoffs | ⚠️ 仅跨服务真有风险时 | 升级条件收紧,仅 critical + 多服务 |
| r1 / r2 / r3-review | ⚠️ 应随 tier 缩放 | basic→1 道,standard→2 道,critical→3 道 |
| coverage-matrix / requirements-archive / artifact-registry / run-summary / agent-schedule | 🧾 台账 | 降级为非阻断,自动生成 |
| mechanical-repair (表格字数/行/列) | 🧹 纯格式 lint | 降级为 advisory,允许内联修,禁止派工 |
| strict-guard / harness-policy / harness-replay / completion-replay / state-history | 🔒 审计回放 | 仅 audited tier |

### 精要门禁集 (任何任务都过的载重 4 道)

1. `clarification` — 用户确认的可测问题 (语义)
2. `test-evidence` — TDD red→green (纪律)
3. `alignment` — 建对了被要求的东西 (AC 覆盖)
4. `run-state` — 状态机完整性 (结构)

其余全部变为**按 tier 挂载的条件门禁**或**非阻断台账**。

---

## 4. 方案:四个杠杆 (按性价比排序)

> 核心原则:**精炼 ≠ 减少检查总量,而是让每道检查只在它真正被消费的阶段出现一次,并随风险缩放。**

### 杠杆 A — 修分级器,堵住"全员 critical" (最高杠杆)

**文件**: `task_tier.py`

- 收紧关键词网:把 `repository` / `mapper` / `tag` / `group` / `api` / `schema` 等高频弱信号,从"单独触发升级"中移除;升级要求**关键词 + 真实依赖证据双命中** (`classify_auto` 中单关键词 `risk_reasons` 路径改为需配合 `kinds`)。
- 新增真正的 `minimal` 地板 tier (仅挂载重 4 门禁)。
- 允许用户带 provenance 显式降级 (放开 `downgrade_blocked`,audited 除外)。

### 杠杆 B — 让澄清门禁接入 tier

**文件**: `clarification_gate.py` (`validate()` @ L758) + `clarification_flow.py`

- `validate` 接收 `tier` 参数;低 tier 跳过 Impact Summary / Change Logic / integration 三类 evidence 检查。
- 放行条件 ([`clarification_gate.py:804`](../skills/e2e-dev-harness/scripts/clarification_gate.py)) 的 4 项 AND,低 tier 收成仅 `user_clarification_ready`;evidence / mechanical 两项下沉。

### 杠杆 C — 机械修复内联化 + 台账门禁非阻断

**文件**: `clarification_flow.py:85-94`、`dispatcher.coordinator_worker_only_action`

- 纯格式修复 (`impact_summary_too_long` 等) 取消强制 `dispatch-beat`,允许一次 Edit。派工只留给"需要重做需求/设计判断"的修复。
- coverage-matrix / artifact-registry / run-summary 等台账类:缺失只 warn 不 block,改为收尾自动生成。

### 杠杆 D — 低 tier 放松"每阶段派工"强制

**文件**: `lifecycle_policy.py:87` `required_todo_list_for_lifecycle`

- 按 tier 返回 todo:低 tier 允许 coordinator 内联完成轻量阶段 (如 basic 任务的 plan),不强制每 state 一轮 spawn。
- 高 tier 维持隔离派工 (保证审计与独立 review)。

---

## 5. 风险与安全网

- `impact-summary` / `contracts` / `r3` 是 reviewer 真在消费的产物 → **只能下沉/缩放,不能删**。否则跨服务支付类改造会放水。
- 杠杆 A 的关键词收紧必须保留"双命中仍升 critical"的安全网。
- `task_tier.evaluate`、`clarification_gate.validate`、`lifecycle_policy.required_todo_list_for_lifecycle` 均为高扇出核心节点 → 改动前逐个跑 `gitnexus_impact` 报影响面,对 HIGH/CRITICAL 告警后再动。

---

## 6. 实施分期 (每期独立可验证)

| 期 | 杠杆 | 改动面 | 风险 | 收益 |
|---|---|---|---|---|
| P1 | A 分级器 | 集中 (`task_tier.py`) | 低-中 | 最大:止住全员 critical |
| P2 | C 机械修复内联 + 台账非阻断 | 中 | 中 | 直接消除"反复拉扯" |
| P3 | B 澄清接 tier | 中 (依赖 P1) | 中 | 简单任务澄清减负 |
| P4 | D 放松每阶段派工 | 大 (动 lifecycle 主干) | 高 | 全流程减仪式 |

每期出口标准:现有 harness 测试全绿 + `detect_changes` 确认仅影响预期 symbol + 新增针对该期行为的回归测试。

---

## 7. 待评审决策点

1. `minimal` 地板 tier 的判定阈值 (无关键词 + 单服务 + 无依赖 → minimal?)
2. 用户显式降级是否需要 provenance,以及哪些 tier 禁止降级 (建议仅 audited 禁止)
3. 台账类产物从"阻断"改"收尾自动生成",由哪个环节负责生成
4. P4 是否纳入本轮 (动主干风险最高,可延后)

---

## 附:本方案的证据基础

均来自只读勘察 (未改动任何代码):

- `task_tier.py` (分级器全文)
- `clarification_gate.py` (澄清门禁全文)
- `clarification_flow.py` (澄清事务控制器全文)
- `lifecycle_policy.py` (生命周期 todo 主干)
- `preflight.py:85` (dispatch 前置闸)
- 上一轮已确认:澄清门禁 4 子门禁 AND 放行结构
