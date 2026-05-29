# E2E Dev Harness 深度分析

## 一、一句话概括

**E2E Dev Harness 是一个「不让 AI agent 乱写代码」的控制系统。** 它通过文件锁、机器可检门禁、状态机和证据链，强制 AI agent 按照一个严格的软件工程流程（需求澄清→设计审查→TDD→代码审查→完成验证）来交付功能，而不是拿到任务就直接写代码。

---

## 二、为什么要做这件事（设计动机）

当前 AI coding agent（Claude Code、Codex、Gemini CLI 等）有一个共同问题：**它们倾向于跳过思考直接写代码**。具体表现为：

1. **需求没澄清就开始实现** — 拿到一句 "加个退款功能" 就直接改 PaymentService
2. **不写测试直接写业务代码** — 跳过红/绿测试循环
3. **自己写自己审** — 缺乏独立审查
4. **跨服务改东西不通知上下游** — 改了支付服务的接口，忘了通知结算服务
5. **写完就宣布完成** — 没有可追溯的证据证明真的测过了

Harness 要解决的就是：**把 agent 的「自由发挥」变成「受控流程」**。

---

## 三、核心设计思路：用「状态机 + 文件锁 + 证据链」控制 Agent

### 3.1 状态机（Run State）

每次开发任务启动时，Harness 创建一个 `run-state.json`，记录当前处于哪个生命周期阶段：

```
CREATED → CLARIFIED → PLANNED → SERVICE_DESIGN_REQUIRED → IMPLEMENTED → REVIEWED → COMPLETED
```

Agent 不能跳阶段。比如还没 CLARIFIED（需求澄清），就不能进入 PLANNED。状态转换必须有对应的证据文件才能触发。

### 3.2 文件锁（Phase Lock）

这是最关键的物理约束。`start` 命令创建 `.phase-lock` 文件。**只要状态还没到 `IMPLEMENTED`，`phase_guard.py` 会拦截所有对生产代码的写入操作。**

实现方式：
- 在 Claude Code 中，通过 `settings.json` 配置 pre-tool hook，每次 Edit/Write 工具调用前先跑 `phase_guard.py`
- 在 Codex/Gemini 中，通过类似的 pre-action hook 模板
- `phase_guard.py` 检查 `.phase-lock`，如果生命周期不是 `IMPLEMENTED`，返回 exit code 2（拒绝写入）

**这就是为什么它能做到控制 — 它不是靠 prompt 劝说 agent，而是靠文件系统的锁和 hook 机制物理阻止不该发生的操作。**

### 3.3 证据链（Evidence）

每个阶段完成需要提交证据文件，机器可验证：

| 阶段 | 需要什么证据 |
|------|-------------|
| 需求澄清 | 填好的设计文档（goal、non-goal、AC、用例、测试设计） |
| TDD Red | 失败的测试命令输出（exit_code != 0） |
| TDD Green | 通过的测试命令输出（exit_code == 0） |
| R1 设计审查 | 独立审查报告 |
| R2 测试审查 | 独立审查报告 |
| R3 实现审查 | 独立审查报告 + 每 AC 的代码路径追踪 |
| 完成 | 覆盖矩阵、实现清单、业务审查、依赖报告 |

证据不是自然语言声明，而是结构化的 JSON/Markdown 文件，脚本可以解析验证。

---

## 四、完整工作流程（15步）

