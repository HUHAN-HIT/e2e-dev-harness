# e2e-dev-harness v2 — 整体重构设计规格 (Redesign Design Spec)

- **状态**: 已评审通过 (Approved) — 待转 writing-plans
- **日期**: 2026-06-07
- **范围**: e2e-dev-harness 全量编排核心重构(新目录),保留多 agent 调度
- **关联**: `docs/superpowers/specs/2026-06-07-gate-streamlining-design.md`(门禁精炼,本设计将其 tier 思想内建)
- **目标**: 让 harness 的工作流**能跑到底**(可终止),消除碎片化与 facade-over-legacy,核心只重写编排,叶子代码复用

---

## 0. 问题诊断 (为什么要重构)

| 证据 | 现象 |
|---|---|
| 1266 单测全绿,但流程"跑不到底" | 单元层正确,整体编排不可用——典型的逐步堆砌、缺整体设计 |
| `policies/lifecycle_policy.py` 是 "facade over the legacy coordinator guidance modules" | 双重/三重代码路径,facade 包 legacy,为兼容而保留 |
| dispatch 有 6+ 重叠状态(`awaiting_runtime_spawn`/`waiting_dispatch`/`worker_running`/`worker_running_unverified`/`worker_dispatched`/`dispatched`) | "在途"有多种表示 → 流程识别不出"已完成",卡死 |
| `dispatcher.py` 2195 行 + `coordinator_flow.py` 908 + `agent_scheduler.py` 853 + `control_plane.py` 794 | ~5k 行纠缠的状态机,是"跑不到底"的根因 |
| 35 个 CLI 子命令,大量重叠 | 命令面过大,记不住也串不起来 |

**结论**: 编排核心(状态机/调度/门禁决策)需重建;叶子模块(scanner/KG/tier/hash/memory)相对干净、可复用。

## 0.1 已确认决策 (来自评审)

| # | 决策点 | 结论 |
|---|---|---|
| D1 | 路线 | **A 重建编排核心 + 复用叶子**(非全量绿地重写,非原地修补) |
| D2 | 多 agent | **保留** coordinator/worker 派发与上下文隔离 |
| D3 | 核心病灶 | 流程**跑不到底**(状态机+门禁+派发纠缠) |
| D4 | 上下文 | coordinator 只持有指针,worker 子 agent **自行加载 skill** |
| D5 | 方法复用 | 尽量复用 **Superpowers** 已验证 skill,其余 harness 专属胶水自持 |
| D6 | 导航 | 每步返回**整段旅程**导航地图,避免局部最优 |
| D7 | 适应性 | 按复杂度**裁剪环节**,且支持**用户自定义流程配置** |
| D8 | 领域 | 当前后端为主,架构预留**前端适配** seam |

---

## 1. 目录与共存

- 新包 **`skills/e2e-dev-harness-v2/`**(Python,与现状一致)。
- 旧 skill **原样保留可用**,v2 并行开发→端到端验证→成为默认→切换后才删除。任何时刻都有一个能用的 harness。
- **单一事实源 (SSOT)**: 整个 v2 的运行态只存一份 `run-state.json`(带版本化 schema)。无 facade-over-legacy,无并行状态存储。所有命令读写这一份文件。

---

## 2. 编排核心 — 主干 (terminating spine)

显式、小型状态机 `core/lifecycle.py`(目标 <300 行),沿用现有 7 阶段:

```
CREATED → CLARIFIED → PLANNED → RED → IMPLEMENTED → REVIEWED → VERIFIED
```

每个阶段是**一条声明式记录**:
```
Phase(name, entry_contract, worker_role, worker_skill, exit_gate, next_phase)
```

coordinator 主循环因此平凡且**保证可终止**:

> `next` = 读 state → 定位当前阶段 → exit_gate 通过则前进一阶;否则返回该阶段唯一的所需动作。

- 不再有 `coordinator_flow.py` 的 908 行决策树。
- **可终止性是结构性的**: 每次 `next` 要么恰好前进一个阶段,要么返回一个具体 blocker——不存在"返回空/无所适从"的状态。
- **不变量 I1 (termination)**: 从任意合法 state 出发,有限次 `next`(配合 worker 提交证据)必达 `VERIFIED` 或返回明确 blocker。

