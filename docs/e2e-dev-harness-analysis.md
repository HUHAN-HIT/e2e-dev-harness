# E2E Dev Harness 深度分析

> 最后更新：2026-05-31 | 版本：v0.2.0 | 基于 42 个脚本 / 18,787 行代码 / 751 个测试

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
6. **上下文膨胀导致质量下降** — 单个 agent 承担全流程，后期注意力涣散
7. **范围漂移** — 实现过程中不知不觉越改越多，偏离原始需求

Harness 要解决的就是：**把 agent 的「自由发挥」变成「受控流程」**。

---

## 三、核心设计思路：用「状态机 + 文件锁 + 证据链」控制 Agent

### 3.1 状态机（Run State）

每次开发任务启动时，Harness 创建一个 `run-state.json`，记录当前处于哪个生命周期阶段：

```
CREATED → CLARIFIED → SERVICE_DESIGN_REQUIRED → PLANNED → RED_READY → WAITING_DISPATCH → IMPLEMENTED → REVIEWED → REWORK_REQUIRED → VERIFIED → ARCHIVED
```

11 个状态，覆盖从创建到归档的完整生命周期。Agent 不能跳阶段——比如还没 CLARIFIED（需求澄清），就不能进入 PLANNED。状态转换必须有对应的证据文件 + 门禁通过记录才能触发，且每次转换都会写入 `history` 数组用于审计。

状态转换保护机制：
- 手动编辑 `.phase-lock` 或 `run-state.json` **无法绕过门禁** — 门禁脚本会校验 transition history
- `run_state.py --transition IMPLEMENTED` 必须附带 `--gate implementation --gate-status passed` + 已有的门禁证据
- `WAITING_DISPATCH` 状态在多服务并行场景中使用，阻止 coordinator 在子 agent 完成前推进

### 3.2 文件锁（Phase Lock）

这是最关键的物理约束。`start` 命令创建 `.phase-lock` 文件。**只要状态还没到 `IMPLEMENTED`，`phase_guard.py`（1,057 行）会拦截所有对生产代码的写入操作。**

实现方式：
- 在 Claude Code 中，通过 `settings.json` 配置 `PreToolUse` hook，每次 `Edit/Write/Bash` 工具调用前先跑 `phase_guard.py`
- 在 Codex/Gemini 中，通过类似的 pre-action hook 模板
- 在 OpenCode 中，通过 `install_hooks.py --runtime opencode` 自动安装 `.opencode/plugins/e2e-dev-harness.js`
- `phase_guard.py` 检查 `.phase-lock`，如果生命周期不是 `IMPLEMENTED`，返回 `{"ready": false}` + 阻止原因
- 支持 `--require-active-run-for-read`：未启动 run 时连代码读取都拦截
- 支持 `--require-session-checkpoint`：强制 agent 定期刷新 `session-checkpoint.json`，防止上下文过期后继续操作
- 多服务场景还要求 agent 先 `agent-task --action claim` 认领任务，才能写对应服务代码

**这就是为什么它能做到控制 — 它不是靠 prompt 劝说 agent，而是靠文件系统的锁和 hook 机制物理阻止不该发生的操作。**

### 3.3 证据链（Evidence）

每个阶段完成需要提交证据文件，机器可验证：

| 阶段 | 需要什么证据 |
|------|-------------|
| 需求澄清 | 填好的设计文档（goal、non-goal、AC、用例、测试设计、开放问题） |
| 服务设计 | 每个受影响服务的独立设计切片，所有全局 AC 必须映射到服务切片 |
| TDD Red | 失败的测试命令 JSON（exit_code != 0 + 命令 + 输出哈希） |
| TDD Green | 通过的测试命令 JSON（exit_code == 0 + 命令 + 输出哈希 + 耗时） |
| R1 设计审查 | 独立审查报告（agent/session 隔离证明 + request hash） |
| R2 测试审查 | 独立审查报告 + happy/failure path 覆盖 + 安全路径 |
| R3 实现审查 | 独立审查报告 + 每 AC 的代码路径追踪 + 反模式检查 |
| AC 进度 | 每个 AC 的覆盖行 + 实现清单行 + 绿色测试证据 |
| 完成 | 覆盖矩阵、实现清单、业务审查、依赖报告、任务对齐、返工关闭 |
| 严格守卫 | `verify --strict-workflow` 通过 + 需求归档 |