```
用户请求
  │
  ▼
1. Prepare（准备）
   加载项目指令、扫描记忆、探测 Superpowers 可用性、刷新依赖图
  │
  ▼
2. Clarify（需求澄清）  ← 硬门禁
   用 brainstorming skill 澄清需求，填设计文档
   必须包含：goal、non-goal、影响的服务、用例、AC、测试设计、开放问题
   有未解决问题 → 不准往下走
  │
  ▼
3. R1 Design Review（设计审查）
   独立审查 agent 检查 AC 完整性、影响范围、安全路径
  │
  ▼
4. Plan（规划）
   选择 single/multi agent 模式，创建执行计划
  │
  ▼
5. Service Design Split（多服务拆分）  ← 仅多服务场景
   每个受影响服务获得独立设计切片
  │
  ▼
6. TDD Red（写失败测试）
   先写一个必然失败的测试，截图证据
  │
  ▼
7. R2 Test Review（测试审查）
   独立审查 agent 在写生产代码前检查测试覆盖
  │
  ▼
8. Dispatch/Claim（分派任务）
   多 agent 场景：每个 agent 认领自己的服务任务
  │
  ▼
9. TDD Green/Refactor（实现 + 重构）
   最小实现让测试通过，Superpowers 红绿重构循环
  │
  ▼
10. AC Progress Gate（AC 进度门禁）
    证明所有分配的 AC 都有覆盖行、实现清单行、通过的测试证据
  │
  ▼
11. R3 Implementation Review（实现审查）
    独立审查 agent 逐 AC 追踪代码路径
  │
  ▼
12. Completion Gate（完成门禁）
    每个 AC 都要有具体的代码引用和测试引用
  │
  ▼
13. Rework Loop（返工循环）  ← 如果发现问题
    创建返工项，回到最早需要的阶段
  │
  ▼
14. Strict Guard/Report（严格守卫）
    运行 verify --strict-workflow，捕获通过的记忆更新，报告证据
  │
  ▼
15. Trace/Archive（追踪归档）
    附加执行追踪和摘要，归档最终需求
```

---

## 五、它是怎么实现 Harness 的（技术架构）

### 5.1 脚本层（37 个 Python 脚本，共 13778 行）

核心入口是 `e2e_dev_harness.py`（1949 行），提供这些子命令：

| 命令 | 作用 |
|------|------|
| `start` | 创建运行、设计模板、阶段锁 |
| `next` | 告诉你当前可以做什么 |
| `clarify` | 机器检查设计文档完整性 |
| `prepare` | 依赖发现 |
| `plan` | 选择 agent 模式，创建归档 |
| `gate` | 执行阶段门禁 |
| `verify` | 一键跑完准备→澄清→门禁→Maven |
| `guard` | CI/hook 层面的严格守卫 |
| `agent-task` | 认领/完成 agent 任务 |
| `service-design` | 验证多服务设计切片 |

辅助脚本分工明确：

| 脚本 | 行数 | 职责 |
|------|------|------|
| `e2e_dev_harness.py` | 1949 | 主入口，子命令路由 |
| `orchestration_plan.py` | 946 | 多 agent 编排决策 |
| `reviewer_gate.py` | 901 | 审查门禁，确保独立且完整 |
| `implementation_gate.py` | 647 | 实现阶段门禁 |
| `cross_service_dependency_scan.py` | 728 | 跨服务依赖扫描 |
| `memory_capture.py` | 779 | 记忆选择与捕获 |
| `clarification_gate.py` | 462 | 需求澄清门禁 |
| `task_alignment_guard.py` | 377 | 任务漂移检测 |
| `handoff_gate.py` | 378 | agent 交接门禁 |
| `coverage_gate.py` | 364 | 覆盖率门禁 |
| `workflow_guard.py` | 345 | 工作流守卫（CI 用） |
| `artifact_registry.py` | 309 | 产物注册表 |
| `run_state.py` | 311 | 状态机管理 |
| `phase_guard.py` | ~200 | 文件锁守卫 |
| `test_impact_plan.py` | 319 | 测试影响计划生成 |
| `implementation_manifest.py` | 337 | 实现清单 |
| `spring_static_check.py` | 288 | Spring 静态检查 |
| `command_evidence.py` | ~110 | 命令证据记录 |
| `context_pack.py` | ~220 | agent 上下文打包 |
| `execution_trace.py` | ~240 | 执行追踪 |
| `checkpoint_gate.py` | ~200 | 检查点门禁 |
| `auto_transition.py` | ~170 | 自动状态转换 |
| `install_hooks.py` | ~160 | hook 安装 |
| `harness_policy.py` | ~180 | 策略验证 |
| `harness_verify.py` | ~220 | 回放验证 |
| `run_summary.py` | ~240 | 运行摘要 |
| `kg_refresh.py` | 248 | 知识图谱刷新 |
| `agent_scheduler.py` | 262 | agent 任务调度 |
| `superpowers_probe.py` | ~130 | Superpowers 可用性探测 |
| `contract_gate.py` | ~220 | 契约门禁 |
| `ac_progress_gate.py` | ~180 | AC 进度门禁 |
| `service_design_gate.py` | ~260 | 服务设计门禁 |
| `requirements_archive.py` | ~150 | 需求归档 |
| `rework_gate.py` | ~200 | 返工门禁 |
| `tdd_evidence.py` | ~220 | TDD 证据 |
| `task_tier.py` | ~150 | 任务层级 |
| `agent_instructions.py` | 361 | agent 指令加载 |

