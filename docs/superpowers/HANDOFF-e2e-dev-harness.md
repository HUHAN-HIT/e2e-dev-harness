# Harness e2e-dev-harness �?�?session 交接 (Handoff)

**更新**: 2026-06-07 · **分支**: `master`(本地,�?push)· **状�?*: M1 完成、合�?master,并已端到端复�?
�?session 读这一个文件即可接续�?
---

## 已完�?(DONE)

- **设计**: [specs/2026-06-07-e2e-dev-harness-redesign-design.md](specs/2026-06-07-e2e-dev-harness-redesign-design.md) �?全量架构 M1–M5(§14 是里程碑分解)�?- **M1 走骨�?*: 计划 [plans/2026-06-07-e2e-dev-harness-m1-walking-skeleton.md](plans/2026-06-07-e2e-dev-harness-m1-walking-skeleton.md);代码 `skills/e2e-dev-harness/`�?  - SSOT run-state、声明式可终止主干、单 dispatch 枚举、派生导航地图�? 动词 CLI、minimal tier�?  - 不变�?**I1(可终�?**�?*I2(门禁闭包)** 已编码为测试;e2e `start→VERIFIED` �?�? 步终止�?  - 4 �?minimal 路径 worker skill 已委�?Superpowers(brainstorming / TDD / verification-before-completion);packet 为指针式�?- **M1 端到端复�?2026-06-07)**: 重跑测试 + 全量人工代码审视,详见下方"复核结论"�?  - 重跑结果:**e2e-dev-harness 套件 25 passed;旧套�?1266 passed + 81 subtests**(34s,未受影响)�?  - 代码与计划逐文件一�?实现干净精简,M1 出口标准**真实达成**�?- master 顶部: `aa8d186`(handoff 文档)�?`e0b7936`(gate-streamlining/SSOT 设计 WIP)�?`97f3975`(M1 收尾)�?
---

## M1 端到端复核结�?(2026-06-07)

> 一句话:**M1 真实达成其出口标�?且无需返工**;以下"限制"都是 spec 明确延后的范围项,不是缺陷。但其中两条是设计核心承�?"跑到底且有真实质�?)�?*承重�?*,M2/M3 必须落地,**别把 M1 误当�?已能干活"**�?
### 承重风险(M2/M3 必须解决,优先级最�?

| # | 现象 | 影响 | 何时必修 |
|---|---|---|---|
| **R1** | **门禁只校�?证据键存�?,不校验产物本身�?* `gates.gate_passes` 仅判�?`key in evidence` 字典;从不检�?path 指向的文件是否存�?有内容。e2e 测试正是�?*不存在的假路�?*(`{phase}-{key}.md`)一路推�?VERIFIED�?| **终止性是真的,"完成�?是假�?*——coordinator 提交垃圾路径也能过门。M1 �?能跑到底的空�?,不是"能保证质量的流程"�?| **M2**:�?`hash_artifacts`/`command_evidence`,门禁校验文件存在+哈希+命令证据�?|
| **R2** | **I2(`gate_closure_ok`)无运行时强制�?* 只在单测里对硬编�?minimal 流水线断言一�?任何 CLI 命令都不调用它�?| 当前唯一内建流水线下安全。一�?**M3** 引入 `pipelines/*.yaml` / 自定义流水线,没有任何东西在执行前跑闭包校�?�?设计要根治的"门禁不可满足死锁"�?*原样复活**。spec §12 要求�?`validate-pipeline` 命令**尚不存在**�?| **M3**:实现 `validate-pipeline`,并在 `start`/`next` 早期对当前流水线�?I1/I2 运行时守卫�?|

### 已知限制(范围�?�?spec 延后;记下以免遗忘)

| # | 现象 | 与设计差�?| 归属 |
|---|---|---|---|
| L1 | **导航地图�?design §10 薄�?* 现有:phases+status(done/current/pending/skipped)、goal、you_are_here、progress "n/5"。缺:(a) blocked "�? 独立�?被阻阶段现渲染为 `current`);(b) 每阶段门禁证据摘�?"gate: X �?�?");(c) 距目标门�?"�?2 �?);(d) next 动作框在地图�?现为 sibling 字段)�?| 计划已显式把"blocked 细分"延后�?M2。反局部最优的"全旅程富信息"只兑现了一半�?| M2 |
| L2 | **DispatchStatus 5 值中 3 个是死值�?* �?`DISPATCHED`(dispatch 命令)�?`DONE`(submit)被写�?`PENDING`/`RUNNING`/`FAILED` 从不�?读�?*�?worker 失败路径**——worker 失败时无状态表�?coordinator 只能"永不 submit"�?| 单枚举落地了,但生命周期被压成 DISPATCHED→DONE�?| M2(�?FAILED + 重试/blocker 语义) |
| L3 | **worker 派发�?约定�?,非自动化�?* CLI `dispatch` �?*产出 packet**;真正 spawn �?agent �?coordinator(Claude)�?SKILL.md �?Agent 工具完成。自动化 e2e 测试�?真实 worker 派发证明终止"是由测试直接 submit 证据**模拟**的——CLI 从不 spawn�?| �?M1 正确(spawn �?agent loop 不在 Python)。但**尚无"真子 agent 跑�?的自动化 e2e**,只有机械�?CLI 终止测试�?| M2/手验 |
| L4 | **PLANNED / REVIEWED 两个 worker skill 未改造�?* �?minimal 路径 4 �?skill 转成 Superpowers 委派�?`e2e-harness-planning`、`e2e-harness-review` 仍引用旧 CLI、未委派�?| 符合 M1 范围(minimal 跳过这两阶段),但是 M2 standard/critical tier 的前置�?| M2 |