---

## 3. 单一派发协议 + 单一状态枚举

用**一个**生命周期替换 6+ 重叠状态:

```
pending → dispatched → running → done   (+ failed)
```

- 一个 `dispatch` 动词: coordinator 调用 → 得到 worker packet(role + 隔离上下文 + 期望产物)→ spawn 子 agent → worker 返回证据 → coordinator 记 `done`。
- 阶段前进当且仅当其 worker 任务 `done` **且** `exit_gate` 通过。
- 多 agent 隔离完全保留(worker 仍在全新上下文运行),但"在途"只有一种表示、"完成"只有一种表示。
- 不再保留 `worker_running_unverified` 等 legacy 别名(见 §5 Drop)。

---

## 4. 门禁/证据契约 — 声明式 + 随 tier 缩放

门禁是**数据,不是代码路径**。每阶段 `exit_gate` 是一组证据检查;每个检查由某个 worker 产出的具名 artifact 满足。风险 **tier**(内建 §0.1-D7,沿用 `task_tier` 思想)选择**哪些检查生效**:

- `minimal` → clarification + test-evidence + alignment(单 worker 一趟)
- `standard`/`critical`/`audited` → 逐级增加 impact、contracts、独立 r1/r2/r3 review、audit replay

- **不变量 I2 (gate-closure)**: 门禁**永不要求**没有任何 worker 被派去产出的证据。设计期校验:每条必需检查都映射到某阶段的 worker 产物。**此闭包校验根治"门禁无法满足"的死锁。**

> §4 的门禁证据 == §9 worker skill 的 `expected_outputs`(同一份清单,两个消费者)。

---

## 5. 取舍表 (port vs rewrite)

**从零重写**(纠缠核心,~5k 行 → 目标 ~1.2k):
`dispatcher.py`、`coordinator_flow.py`、`agent_scheduler.py`、`control_plane.py`、lifecycle facades、35 命令 CLI 派发。

**作为库 port**(干净叶子,逻辑不动,只包一层窄接口):
- `adapters/scanners/`(generic + java_spring AST)
- KG 证据集成(`kg-tool-selection`、GitNexus 调用)
- `task_tier.py` + golden tier fixtures
- hashing/evidence(`hash_artifacts`、`command_evidence`)
- memory capture
- runtime adapters(`claude_code`/`codex_multi_agent`/`opencode`/`manual`)→ 收敛到**一个** `spawn_worker(packet) -> handle` 接口

**Drop**(死代码/重复): legacy 状态别名、`worker_running_unverified` 兼容垫片、recover/timeline/gc(YAGNI,真实流程需要再加回)。

---

## 6. CLI 面 — 35 → 6 动词

| v2 动词 | 取代 | 作用 |
|---|---|---|
| `start` | start/prepare/install | 创建唯一 run-state |
| `next` | next/map/doctor/preflight/ac-progress | 推进主干或返回单一 blocker |
| `dispatch` | dispatch-next/-beat/-ack | 产出一个 worker packet |
| `submit` | dispatch-complete/-finish/handoff/hash | 记录 worker 证据 + 标记 done |
| `gate` | gate/verify/guard/clarify | 跑某阶段声明式 exit_gate |
| `status` | dispatch-status/timeline | 人读状态/导航地图 |

未映射的旧动词(recover/gc/service-design 等)为**显式延后**,spec "deferred" 段记录,非静默删除。

---

## 7. 构建策略 — 垂直切片优先

因核心病灶是"跑不到底",**第一里程碑就是一次完整端到端跑通**(minimal tier):
`start → next → dispatch(clarifier) → submit → … → VERIFIED`,带真实(可先 stub)worker 派发,证明可终止。
之后再逐增: 高 tier、独立 review fan-out(r1/r2/r3)、多服务切片、audited replay。每个 tier 都是在"已能跑完"的流程上的增量。

---

## 8. 测试策略