证据不是自然语言声明，而是结构化的 JSON/Markdown 文件，门禁脚本可以解析验证。

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
   选择 single/single-review/multi agent 模式，创建执行计划
   auto 模式根据风险关键词和服务数量自动推荐
  │
  ▼
5. Service Design Split（多服务拆分）  ← 仅多服务场景
   每个受影响服务获得独立设计切片
   run-state 进入 SERVICE_DESIGN_REQUIRED，所有切片验证通过才能继续
  │
  ▼
6. TDD Red（写失败测试）
   先写一个必然失败的测试，捕获命令执行证据
  │
  ▼
7. R2 Test Review（测试审查）
   独立审查 agent 在写生产代码前检查测试覆盖
  │
  ▼
8. Implementation Gate（实现门禁）
   验证 red 证据 + 门禁状态 + 知识图谱状态，通过后自动打开 IMPLEMENTED
  │
  ▼
9. Dispatch/Claim（分派任务）
   多 agent 场景：每个 agent 通过 agent-task claim 认领服务任务
   单 agent 场景：跳过此步
  │
  ▼
10. TDD Green/Refactor（实现 + 重构）
    最小实现让测试通过，按 test-impact-plan 执行增量 Maven 测试
    Superpowers 红绿重构循环
  │
  ▼
11. AC Progress Gate（AC 进度门禁）
    证明所有分配的 AC 都有覆盖行、实现清单行、通过的测试证据
    任何 AC 未完成 → 不准启动 R3
  │
  ▼
12. R3 Implementation Review（实现审查）
    独立审查 agent 逐 AC 追踪代码路径
    检查完整性、测试、安全、反模式、项目一致性
  │
  ▼
13. Completion Gate（完成门禁）
    每个 AC 都要有具体的代码引用和测试引用
    多服务场景还要求 handoff 证据
  │
  ▼
14. Rework Loop（返工循环）  ← 如果发现问题
    创建返工项，回到最早需要的阶段
    路由规则：需求不清→clarify / 缺测试→tdd / 契约问题→plan
  │
  ▼
15. Strict Guard/Archive（严格守卫 + 归档）
    verify --strict-workflow + guard + 摘要 + 需求归档
    execution-trace.json + run-summary.json + run-summary.md