### 健壮性小�?廉价、择�?

- **L5** `run_state.load` �?schema 版本校验(�?`json.loads`)——损�?不兼容文件会变成下游莫名 KeyError 而非清晰报错�?- **L6** `run_state.save` 非原子写(直接 `write_text`)——崩在写一半会截断**唯一 SSOT**。单 coordinator 风险�?�?SSOT 值得 temp+rename 原子替换�?- **L7** 未知 pipeline/phase 抛裸 `KeyError`:`main()` �?try/except �?变成未捕�?traceback、exit 1�?*�?JSON stdout**,破坏"每命令出 JSON"契约(�?run-state �?`pipeline` 值非法会�?`next` �?�?- **L8** `gate` 动词不被文档化主循环触发(loop �?next→dispatch→submit→next),仅作人工/调试;�?e2e 覆盖其契�?�?unit �?`gate_passes`)�?
---

## 未完�?(TODO)

### A. e2e-dev-harness 后续里程�?各自 spec→plan→execute,�?session 各一)
- **M2 后端完整**: standard/critical/audited tier;**结构化阶段裁�?*(spec §11);r1/r2/r3 独立 review fan-out;把现�?`skills/e2e-dev-harness/scripts/` �?scanner / KG 证据 / `task_tier.py` / hashing / memory / runtime adapters **port �?e2e-dev-harness 窄接�?*(`spawn_worker(packet)->handle`)。对齐后�?golden fixtures�?  - **承接复核**: 落地 **R1**(门禁校验真实产物:文件存在+哈希+命令证据)�?*L1**(导航地图�?blocked/门禁摘要/距目�?�?*L2**(FAILED 路径+重试)�?*L4**(改�?planning/review �?skill)�?- **M3 配置�?*: `pipelines/*.yaml` + `validate-pipeline`(对任意配置跑 I1/I2 校验)+ 用户自定义流水线(spec §12)�?  - **承接复核**: 落地 **R2**(I2/I1 运行时强�?,否则自定义流水线会复活死锁�?- **M4 前端适配**: 实现 `DomainAdapter`(scan / test_runner / review_profile / gate_bindings)前端�?spec §13);同一核心驱动前端 fixture �?VERIFIED�?- **M5 切换**: e2e-dev-harness 设默认、迁移文档、删�?`e2e-dev-harness` skill(确认无能力损�?�?
### B. �?harness �?gate-streamlining WIP(独立�?e2e-dev-harness)
- `e0b7936` 已把设计/计划文档合入 master,�?*实现可能未完�?*。相关计�?
  `plans/2026-06-07-gate-streamlining.md`、`plans/2026-06-07-control-plane-ssot.md`、`plans/2026-06-07-phase-skill-capabilities-ssot.md`�?  �?session 需确认这些计划是否还要�?*�?* harness 上落�?还是�?M5 废弃�?harness 而作废�?
### C. housekeeping
- **�?push**: master 本地领先 origin/master **63 commit**。需要时 `git push`(用户决定)�?- **运行时残留未跟踪**(已故意不提交): `docs/agent-runs/nonexistent/`、`skills/e2e-dev-harness/scripts/.e2e/`、`snapshots/`。建议加�?`.gitignore`�?- **GitNexus 索引陈旧**(index 不覆�?`e2e-dev-harness/`):�?session 早期�?`npx gitnexus analyze`,�?impact 分析覆盖 e2e-dev-harness。port 叶子模块改旧 symbol 时按 CLAUDE.md 先跑 `gitnexus_impact`�?- **本地分支**: `codex/clarification-bash-reduction`、`codex/single-file-control-plane` 及若�?`claude/*` worktree 分支仍在,可按需清理�?
---

## �?session 起手 prompt(M2)

> 先读 **`docs/superpowers/specs/2026-06-07-e2e-dev-harness-m2-planning-input.md`**(M2 计划输入:R1/R1'出口硬标�?+ 功能�?+ 验收标准 + 受影响文�?直接喂给 writing-plans)。再�?`docs/superpowers/specs/2026-06-07-e2e-dev-harness-redesign-design.md` §14 与本文件(尤其"M1 端到端复核结�?)。先早期�?`npx gitnexus analyze`。然后用 superpowers:writing-plans �?**M2(后端完整)** 计划并执�?standard/critical/audited tier、结构化阶段裁剪、r1/r2/r3 review fan-out、把 scanner/KG/task_tier/memory/runtime-adapters port �?e2e-dev-harness 窄接口�?*M2 必须解决复核 R1(门禁校验真实产物)**,并捎�?L1/L2/L4。从 master 开新分支工作�?
## 成本经验
上一�?subagent 驱动执行成本偏高($170+)。建�?实现�?subagent 用批�?把紧耦合小任务合并为一次派�?,用测试做每任务门�?最后一次性总评�?避免每任务两阶段独立 review �?~30 次派发�?