- **旧测试集 = 行为金标**: 不整体搬运;每个 port 的叶子模块保留其测试,tier golden fixtures 原样沿用。
- **新核心 TDD**(`superpowers:test-driven-development`): 先写两条不变量的测试——I1(状态机可终止)与 I2(门禁闭包)——这正是旧系统违反的两点。
- **一条 e2e 测试**: 驱动真实 fixture 仓库 `start → VERIFIED` 并断言**终止**——旧 harness 永远过不了的那条。

---

## 9. Worker skill 模型 & Superpowers 复用

**原则: coordinator 持指针,不持过程**——这是主 agent 上下文小的关键。

`dispatch` 产出的 worker packet 仅含:
```
{ role, skill, context_paths[], expected_outputs[] }   ← 指针,非指令
```
子 agent **首个动作是 invoke 自己被指定的 skill**。所有"怎么做"都在 worker skill 与其委派的 Superpowers skill 里,**永不进 coordinator**。coordinator 纯控制面: 读 state → 发 packet → 记证据 → 推进。

**worker skill 瘦身为委派器**(每个 `e2e-harness-<phase>` 缩为契约: 输入 / 必需产物(门禁消费的证据)/ 由哪个验证过的 skill 实际做):

| 阶段 | worker skill | 委派"怎么做"给(验证过) |
|---|---|---|
| CLARIFIED | e2e-harness-clarification | `superpowers:brainstorming` |
| PLANNED | e2e-harness-planning | `superpowers:writing-plans` |
| RED | e2e-harness-tdd-red | `superpowers:test-driven-development`(红) |
| IMPLEMENTED | e2e-harness-implementation | `superpowers:test-driven-development`(绿)+ `superpowers:systematic-debugging` |
| REVIEWED | e2e-harness-review | `superpowers:requesting-code-review` / `receiving-code-review` |
| VERIFIED | e2e-harness-completion | `superpowers:verification-before-completion` |

v2 只拥有 **harness 专属胶水**(上下文隔离、证据 schema、门禁契约);**方法**(如何澄清/TDD/review/verify)复用 Superpowers,不重造。Superpowers 无对应处(如多服务切片),worker skill 自持;若有更佳现成参考,优先采用。

现状: 六个 worker skill 已存在但为 16 行桩,引用旧 CLI、未委派 Superpowers——v2 在此基础上改造。

---

## 10. 导航地图 — 整段旅程感知 (避免局部最优)

**派生,不手维护**: 主干是一份声明式状态机、状态在一份 run-state,导航地图由两者**计算**得出,无独立地图可漂移。`next` 与 `status` 返回**同一份**全旅程视图:

```
CREATED ✓ → CLARIFIED ✓ → PLANNED ✓ → RED ▶ → IMPLEMENTED ○ → REVIEWED ○ → VERIFIED ◎(目标)
                                          └─ 你在这 · gate: test-evidence ✗(缺 1)· next: dispatch e2e-harness-tdd-red
```

每条响应携带:
- **整条主干** + 每阶段状态(`✓ done / ▶ current / ○ pending / ✗ blocked / – skipped`),始终看到全弧与**终点目标** `VERIFIED`。
- **you-are-here** + 当前阶段门禁摘要(证据有/缺)。
- **单一 next 动作**,但**框在旅程内**呈现。
- **进度 + 距目标**(如 "3/7 阶段,剩 2 门")。

**为何根治局部最优**: 全局目标(达 `VERIFIED`)与剩余路径在**每一步**可见,前进永远对照终点而非当前步。是 SSOT 契约(§1)的一部分,`next`(机读)与 `status`(人读)同源渲染。

---

## 11. 复杂度自适应流水线 (裁剪环节)

7 阶段主干是**最长路径**。tier 选择**哪些阶段运行**(不止门禁缩放):

| tier | 活跃阶段 |
|---|---|
| `minimal` | CREATED → CLARIFIED → RED → IMPLEMENTED → VERIFIED *(跳过 PLANNED, REVIEWED)* |
| `standard` | 全主干,单 reviewer |
| `critical` | 全主干 + r1/r2/r3 独立 review fan-out |
| `audited` | 全主干 + review + audit replay |