```

### 4.1 各阶段的 `next` 指引

`e2e_dev_harness.py next` 命令会根据当前 lifecycle 返回精确的下一步指引：

| Lifecycle | 允许写入 | 阻止写入 |
|-----------|---------|---------|
| `CREATED` | docs/design/、docs/agent-runs/ | 生产代码、测试 |
| `CLARIFIED` | docs/agent-runs/、docs/design/ | 生产代码 |
| `SERVICE_DESIGN_REQUIRED` | docs/agent-runs/、docs/design/ | 生产代码、service code-agent 分发 |
| `PLANNED` | 测试文件（red evidence）、docs/agent-runs/ | 生产代码 |
| `RED_READY` | docs/agent-runs/ | 生产代码 |
| `IMPLEMENTED` | 声明范围内的生产/测试代码、docs/agent-runs/ | 未声明范围、R3 前的漂移 |
| `REVIEWED` | docs/agent-runs/ | 新生产变更（无返工项） |
| `REWORK_REQUIRED` | 返工路由范围内的代码 | 路由范围外的变更 |
| `VERIFIED` | docs/agent-runs/、记忆更新 | 新实现变更 |

---

## 五、技术架构

### 5.1 脚本层（42 个 Python 脚本，共 18,787 行）

核心入口是 `e2e_dev_harness.py`（2,629 行），提供 21 个子命令：

| 命令 | 作用 |
|------|------|
| `start` | 创建运行、设计模板、阶段锁、bootstrap schedule |
| `next` | 告诉你当前生命周期允许做什么 |
| `prepare` | 依赖发现、环境探测 |
| `clarify` | 机器检查设计文档完整性 |
| `plan` | 选择 agent 模式，创建归档 + agent-schedule |
| `gate` | 执行阶段门禁（planning/implementation/completion） |
| `verify` | 一键跑完准备→澄清→门禁→Maven |
| `guard` | CI/hook 层面的严格守卫 |
| `doctor` | 检查安装、runtime hooks、本地工具就绪度 |
| `install` | 安装 skill 副本 + 项目级 hooks |
| `pre-code` | 检查单个代码写入是否被 phase-lock 允许 |
| `test-impact` | 创建/验证增量测试影响计划 |
| `service-design` | 验证多服务设计切片 |
| `agent-task` | 认领/完成/验证 agent 任务 |
| `runtime-capabilities` | 报告 runtime 的多 agent 分发能力 |
| `dispatch-next` | 认领下一个就绪任务，创建子 agent 分发包 |
| `dispatch-beat` | 批量分发同组就绪任务 |
| `dispatch-ack` | 记录 runtime worker handle |
| `dispatch-complete` | 完成分发任务，验证证据 |
| `dispatch-status` | 汇总分发状态 |
| `ac-progress` | 阻止 R3 直到所有 AC 有实现+测试证据 |

辅助脚本分工明确（按行数排序 Top 15）：

| 脚本 | 行数 | 职责 |
|------|------|------|
| `e2e_dev_harness.py` | 2,629 | 主入口，21 个子命令路由 |
| `phase_guard.py` | 1,057 | 阶段锁守卫，hook 层拦截代码写入 |
| `cross_service_dependency_scan.py` | 1,044 | 跨服务依赖扫描（regex + 可选 tree-sitter AST） |
| `orchestration_plan.py` | 1,014 | 多 agent 编排决策 + 风险分类 |
| `reviewer_gate.py` | 952 | 审查门禁，确保独立且完整 |
| `dispatcher.py` | 984 | L0 串行隔离分发，支持 Claude Code / Codex / manual |
| `memory_capture.py` | 784 | 记忆选择与捕获 |
| `implementation_gate.py` | 782 | 实现阶段门禁（验证 red 证据 + KG + 评审） |
| `agent_scheduler.py` | 647 | agent 任务调度 + lease 管理 |
| `run_state.py` | 484 | 状态机管理 + 转换历史 + 门禁证据校验 |
| `clarification_gate.py` | 465 | 需求澄清门禁 |
| `harness_stop_guard.py` | 433 | 终止守卫（阻止 agent 在完成前结束） |
| `install_hooks.py` | 418 | hook 安装（Claude/Codex/Gemini/OpenCode） |
| `service_design_gate.py` | 407 | 服务设计门禁（多服务场景） |
| `handoff_gate.py` | 378 | agent 交接门禁 |

### 5.2 四个关键机制

**1) 阶段锁（Phase Lock）** — 物理阻止

```
.phase-lock 文件记录当前生命周期
hook 在每次 Edit/Write/Bash 前调用 phase_guard.py
phase_guard 检查锁状态 → 不在 IMPLEMENTED 阶段 → {"ready": false} → 写入被拒绝

额外保护：
- --require-active-run-for-read：未 start 时连读取都被阻止
- --require-session-checkpoint：强制定期刷新 checkpoint（默认 30 分钟过期）
- 多服务场景要求 agent-task claim 认领后才允许写对应服务代码
- recognized write tools: Write/Edit/Update/MultiEdit/NotebookEdit/Bash/Shell/PowerShell
- 未知工具触及代码路径 → fail closed（默认拒绝）
```

**2) 产物注册表（Artifact Registry）** — 全局追溯

```
每个计划产物记录：类型、所有者、路径、完成要求、状态、SHA-256
严格模式下所有产物必须存在且哈希匹配
用于 CI 回放和审计
支持 refresh 模式：计划文件写入后自动更新注册表
```

**3) 返工路由（Rework Routing）** — 问题回退有规则

```
需求不清         → 回到 clarify
缺少用例         → 回到 use-case-design
缺少测试         → 回到 test-case-design
缺少代码/测试失败 → 回到 tdd-implement
跨服务契约问题   → 回到 plan
评审发现问题     → 根据 return_phase 路由到最早需要的阶段
不允许直接打补丁跳过流程
返工项状态：Status: verified 或 Status: deferred (需 user-approved)
```

**4) 审查独立性（Review Independence）** — 防止自己审自己

```
R1/R2/R3 必须是独立 agent 或独立 session
同一个 agent 不能写代码又审代码
reviewer_gate.py 验证：
  - 审查 agent ≠ 开发 agent
  - 审查 session ≠ 开发 session
  - request hash 一致（防止评审的是被篡改的内容）
  - 必填字段完整
  - 无代码变更声明
  - 独立声明
