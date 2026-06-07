# Harness v2 — 跨 session 交接 (Handoff)

**更新**: 2026-06-07 · **分支**: `master`(本地,未 push)· **状态**: M1 完成并合入 master

新 session 读这一个文件即可接续。

---

## 已完成 (DONE)

- **设计**: [specs/2026-06-07-harness-v2-redesign-design.md](specs/2026-06-07-harness-v2-redesign-design.md) — 全量架构 M1–M5(§14 是里程碑分解)。
- **M1 走骨架**: 计划 [plans/2026-06-07-harness-v2-m1-walking-skeleton.md](plans/2026-06-07-harness-v2-m1-walking-skeleton.md);代码 `skills/e2e-dev-harness-v2/`。
  - SSOT run-state、声明式可终止主干、单 dispatch 枚举、派生导航地图、6 动词 CLI、minimal tier。
  - 不变量 **I1(可终止)**、**I2(门禁闭包)** 已编码为测试;e2e `start→VERIFIED` 在 ≤6 步终止。
  - **v2 套件 25 passed;旧套件 1266 passed**(未受影响)。
  - 4 个 minimal 路径 worker skill 已委派 Superpowers(brainstorming / TDD / verification-before-completion);packet 为指针式。
- master 顶部: `e0b7936`(gate-streamlining/SSOT 设计 WIP)→ `97f3975`(M1 收尾)。

---

## 未完成 (TODO)

### A. v2 后续里程碑(各自 spec→plan→execute,新 session 各一)
- **M2 后端完整**: standard/critical/audited tier;**结构化阶段裁剪**(spec §11);r1/r2/r3 独立 review fan-out;把现有 `skills/e2e-dev-harness/scripts/` 的 scanner / KG 证据 / `task_tier.py` / hashing / memory / runtime adapters **port 到 v2 窄接口**(`spawn_worker(packet)->handle`)。对齐后端 golden fixtures。
- **M3 配置层**: `pipelines/*.yaml` + `validate-pipeline`(对任意配置跑 I1/I2 校验)+ 用户自定义流水线(spec §12)。
- **M4 前端适配**: 实现 `DomainAdapter`(scan / test_runner / review_profile / gate_bindings)前端版(spec §13);同一核心驱动前端 fixture 到 VERIFIED。
- **M5 切换**: v2 设默认、迁移文档、删旧 `e2e-dev-harness` skill(确认无能力损失)。

### B. 旧 harness 的 gate-streamlining WIP(独立于 v2)
- `e0b7936` 已把设计/计划文档合入 master,但**实现可能未完成**。相关计划:
  `plans/2026-06-07-gate-streamlining.md`、`plans/2026-06-07-control-plane-ssot.md`、`plans/2026-06-07-phase-skill-capabilities-ssot.md`。
  新 session 需确认这些计划是否还要在**旧** harness 上落地,还是随 M5 废弃旧 harness 而作废。

### C. housekeeping
- **未 push**: master 本地领先 origin/master ~62 commit。需要时 `git push`(用户决定)。
- **运行时残留未跟踪**(已故意不提交): `docs/agent-runs/nonexistent/`、`skills/e2e-dev-harness/scripts/.e2e/`、`snapshots/`。建议加入 `.gitignore`。
- **GitNexus 索引陈旧**(last indexed 4eba02d):新 session 早期跑 `npx gitnexus analyze`,使 impact 分析覆盖 `e2e-dev-harness-v2/`。
- 分支 `codex/clarification-bash-reduction` 仍在(==master),可删可留。

---

## 新 session 起手 prompt(M2)

> 读 `docs/superpowers/specs/2026-06-07-harness-v2-redesign-design.md` §14 与 `docs/superpowers/HANDOFF-harness-v2.md`。先早期跑 `npx gitnexus analyze`。然后用 superpowers:writing-plans 写 **M2(后端完整)** 计划并执行:standard/critical/audited tier、结构化阶段裁剪、r1/r2/r3 review fan-out、把 scanner/KG/task_tier/memory/runtime-adapters port 到 v2 窄接口。从 master 开新分支工作。

## 成本经验
本次 subagent 驱动执行成本偏高($170+)。建议:实现型 subagent 用批量(把紧耦合小任务合并为一次派发),用测试做每任务门禁,最后一次性总评审;避免每任务两阶段独立 review 的 ~30 次派发。
