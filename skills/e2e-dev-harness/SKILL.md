---
name: e2e-dev-harness
description: Default canonical delivery harness. Use when a feature/bugfix/refactor needs a multi-agent dev workflow that reliably runs to completion — clarification, TDD, review, verification — with a single source of truth, declarative tier-scaled gates, and worker subagents that self-load Superpowers skills.
---

# E2E Dev Harness

把需求变成"澄清→TDD→实现→(审查)→验证"的多 agent 流程,**保证跑到 VERIFIED**。

## Coordinator 纪律 (控制面 only)

- 你只读 run-state、发 worker packet、记证据、推进主干。**不**做本地代码探索/设计/TDD/审查/实现。
- worker packet 是**指针**(role + skill + context_paths + expected_outputs),worker 子 agent **首动作是 invoke 自己的 skill**,方法委派给 Superpowers。
- 每步看 `navigation_map`:全旅程 `CREATED→…→VERIFIED`,始终对照终点目标,避免局部最优。

## 6 动词

```bash
S=skills/e2e-dev-harness/scripts/e2e_dev_harness.py
# 含中文/非 ASCII 的需求：写进 UTF-8 文件用 --request-file/--feature-file，避免
# Windows/git-bash 控制台编码把 argv 损坏（损坏会被 start 显式拒绝，不再静默降级）。
printf '%s' "<原始需求>" > /tmp/req.txt
PYTHONUTF8=1 python $S start --repo . --feature "<feat>" --request-file /tmp/req.txt  # 创建唯一 run-state
# 纯 ASCII 时也可直接：python $S start --repo . --feature "<feat>" --request "<req>"
python $S next   --state <run-state>     # 推进主干或返回单一 blocker + navigation_map
python $S dispatch --state <run-state>   # 产出当前阶段的指针 worker packet
python $S submit --state <run-state> --phase <P> --key <k> --path <p>  # 记录 worker 证据
python $S gate   --state <run-state>     # 跑当前阶段声明式门禁
python $S status --state <run-state>     # 人读导航地图
```

## 循环 (单游标 + 多轨 beat)

`start` → 循环 → 直到 `VERIFIED`。两种节奏由 `next` 返回的 `region` 决定:

**prologue / epilogue (单游标):** `next` → 若 `complete` 收尾;否则 `dispatch` 当前阶段 → spawn 1 个 worker 子 agent(自加载 `next_action.skill`)→ worker `submit` 证据 → 回到 `next`。

**module_band (多轨 beat):** `next` 返回 `tracks_frontier`(每条活跃轨一个 blocker)。**一个 beat** = 一次并发循环:

1. `next` → 看到 `tracks_frontier`(独立轨可处不同 base 阶段)。
2. `dispatch` → band 区一次拿到整批 descriptor,按轨记 `tracks[m].dispatch = dispatched`。
3. coordinator **一个回合**发 N 个 `Task`/`spawn_agent` 并 `await` 全部 ← 真并发在这里。
4. 各 worker `submit` 自己的 namespaced 证据(经 `run_state.mutate` 串行化)。
5. `next` 对账:所有过 gate 的轨推进;失败轨进轨内 rework(**不卡兄弟轨**);新解锁的依赖轨进下一拍 frontier。

循环 beat 直到所有轨 complete → join → `region=epilogue`、`current_phase=VERIFIED`。

> harness 仍是纯控制面:`tracks_frontier` 只是并行**意图**,真正并发 spawn 永远是 coordinator 的工具调用。`current_phase` 是派生的"领头游标",单游标读者(guards/gate/navigation)照常工作。

## tier 与流水线 (M2)

`start --tier <t>` selects the pipeline. The default `auto` classifies the request text; use `minimal` only when explicitly pinned:

| tier | 活跃阶段 | 说明 |
|---|---|---|
| `minimal` | CREATED→CLARIFIED→RED→IMPLEMENTED→VERIFIED | 跳过 PLANNED/REVIEWED |
| `standard` | 全主干 | 单 reviewer |
| `critical` | 全主干 | REVIEWED 派 r1/r2/r3 三份独立 review(隔离上下文,不 review 自己实现) |
| `audited` | 全主干 | r1/r2/r3 + VERIFIED 用 `verification`+`audit_replay`(命令证据背书的 manifest)+`agent_team_dispatch`(dispatch-invocation),**不含** scope_manifest |

### Tier recommendation contract

`start --tier auto` emits and persists `tier_recommendation`. Its `options`
list contains `minimal`, `standard`, `critical`, and `audited` choices with
cost and reason summaries.

- `recommended_tier`: highest floor justified by request text, scanner scope,
  and GitNexus impact evidence.
- `selected_tier`: actual tier used for the run.
- Auto selection uses the recommendation.
- Explicit `--tier` selections are preserved even when below the
  recommendation. In that case downgrade metadata records
  `requested_below_recommended`, `requires_provenance=true`, and `blocked=false`
  under the current contract.

GitNexus impact evidence raises the recommendation for MEDIUM, HIGH, or
CRITICAL risk. Missing GitNexus verification on cross-service dependencies
must stay visible in `tier_recommendation.reasons`.

### Tier preview confirmation

Use `start --preview-tier` when Codex should show the user the recommended
workflow before creating a run. The command emits `tier-preview.v1`, includes
the same `tier_recommendation` options as normal `start`, and does not create
`run-state.json`.

Codex should present the recommendation, tier costs, and GitNexus/scanner
reasons to the user. After the user chooses, create the real run with
`start --tier <choice>` using the same repo, feature, request, adapter, scan,
and pipeline inputs.

Do not implement this as a stdin prompt. The CLI remains JSON-only and
non-interactive; the user choice happens in the coordinator conversation.

裁剪是结构性的:被跳阶段从计算出的 spine 移除,`next` 越过、导航地图渲染 `– skipped`。每个内建 tier 都过 I2 门禁闭包(`gate_closure_ok`)。门禁校验**真实产物**(文件存在+非空+哈希;`failing_tests`/`passing_tests` 须为命令证据且退出码正确)。
## Agent-Team Dispatch Boundary

`dispatch` has an agent-team planning layer between lifecycle phases and
runtime descriptors:

```text
pipeline phase -> agent_team provider/profile -> worker packet(s) -> runtime adapter -> descriptor(s)
```

The lifecycle phase still defines required evidence. The builtin agent-team
provider decides how many workers should produce that evidence. Runtime adapters
translate one worker packet into a Codex, Claude Code, OpenCode, or manual
descriptor. Gates still decide phase transitions from evidence keys; an
agent-team plan never passes a gate by itself.

Default single-worker phases preserve the legacy top-level worker packet and
`worker_descriptor` output. Multi-worker phases additionally include
`agent_team_plan`, `worker_descriptors`, and generated artifacts under the run
directory:

- `agent-team-plan.json`
- `dispatch-invocations/<phase>-<timestamp>.json`

Bundled profiles live in `agent-teams/default-*.yaml`. Project-local profiles
must be explicitly selected with `--team-profile` and should live under
`.e2e/agent-teams/`.