不通过 → 整个审查无效，必须重新执行
```

### 5.3 工作流层级（Workflow Tiers）

不是所有任务都需要最严格的流程。四个层级，证据深度递增：

| 层级 | 包含内容 | 适用场景 |
|------|---------|---------|
| `basic` | 澄清 + 影响摘要 + 测试证据 + 完成证明 + 运行状态 + 产物注册表 + 运行摘要 | 小范围改动 |
| `standard` | `basic` + R1/R2/R3 审查 + 覆盖矩阵 + 需求归档 | 常规功能开发 |
| `critical` | `standard` + GitNexus 影响 + 契约 + 服务计划 + 交接 + 严格守卫 | 跨服务/API/MQ/支付/安全 |
| `audited` | `critical` + 策略回放 + 完成回放 + 状态历史 | 审计/合规/生产关键 |

`--workflow-tier auto` 根据设计文档中的风险关键词自动选择：
- 包含支付/退款/安全/权限/幂等/重试/MQ/Kafka → `critical`
- 跨服务 HTTP API → `critical`
- 中文关键词（跨服务/契约/消息契约/支付/退款） → `critical`
- 默认 → `standard`

### 5.4 Agent 编排模式

| 模式 | 场景 | 行为 |
|------|------|------|
| `single` | 小改动、单服务、低风险 | 一个 agent 做，但 R1/R2/R3 仍需独立审查 |
| `single-review` | 单服务中等改动 + 有风险词 | 一个 agent 开发，独立审查 session，split role |
| `multi` | 跨服务、契约变更、高风险、设计重 | 多个独立 agent，每个负责自己的服务 |

`auto` 模式的决策逻辑：
1. 检测到多个受影响服务 → 强制 `multi`
2. 单服务但有风险关键词 + 设计文档 > 6000 字符 → `single-review`
3. 其他 → `single`
4. `single` 和 `single-review` 在检测到多服务时会自动升级为 `multi`

### 5.5 Agent 分发机制

Harness 支持三种分发模式，通过 `runtime-capabilities` 查询：

| Runtime | 分发方式 | 能力 |
|---------|---------|------|
| Claude Code | `native-subagent` | 支持 Task tool、hook 确认、独立审查、stop 阻塞 |
| Codex | `codex-multi-agent-v1` | 支持 `multi_agent_v1.spawn_agent` |
| Manual | `manual-dispatch` | 输出手动分发包，不支持自动 |

分发流程：
```
dispatch-next → 识别就绪任务 → 创建 context-pack → 认领 → 输出 Task prompt
    ↓
agent 执行 Task prompt（只使用 context-pack 中的内容）
    ↓
dispatch-ack → 确认 worker handle（hook 或手动）
    ↓
dispatch-complete → 验证证据文件 → 关闭任务