### 5.2 四个关键机制

**1) 阶段锁（Phase Lock）** — 物理阻止

```
.phase-lock 文件记录当前生命周期
hook 在每次 Edit/Write 前调用 phase_guard.py
phase_guard 检查锁状态 → 不在 IMPLEMENTED 阶段 → exit code 2 → 写入被拒绝
```

**2) 产物注册表（Artifact Registry）** — 全局追溯

```
每个计划产物记录：类型、所有者、路径、完成要求、状态、SHA-256
严格模式下所有产物必须存在且哈希匹配
用于 CI 回放和审计
```

**3) 返工路由（Rework Routing）** — 问题回退有规则

```
需求不清       → 回到 clarify
缺少用例       → 回到 use-case-design
缺少测试       → 回到 test-case-design
缺少代码/测试失败 → 回到 tdd-implement
跨服务契约问题 → 回到 plan
不允许直接打补丁跳过流程
```

**4) 审查独立性（Review Independence）** — 防止自己审自己

```
R1/R2/R3 必须是独立 agent 或独立 session
同一个 agent 不能写代码又审代码
审查报告必须包含：请求哈希、独立声明、上下文边界、无代码变更声明
```

### 5.3 工作流层级（Workflow Tiers）

不是所有任务都需要最严格的流程。四个层级，证据深度递增：

| 层级 | 包含内容 |
|------|---------|
| `basic` | 澄清 + 影响摘要 + 测试证据 + 完成证明 + 运行状态 |
| `standard` | `basic` + R1/R2/R3 审查 + 覆盖矩阵 + 需求归档 |
| `critical` | `standard` + GitNexus 影响 + 契约 + 服务计划 + 交接 + 严格守卫 |
| `audited` | `critical` + 策略回放 + 完成回放 + 状态历史 |

### 5.4 Agent 编排模式

| 模式 | 场景 | 行为 |
|------|------|------|
| `single` | 小改动、单服务、低风险 | 一个 agent 做，但 R1/R2/R3 仍需独立审查 |
| `single-review` | 单服务中等改动 | 一个 agent 开发，独立审查 session |
| `multi` | 跨服务、契约变更、高风险 | 多个独立 agent，每个负责自己的服务 |

### 5.5 项目文件结构

```
skills/e2e-dev-harness/
  SKILL.md                          # 主 skill 入口，229 行
  hooks/
    claude-code-settings.example.json   # Claude Code hook 模板
    codex-pre-action.example.json       # Codex hook 模板
    gemini-pre-action.example.json      # Gemini hook 模板
  ci/
    github-actions-harness.yml          # GitHub Actions CI 模板
  references/                        # 17 个参考文档
    agent-orchestration.md              # Agent 编排详解
    agent-handoff-schema.md             # Agent 交接模式
    clarification-gate.md               # 需求澄清门禁
    common-review-issues.md             # 常见审查问题
    exec-plan.md                        # 执行计划模板
    execution-control.md                # 执行控制（阶段锁）
    implementation-gates.md             # 实现门禁（最详细）
    kg-tool-selection.md                # 知识图谱工具选择
    memory-integration.md               # 记忆集成
    platform-compatibility.md           # 平台兼容性
    requirements-archive.md             # 需求归档
    review-profiles.md                  # 审查配置文件
    superpowers-integration.md          # Superpowers 集成
    tdd-java-spring.md                  # Java/Spring TDD 附则
    agent-instructions.md               # Agent 指令加载
  review-profiles/                    # 审查配置
    default.json
    security-heavy.json
    api-first.json
  scripts/                           # 37 个 Python 脚本
    e2e_dev_harness.py                  # 主入口（1949 行）
    ...
tests/
  test_e2e_dev_harness_scripts.py    # 测试（9267 行）
```

