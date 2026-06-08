# Harness v2 — 跨 session 交接 (Handoff)

**更新**: 2026-06-07 · **分支**: `master`(本地,未 push)· **状态**: M1 完成、合入 master,并已端到端复核

新 session 读这一个文件即可接续。

---

## 已完成 (DONE)

- **设计**: [specs/2026-06-07-harness-v2-redesign-design.md](specs/2026-06-07-harness-v2-redesign-design.md) — 全量架构 M1–M5(§14 是里程碑分解)。
- **M1 走骨架**: 计划 [plans/2026-06-07-harness-v2-m1-walking-skeleton.md](plans/2026-06-07-harness-v2-m1-walking-skeleton.md);代码 `skills/e2e-dev-harness-v2/`。
  - SSOT run-state、声明式可终止主干、单 dispatch 枚举、派生导航地图、6 动词 CLI、minimal tier。
  - 不变量 **I1(可终止)**、**I2(门禁闭包)** 已编码为测试;e2e `start→VERIFIED` 在 ≤6 步终止。
  - 4 个 minimal 路径 worker skill 已委派 Superpowers(brainstorming / TDD / verification-before-completion);packet 为指针式。
- **M1 端到端复核(2026-06-07)**: 重跑测试 + 全量人工代码审视,详见下方"复核结论"。
  - 重跑结果:**v2 套件 25 passed;旧套件 1266 passed + 81 subtests**(34s,未受影响)。
  - 代码与计划逐文件一致,实现干净精简,M1 出口标准**真实达成**。
- master 顶部: `aa8d186`(handoff 文档)← `e0b7936`(gate-streamlining/SSOT 设计 WIP)← `97f3975`(M1 收尾)。

---

## M1 端到端复核结论 (2026-06-07)

> 一句话:**M1 真实达成其出口标准,且无需返工**;以下"限制"都是 spec 明确延后的范围项,不是缺陷。但其中两条是设计核心承诺("跑到底且有真实质量")的**承重项**,M2/M3 必须落地,**别把 M1 误当成"已能干活"**。

### 承重风险(M2/M3 必须解决,优先级最高)

| # | 现象 | 影响 | 何时必修 |
|---|---|---|---|
| **R1** | **门禁只校验"证据键存在",不校验产物本身。** `gates.gate_passes` 仅判断 `key in evidence` 字典;从不检查 path 指向的文件是否存在/有内容。e2e 测试正是用**不存在的假路径**(`{phase}-{key}.md`)一路推到 VERIFIED。 | **终止性是真的,"完成度"是假的**——coordinator 提交垃圾路径也能过门。M1 是"能跑到底的空壳",不是"能保证质量的流程"。 | **M2**:接 `hash_artifacts`/`command_evidence`,门禁校验文件存在+哈希+命令证据。 |
| **R2** | **I2(`gate_closure_ok`)无运行时强制。** 只在单测里对硬编码 minimal 流水线断言一次;任何 CLI 命令都不调用它。 | 当前唯一内建流水线下安全。一旦 **M3** 引入 `pipelines/*.yaml` / 自定义流水线,没有任何东西在执行前跑闭包校验 → 设计要根治的"门禁不可满足死锁"会**原样复活**。spec §12 要求的 `validate-pipeline` 命令**尚不存在**。 | **M3**:实现 `validate-pipeline`,并在 `start`/`next` 早期对当前流水线跑 I1/I2 运行时守卫。 |

### 已知限制(范围项,按 spec 延后;记下以免遗忘)

| # | 现象 | 与设计差距 | 归属 |
|---|---|---|---|
| L1 | **导航地图比 design §10 薄。** 现有:phases+status(done/current/pending/skipped)、goal、you_are_here、progress "n/5"。缺:(a) blocked "✗" 独立态(被阻阶段现渲染为 `current`);(b) 每阶段门禁证据摘要("gate: X ✗ 缺1");(c) 距目标门数("剩 2 门");(d) next 动作框在地图内(现为 sibling 字段)。 | 计划已显式把"blocked 细分"延后到 M2。反局部最优的"全旅程富信息"只兑现了一半。 | M2 |
| L2 | **DispatchStatus 5 值中 3 个是死值。** 仅 `DISPATCHED`(dispatch 命令)与 `DONE`(submit)被写过;`PENDING`/`RUNNING`/`FAILED` 从不写/读。**无 worker 失败路径**——worker 失败时无状态表示,coordinator 只能"永不 submit"。 | 单枚举落地了,但生命周期被压成 DISPATCHED→DONE。 | M2(加 FAILED + 重试/blocker 语义) |
| L3 | **worker 派发是"约定式",非自动化。** CLI `dispatch` 只**产出 packet**;真正 spawn 子 agent 由 coordinator(Claude)按 SKILL.md 用 Agent 工具完成。自动化 e2e 测试里"真实 worker 派发证明终止"是由测试直接 submit 证据**模拟**的——CLI 从不 spawn。 | 对 M1 正确(spawn 在 agent loop 不在 Python)。但**尚无"真子 agent 跑通"的自动化 e2e**,只有机械的 CLI 终止测试。 | M2/手验 |
| L4 | **PLANNED / REVIEWED 两个 worker skill 未改造。** 仅 minimal 路径 4 个 skill 转成 Superpowers 委派器;`e2e-harness-planning`、`e2e-harness-review` 仍引用旧 CLI、未委派。 | 符合 M1 范围(minimal 跳过这两阶段),但是 M2 standard/critical tier 的前置。 | M2 |