dispatch-beat → 批量分发同组就绪任务（并行组调度）
```

Context Pack 约束：
- 最大 12 个文件 / 120,000 字符
- 超限 → 阻止分发，强制 coordinator 精简输入
- 只包含：allowed inputs、allowed outputs、dependency phase、budget

### 5.6 项目文件结构

```
skills/e2e-dev-harness/
  SKILL.md                          # 主 skill 入口（217 行）
  hooks/
    claude-code-settings.example.json   # Claude Code hook 模板
    codex-pre-action.example.json       # Codex hook 模板
    gemini-pre-action.example.json      # Gemini hook 模板
    opencode-plugin.example.js          # OpenCode 插件模板
  ci/
    github-actions-harness.yml          # GitHub Actions CI 模板
  references/                        # 16 个参考文档（2,199 行）
    agent-orchestration.md              # Agent 编排详解（389 行）
    implementation-gates.md             # 实现门禁（383 行，最详细）
    common-review-issues.md             # 常见审查问题（234 行）
    clarification-gate.md               # 需求澄清门禁（112 行）
    agent-handoff-schema.md             # Agent 交接模式（170 行）
    execution-control.md                # 执行控制（120 行）
    exec-plan.md                        # 执行计划模板（82 行）
    memory-integration.md               # 记忆集成（147 行）
    kg-tool-selection.md                # 知识图谱工具选择（146 行）
    tdd-java-spring.md                  # Java/Spring TDD 附则（100 行）
    review-profiles.md                  # 审查配置文件（87 行）
    agent-instructions.md               # Agent 指令加载（67 行）
    requirements-archive.md             # 需求归档（64 行）
    superpowers-integration.md          # Superpowers 集成（56 行）
    platform-compatibility.md           # 平台兼容性（42 行）
  review-profiles/                    # 审查配置
    default.json                         # 默认 profile（7 个检查项）
    security-heavy.json                  # 安全强化 profile
    api-first.json                       # API 优先 profile
  scripts/                           # 42 个 Python 脚本（18,787 行）
    e2e_dev_harness.py                  # 主入口（2,629 行）
    ...（见 5.1 节）
tests/                               # 27 个测试文件（751 个测试用例）
  conftest.py
  test_e2e_dev_harness_scripts.py      # 主集成测试
  test_orchestration.py                # 编排测试（176 个用例）
  test_gates_*.py                      # 各门禁测试
  test_evidence.py                     # 证据测试
  ...
pyproject.toml                          # 包配置（e2e-dev-harness / e2eh）
```

---

## 六、质量把控能力评估

### 6.1 质量维度评分

| 质量维度 | 评分 | 说明 |
|----------|------|------|
| **防止未测试代码进入** | ⭐⭐⭐⭐⭐ | TDD red/green 证据链 + implementation gate + test-impact-plan |
| **防止评审走过场** | ⭐⭐⭐⭐⭐ | reviewer_gate 验证 agent/session 隔离 + request hash + 必填字段 |
| **防止范围漂移** | ⭐⭐⭐⭐ | task_alignment_guard + implementation_manifest + coverage_gate |
| **防止跳步** | ⭐⭐⭐⭐⭐ | phase_lock + stop_guard + 状态转换历史校验 + session checkpoint |
| **防止多服务冲突** | ⭐⭐⭐⭐ | agent claim/lease + service-scoped write guard + dispatch lifecycle |
| **审计可追溯** | ⭐⭐⭐⭐⭐ | artifact registry + execution trace + evidence + command_evidence |
| **自身代码质量** | ⭐⭐⭐ | 见 6.3 节"自身代码质量问题" |

### 6.2 代码质量把控的完整链条

```
需求阶段：
  clarification_gate → 检查 goal/non-goal/AC/用例/测试设计/开放问题
  service_design_gate → 多服务场景下验证每个服务切片的 AC 映射

设计阶段：
  R1 review → 独立审查 AC 完整性、影响范围、安全路径、引用模式

测试阶段：
  TDD red evidence → 必须有失败证据（exit_code != 0）
  R2 review → 独立审查测试覆盖的 happy/failure path + 安全用例
  test-impact-plan → 增量测试范围，不是全量跑

实现阶段：
  implementation gate → 验证 red 证据 + KG 状态 + 评审通过
  phase_guard → hook 层面物理拦截未授权写入
  task_alignment_guard → 检测实现文件是否超出声明范围
  AC progress → 每个 AC 必须有覆盖行 + 实现行 + 绿色测试

评审阶段：
  R3 review → 独立审查，逐 AC 追踪代码路径
  reviewer_gate → 验证隔离性、完整性、无代码变更
  coverage_gate → 覆盖矩阵验证

完成阶段：
  completion gate → 全量证据校验
  rework_gate → 未关闭的返工项阻止完成
  workflow_guard → CI 级别的严格校验
  requirements_archive → 需求归档验证
