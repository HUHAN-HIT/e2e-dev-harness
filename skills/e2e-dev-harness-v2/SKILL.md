---
name: e2e-dev-harness-v2
description: Use when a feature/bugfix/refactor needs a multi-agent dev workflow that reliably runs to completion — clarification, TDD, review, verification — with a single source of truth, declarative tier-scaled gates, and worker subagents that self-load Superpowers skills.
---

# E2E Dev Harness v2

把需求变成"澄清→TDD→实现→(审查)→验证"的多 agent 流程,**保证跑到 VERIFIED**。

## Coordinator 纪律 (控制面 only)

- 你只读 run-state、发 worker packet、记证据、推进主干。**不**做本地代码探索/设计/TDD/审查/实现。
- worker packet 是**指针**(role + skill + context_paths + expected_outputs),worker 子 agent **首动作是 invoke 自己的 skill**,方法委派给 Superpowers。
- 每步看 `navigation_map`:全旅程 `CREATED→…→VERIFIED`,始终对照终点目标,避免局部最优。

## 6 动词

```bash
S=skills/e2e-dev-harness-v2/scripts/e2e_dev_harness_v2.py
python $S start --repo . --feature "<feat>" --request "<原始需求>"   # 创建唯一 run-state
python $S next   --state <run-state>     # 推进主干或返回单一 blocker + navigation_map
python $S dispatch --state <run-state>   # 产出当前阶段的指针 worker packet
python $S submit --state <run-state> --phase <P> --key <k> --path <p>  # 记录 worker 证据
python $S gate   --state <run-state>     # 跑当前阶段声明式门禁
python $S status --state <run-state>     # 人读导航地图
```

## 循环

`start` → 循环{ `next` → 若 `complete` 收尾;否则 `dispatch` 当前阶段 → spawn worker 子 agent(自加载 `next_action.skill`)→ worker `submit` 证据 → 回到 `next` } 直到 `VERIFIED`。

## tier 与流水线 (M2)

`start --tier <t>` 选择流水线(默认 `minimal`,`auto` 由请求文本分类):

| tier | 活跃阶段 | 说明 |
|---|---|---|
| `minimal` | CREATED→CLARIFIED→RED→IMPLEMENTED→VERIFIED | 跳过 PLANNED/REVIEWED |
| `standard` | 全主干 | 单 reviewer |
| `critical` | 全主干 | REVIEWED 派 r1/r2/r3 三份独立 review(隔离上下文,不 review 自己实现) |
| `audited` | 全主干 | r1/r2/r3 + VERIFIED 增 audit_replay 证据 |

裁剪是结构性的:被跳阶段从计算出的 spine 移除,`next` 越过、导航地图渲染 `– skipped`。每个内建 tier 都过 I2 门禁闭包(`gate_closure_ok`)。门禁校验**真实产物**(文件存在+非空+哈希;`failing_tests`/`passing_tests` 须为命令证据且退出码正确)。