### 健壮性小项(廉价、择机)

- **L5** `run_state.load` 无 schema 版本校验(裸 `json.loads`)——损坏/不兼容文件会变成下游莫名 KeyError 而非清晰报错。
- **L6** `run_state.save` 非原子写(直接 `write_text`)——崩在写一半会截断**唯一 SSOT**。单 coordinator 风险低,但 SSOT 值得 temp+rename 原子替换。
- **L7** 未知 pipeline/phase 抛裸 `KeyError`:`main()` 无 try/except → 变成未捕获 traceback、exit 1、**非 JSON stdout**,破坏"每命令出 JSON"契约(如 run-state 里 `pipeline` 值非法会让 `next` 崩)。
- **L8** `gate` 动词不被文档化主循环触发(loop 走 next→dispatch→submit→next),仅作人工/调试;无 e2e 覆盖其契约(仅 unit 级 `gate_passes`)。

---

## 未完成 (TODO)

### A. v2 后续里程碑(各自 spec→plan→execute,新 session 各一)
- **M2 后端完整**: standard/critical/audited tier;**结构化阶段裁剪**(spec §11);r1/r2/r3 独立 review fan-out;把现有 `skills/e2e-dev-harness/scripts/` 的 scanner / KG 证据 / `task_tier.py` / hashing / memory / runtime adapters **port 到 v2 窄接口**(`spawn_worker(packet)->handle`)。对齐后端 golden fixtures。
  - **承接复核**: 落地 **R1**(门禁校验真实产物:文件存在+哈希+命令证据)、**L1**(导航地图补 blocked/门禁摘要/距目标)、**L2**(FAILED 路径+重试)、**L4**(改造 planning/review 两 skill)。
- **M3 配置层**: `pipelines/*.yaml` + `validate-pipeline`(对任意配置跑 I1/I2 校验)+ 用户自定义流水线(spec §12)。
  - **承接复核**: 落地 **R2**(I2/I1 运行时强制),否则自定义流水线会复活死锁。
- **M4 前端适配**: 实现 `DomainAdapter`(scan / test_runner / review_profile / gate_bindings)前端版(spec §13);同一核心驱动前端 fixture 到 VERIFIED。
- **M5 切换**: v2 设默认、迁移文档、删旧 `e2e-dev-harness` skill(确认无能力损失)。

### B. 旧 harness 的 gate-streamlining WIP(独立于 v2)
- `e0b7936` 已把设计/计划文档合入 master,但**实现可能未完成**。相关计划:
  `plans/2026-06-07-gate-streamlining.md`、`plans/2026-06-07-control-plane-ssot.md`、`plans/2026-06-07-phase-skill-capabilities-ssot.md`。
  新 session 需确认这些计划是否还要在**旧** harness 上落地,还是随 M5 废弃旧 harness 而作废。

### C. housekeeping
- **未 push**: master 本地领先 origin/master **63 commit**。需要时 `git push`(用户决定)。
- **运行时残留未跟踪**(已故意不提交): `docs/agent-runs/nonexistent/`、`skills/e2e-dev-harness/scripts/.e2e/`、`snapshots/`。建议加入 `.gitignore`。
- **GitNexus 索引陈旧**(index 不覆盖 `e2e-dev-harness-v2/`):新 session 早期跑 `npx gitnexus analyze`,使 impact 分析覆盖 v2。port 叶子模块改旧 symbol 时按 CLAUDE.md 先跑 `gitnexus_impact`。
- **本地分支**: `codex/clarification-bash-reduction`、`codex/single-file-control-plane` 及若干 `claude/*` worktree 分支仍在,可按需清理。

---

## 新 session 起手 prompt(M2)

> 先读 **`docs/superpowers/specs/2026-06-07-harness-v2-m2-planning-input.md`**(M2 计划输入:R1/R1'出口硬标准 + 功能项 + 验收标准 + 受影响文件,直接喂给 writing-plans)。再读 `docs/superpowers/specs/2026-06-07-harness-v2-redesign-design.md` §14 与本文件(尤其"M1 端到端复核结论")。先早期跑 `npx gitnexus analyze`。然后用 superpowers:writing-plans 写 **M2(后端完整)** 计划并执行:standard/critical/audited tier、结构化阶段裁剪、r1/r2/r3 review fan-out、把 scanner/KG/task_tier/memory/runtime-adapters port 到 v2 窄接口。**M2 必须解决复核 R1(门禁校验真实产物)**,并捎带 L1/L2/L4。从 master 开新分支工作。

## 成本经验
上一轮 subagent 驱动执行成本偏高($170+)。建议:实现型 subagent 用批量(把紧耦合小任务合并为一次派发),用测试做每任务门禁,最后一次性总评审;避免每任务两阶段独立 review 的 ~30 次派发。