```

### 6.3 自身代码质量问题

Harness 要求业务代码遵守严格的 TDD/评审/审计标准，但自身代码存在一些需要关注的问题：

**1) 圈复杂度爆表的核心函数**

| 文件 | 函数 | CC | 行数 | 影响 |
|------|------|----|------|------|
| `reviewer_gate.py` | `validate_item` | **94** | 240 | 最核心的评审验证逻辑 |
| `phase_guard.py` | `validate_action` | **79** | 374 | 最核心的写入拦截逻辑 |
| `implementation_gate.py` | `validate_gate_request` | **54** | 298 | 实现门禁核心 |
| `install_hooks.py` | `validate_config` | **39** | 66 | Hook 配置验证 |
| `harness_policy.py` | `validate_policy` | **32** | 55 | 策略验证 |

CC > 20 意味着函数有太多分支路径，修改时几乎不可能确保不引入回归。总计有 **34 个函数 CC > 15**。

**2) 主 CLI 是 2,629 行的上帝对象**

`e2e_dev_harness.py` 的 `main()` 函数有 **316 行**，通过 21 个 elif 分支路由子命令。其中：
- 15 个函数超过 50 行
- `main()` CC=22，`verify()` CC=22，`install_project()` CC=21

**3) 超长函数分布**

25 个函数超过 80 行，最长的是 `phase_guard.py:validate_action`（374 行）。

**4) Java/Spring 耦合**

18/42（43%）的脚本包含 Java/Spring/Maven 硬编码，总引用 198 处。这导致 harness 难以复用到 Go/Python/Node.js 项目。

**5) 错误信息可操作性**

门禁拒绝时，约 55% 的错误会附带修复指引，但 45% 只说 "invalid" 或 "missing"。企业级工具应 100% 给出可操作的修复步骤。

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
  - `gitnexus context` — 360 度符号视图（传类名/方法名，不传目录）
  - `gitnexus impact` — 受影响范围分析
  - `gitnexus detect-changes` — 变更检测
  - 在 `critical`/`audited` 层级，GitNexus 证据是门禁的必要输入
  - 不可用时的降级需要 user-approved degradation 记录
- **Graphify** — 文档、ADR、架构语义（辅助上下文）
  - Scanner 事实可同时作为 GitNexus 和 Graphify 的种子
- **Memory** — 可选上下文，不是权威来源
  - `memory_capture.py select --phase code --service <svc>` 按阶段和服务筛选
  - 只在完成时 promote 已验证的记忆条目
- **Superpowers** — 提供 brainstorming 和 TDD 的方法论，Harness 引用但不强制要求

---

## 八、企业级可用性评估

### 8.1 已达标的方面

| 维度 | 评价 | 说明 |
|------|------|------|
| **生命周期状态机** | ✅ 成熟 | 11 个状态、门禁驱动转换、带历史追溯、防手动篡改 |
| **门禁体系** | ✅ 完善 | 7+ 种门禁（clarify/service-design/implementation/completion/AC-progress/checkpoint/review），每个都有对应脚本 |
| **TDD 分层** | ✅ 完善 | auto/basic/strict 三级，风险关键词自动匹配 |
| **工作流分层** | ✅ 完善 | basic/standard/critical/audited 四层，证据深度递进 |
| **Hook 强制** | ✅ 完整 | 支持 Claude Code/Codex/Gemini/OpenCode 四平台，read/write/stop 全拦截 |
| **评审隔离** | ✅ 严格 | R1/R2/R3 要求独立 agent + 独立 session + request hash |
| **可审计性** | ✅ 完整 | 每个动作有 artifact registry + evidence + execution trace，完全可回放 |
| **CI 集成** | ✅ 就绪 | GitHub Actions workflow + guard 命令 + exit code 语义 |
| **多服务编排** | ✅ 设计完整 | 全局设计 + 服务切片 + context pack + dispatch lifecycle |
| **测试** | ✅ 751 全绿 | 27 个测试文件覆盖核心路径 |

### 8.2 需改进的方面

| 问题 | 严重性 | 影响 |
|------|--------|------|
| 核心函数 CC 过高（94/79/54） | 高 | 维护风险，修改容易引入回归 |
| 主 CLI 2629 行上帝对象 | 中 | 可读性差，难以并行开发 |
| Java/Spring 耦合 43% | 中 | 无法复用到其他技术栈 |
| Review Profile 只有 ~11 条检查项 | 中 | 质量标准偏薄 |
| 错误信息可操作性 55% | 中 | 开发者遇到错误时缺少修复指引 |
| 学习曲线陡峭（18 命令/11 状态/4 层级） | 低 | 新手上手成本高 |
| 缺少端到端示例项目 | 低 | 难以快速理解完整流程 |

### 8.3 企业级可用性结论

harness 的**流程设计和门禁理念达到了业界顶级水平**——状态机完备、门禁物理可执行、评审隔离严格、全链路可审计。

在"把控住开发过程中代码质量问题"这一点上，harness 的能力是**确实有效的**：它不是靠 prompt 劝说，而是靠文件锁 + hook 物理拦截 + 结构化证据验证。

但在工程实现层面（自身代码质量、技术栈通用性、开发者体验），距离"企业级好用"还有改进空间。改进建议按优先级：

1. **拆解高 CC 门禁函数**（1 周）→ 将 `validate_item`/`validate_action` 拆为独立子检查，每个 CC < 15
2. **拆分主 CLI**（3 天）→ 每个子命令一个模块
3. **丰富 Review Profile**（2 天）→ 从 11 条扩展到 40+ 条
4. **提升错误可操作性到 90%+**（2 天）→ 每个拒绝必须附带修复指引
5. **技术栈抽象层**（1 周）→ Java/Maven 硬编码提取为可配置 stack-adapter
6. **一键引导式初始化**（3 天）→ `e2eh init --interactive` 自动检测 + 安装 + 引导

---

## 九、适用场景

| 场景 | 是否适合 | 建议层级 |
|------|---------|---------|
| 单服务小改动（改个文案、加个字段） | 适合 | `basic` |
| 单服务功能开发（新 API、新业务逻辑） | 适合 | `standard` |
| 单服务高风险（支付/权限/安全） | 适合 | `critical` + `single-review` |
| 跨服务改动（改接口、加 MQ 消息） | 适合 | `critical` + `multi` |
| 支付/退款/审计/合规 | 适合 | `audited` |
| 纯探索性任务 | 不需要 | — |
| 非 Java/Spring 项目 | 需改造 | 43% 脚本有 Java 耦合 |

---

## 十、关键数据总结

| 指标 | 数值 |
|------|------|
| Python 脚本数量 | 42 个 |
| 脚本总代码量 | 18,787 行 |
| 最大脚本 | `e2e_dev_harness.py`（2,629 行） |
| CLI 子命令数 | 21 个 |
| 函数总数 | 748 个 |
| 类型标注覆盖 | 92% 函数 / 96% 参数 |
| 圈复杂度 > 15 的函数 | 34 个 |
| 100 行以上函数 | 25 个 |
| 参考文档数量 | 16 个 / 2,199 行 |
| SKILL.md 行数 | 217 行 |
| 测试文件数 | 27 个 |
| 测试用例数 | 751 个（全绿） |
| 工作流步骤 | 15 步 |
| 生命周期状态 | 11 个 |
| 工作流层级 | 4 级（basic/standard/critical/audited） |
| Agent 模式 | 3 种（single/single-review/multi） |
| 门禁类型 | 7+ 种 |
| Review Profile 检查项 | ~11 条 |
| 支持的 Agent Runtime | Claude Code / Codex / Gemini CLI / OpenCode / CI |
| 支持的技术栈 | Java 21 / Spring 6.x / Maven |
| Java/Spring 耦合脚本 | 18/42（43%） |
| 错误修复指引率 | ~55% |

---

## 十一、总结

E2E Dev Harness 的本质是 **"给 AI agent 戴上脚镣跳舞"**：

- **脚镣**：文件锁阻止乱写、状态机阻止跳步、门禁脚本阻止蒙混、stop guard 阻止提前结束
- **跳舞**：15 步工作流仍然允许 agent 完成复杂的多服务 Java/Spring 开发，只是必须按规矩来
- **可审计**：每一步都有磁盘上的证据文件，可以事后完整回放
- **物理约束**：不是靠 prompt 劝说，而是靠 hook + 文件锁物理阻止违规操作

它不是框架，不是库，而是一套 **可执行的流程控制脚本 + SKILL.md 指令**，让任何 AI agent runtime 都能按照严格的软件工程标准交付功能。