裁剪是**结构性**的: 被跳阶段从计算出的流水线中移除,`next` 越过它,导航地图渲染为 `– skipped`。两不变量(I1/I2)对**裁剪后**流水线重新校验——tier 不能跳过其产物仍被后续门禁需要的阶段。

---

## 12. 用户自定义环节 — 流水线即配置

主干**非硬编码**,是声明式流水线配置(`pipelines/*.yaml`)的默认条目。用户/项目可定义自定义流水线: 阶段顺序、每阶段绑定的 worker skill、每阶段门禁/证据集、tier 覆盖。状态机**解释**配置——内建 tier 只是出厂配置,无特权。

安全网: **任何配置运行前先过不变量校验** `validate-pipeline`(同 I1/I2: 是否可终止?每条必需证据是否都有某阶段 worker 产出?)。这让用户自由定制**而不**重造"跑不到底"死锁——架构拒绝运行不可满足的流水线。

---

## 13. 领域适配 seam (后端先行,前端后续)

随技术栈变化的部分收敛到**一个** `DomainAdapter` 接口:
```
DomainAdapter:
  scan(repo) -> services/components       # 后端: java_spring/generic AST;前端: routes/components
  test_runner                              # 后端: mvn/pytest;前端: vitest/jest/playwright
  review_profile                           # 哪些 review 检查重要
  gate_bindings / worker_skill_overrides   # 如前端 RED 用组件测试约定
```
**核心领域无关**: spine、dispatch 枚举、gates-as-data、导航地图、配置层从不提及前后端。后端先行(port 现有 scanner / `tdd-java-spring`)。前端是**实现同一接口的新 adapter**——核心零改动,即所要预留的"适配的地方"。默认 adapter 由 repo 标记自动识别,可在流水线配置覆盖。

---

## 14. 总体交付计划 (分期)

架构第一天就**容纳**上述全部能力;**实现**按 YAGNI 排序:

| 里程碑 | 交付 | 验证 |
|---|---|---|
| **M1 走骨架** | SSOT run-state、可终止主干、单 dispatch 枚举、导航地图、`minimal` 后端 tier、指针 packet worker 自加载 Superpowers | 旧 harness 过不了的那条 e2e: `start → VERIFIED` 终止 |
| **M2 后端完整** | standard/critical/audited tier、阶段裁剪、r1/r2/r3 review fan-out、port scanner/KG/task_tier/memory 至窄接口 | 后端 golden fixtures 行为对齐 |
| **M3 配置层** | 流水线即配置 + `validate-pipeline` 不变量校验 + 用户自定义流水线 | 自定义流水线可跑;不可满足流水线被拒 |
| **M4 前端适配** | 前端 `DomainAdapter`(scanner + test runner + review profile) | 同一核心驱动前端 fixture 仓库到 `VERIFIED` |
| **M5 切换** | v2 设默认、迁移文档、删旧 skill | 旧 harness 退役且无能力损失 |

---

## 15. 不变量与受影响节点

**两条架构不变量(贯穿设计,先写测试)**:
- **I1 termination**: 流程从任意合法 state 有限步可达 `VERIFIED` 或明确 blocker。
- **I2 gate-closure**: 任何(默认或用户)流水线中,每条必需证据都有某阶段 worker 产出。

**v2 为新目录,无对旧 symbol 的就地编辑**;旧 skill 在 M5 前不改。port 叶子模块时按 CLAUDE.md 对受影响 symbol 跑 `gitnexus_impact`。

---

## 16. 非目标 (YAGNI)

- 本轮不在 v2 实现前端逻辑(仅预留 adapter 接口,M4 才实现)。
- 不搬运 recover/gc/timeline,除非真实流程证明需要。
- 不整体搬运 1266 旧测试;仅 port 叶子模块连同其测试 + tier golden。
- 不在 M5 前改动旧 skill 行为。

---

## 17. 续接指引

实现从 M1 走骨架开始。下一步: 进 `superpowers:writing-plans` 出 M1 实现计划(TDD 先写 I1/I2 不变量红测)。