---

## 六、为什么能做到（能力根源）

1. **不依赖 prompt 劝说** — Harness 不靠"请你先做需求分析"这种软约束，而是靠文件锁和 hook 物理拦截
2. **状态机是文件级的** — `run-state.json` 写在磁盘上，任何 agent 都能读写，状态不依赖某个 agent 的上下文
3. **证据是机器可验的** — 不是"我测过了"，而是结构化 JSON（命令、exit_code、输出哈希）
4. **Agent 中立** — 不绑定 Claude Code。任何能读 SKILL.md + 执行 Python 的 runtime 都能用
5. **可回放** — 保存了完整的状态、产物注册表、执行追踪，CI 或事后审计可以完整回放
6. **有 9267 行测试** — `tests/test_e2e_dev_harness_scripts.py` 覆盖了这些脚本的行为

---

## 七、与其他系统的关系

```
                    ┌──────────────┐
                    │ Superpowers  │  ← 通用 skill 层
                    │  brainstorm  │    提供 brainstorming、TDD 等方法论
                    │  TDD skill   │
                    └──────┬───────┘
                           │ 引用但不依赖
                    ┌──────┴───────┐
                    │ E2E Dev      │  ← 这个 skill
                    │   Harness    │    提供状态机、门禁、锁、证据
                    └──────┬───────┘
                           │ 使用
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ GitNexus │ │ Graphify │ │ Memory   │
        │ 代码级    │ │ 文档级    │ │ 上下文级  │
        │ 影响分析  │ │ 知识图谱  │ │ 选择性加载│
        └──────────┘ └──────────┘ └──────────┘
```

- **GitNexus** — 代码级跨服务依赖、影响分析（硬证据来源）
- **Graphify** — 文档、ADR、架构语义（辅助上下文）
- **Memory** — 可选上下文，不是权威来源
- **Superpowers** — 提供 brainstorming 和 TDD 的方法论，Harness 引用但不强制要求

---

## 八、适用场景

| 场景 | 是否适合 |
|------|---------|
| 单服务小改动（改个文案、加个字段） | 用 `basic` 层级即可 |
| 单服务功能开发（新 API、新业务逻辑） | 用 `standard` 层级 |
| 跨服务改动（改接口、加 MQ 消息） | 用 `critical` 层级 + `multi` 模式 |
| 支付/退款/安全/审计相关 | 用 `audited` 层级 |
| 纯探索性任务 | 不需要 Harness |

---

## 九、关键数据总结

| 指标 | 数值 |
|------|------|
| Python 脚本数量 | 37 个 |
| 脚本总代码量 | 13,778 行 |
| 最大脚本 | `e2e_dev_harness.py`（1,949 行） |
| 参考文档数量 | 17 个 |
| SKILL.md 行数 | 229 行 |
| 测试代码量 | 9,267 行 |
| 工作流步骤 | 15 步 |
| 工作流层级 | 4 级（basic/standard/critical/audited） |
| Agent 模式 | 3 种（single/single-review/multi） |
| 门禁类型 | 7 种（clarify/planning/implementation/completion/AC-progress/service-design/checkpoint） |
| 支持的 Agent Runtime | Claude Code / Codex / Gemini CLI / OpenCode / CI |
| 支持的技术栈 | Java 21 / Spring Framework 6.x / Maven |

---

## 十、总结

E2E Dev Harness 的本质是 **"给 AI agent 戴上脚镣跳舞"**：

- **脚镣**：文件锁阻止乱写、状态机阻止跳步、门禁脚本阻止蒙混
- **跳舞**：15 步工作流仍然允许 agent 完成复杂的多服务 Java/Spring 开发，只是必须按规矩来
- **可审计**：每一步都有磁盘上的证据文件，可以事后回放验证

它不是框架，不是库，而是一套 **可执行的流程控制脚本 + SKILL.md 指令**，让任何 AI agent runtime 都能按照严格的软件工程标准交付功能。
