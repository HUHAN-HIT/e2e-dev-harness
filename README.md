# E2E Dev Workflow Skill 与脚手架

本仓库提供一个 Codex skill 和一个 Java 工程脚手架，用于在 Java 21 + Spring Framework 6.x + Maven 项目中执行“先加载项目指令、再澄清、再建图、再 TDD 实施”的工程流程。

核心原则：

- 需求和用例没有澄清清楚前，不进入实现。
- 需求澄清前必须加载根目录 `AGENT.md` / `AGENTS.md` 和受影响微服务目录下的 `AGENT.md` / `AGENTS.md`。
- 实施前刷新知识图谱。
- TDD 以 `superpowers:test-driven-development` 为权威范式。
- 复杂任务可拆成多 agent，通过文件交接降低单个 agent 的上下文压力。
- 完成前必须用 coverage matrix 证明设计、用例、代码、UT 和业务审查已闭环。
- memory 只记录已验证或用户确认的事实，不能覆盖当前代码、测试和最新知识图谱。

## 目录结构

```text
.
|-- README.md
|-- skills/
|   `-- e2e-dev-workflow/
|       |-- SKILL.md
|       |-- agents/
|       |   `-- openai.yaml
|       |-- references/
|       |   |-- agent-instructions.md
|       |   |-- agent-handoff-schema.md
|       |   |-- agent-orchestration.md
|       |   |-- clarification-gate.md
|       |   |-- exec-plan.md
|       |   |-- kg-tool-selection.md
|       |   |-- memory-integration.md
|       |   |-- superpowers-integration.md
|       |   `-- tdd-java-spring.md
|       `-- scripts/
|           |-- agent_instructions.py
|           |-- clarification_gate.py
|           |-- common.py
|           |-- coverage_gate.py
|           |-- implementation_gate.py
|           |-- e2e_dev_workflow.py
|           |-- kg_refresh.py
|           |-- memory_capture.py
|           |-- orchestration_plan.py
|           `-- superpowers_probe.py
|-- tests/
|   `-- test_e2e_dev_workflow_scripts.py
`-- java21-spring-tdd-kg-scaffold/
    |-- AGENT.md
    |-- pom.xml
    |-- docs/
    |   |-- adr/
    |   `-- design/
    |-- memory/
    |-- scripts/
    |   |-- update-knowledge-graph.ps1
    |   `-- verify.ps1
    `-- services/
        `-- sample-service/
            |-- AGENT.md
            |-- pom.xml
            `-- src/
```

## 两个交付物

`skills/e2e-dev-workflow/` 是 skill 本体，负责定义 AGENT 指令加载、Superpowers 适配、需求澄清、用例设计、知识图谱刷新、memory 和 TDD 门禁。

`java21-spring-tdd-kg-scaffold/` 是工程脚手架示例，基于 Java 21、Spring Framework 6.x、Maven。它不是 Spring Boot 工程。

## 命名说明

skill 正式名称是 `e2e-dev-workflow`。名称强调“端到端研发流程”，不绑定具体技术栈；Java 21、Spring Framework 6.x、Maven、Graphify/GitNexus、Superpowers TDD 和 memory 是当前内置适配能力。

正式 CLI 入口是 `scripts/e2e_dev_workflow.py`。

## 前置条件

- Java 21
- Maven 3.9+
- Python 3.10+
- Superpowers plugin/skill
- Graphify CLI
- GitNexus CLI

建议确认命令在 `PATH` 中：

```powershell
java -version
mvn -version
python --version
graphify --help
gitnexus --help
```

## 标准使用流程

### 0. 统一准备入口

推荐优先使用统一 Python CLI，减少漏跑步骤：

```powershell
cd java21-spring-tdd-kg-scaffold
python ..\skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py prepare . `
  --design-doc docs\design\feature-design-template.md `
  --agent-mode strict `
  --agent-scope discovery `
  --service-scope discovery `
  --include-agent-content
```

如果已经知道会改哪些服务或文件，可以传入 `--service` 或 `--path`，只加载对应服务和目录作用域内的 AGENT 指令：

```powershell
python ..\skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py prepare . `
  --design-doc docs\design\feature-design-template.md `
  --service services/sample-service `
  --agent-mode strict `
  --agent-scope affected `
  --service-scope affected `
  --include-agent-content
```

```powershell
python ..\skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py prepare . `
  --design-doc docs\design\feature-design-template.md `
  --path services/sample-service/src/main/java/com/example/sample/order/OrderQuoteService.java `
  --agent-mode strict `
  --agent-scope affected `
  --service-scope affected `
  --include-agent-content
```

### 1. 加载 AGENT 指令

在进行需求澄清前先执行：

```powershell
cd java21-spring-tdd-kg-scaffold
python ..\skills\e2e-dev-workflow\scripts\agent_instructions.py . --mode strict --scope discovery --include-content
```

加载策略：

1. 澄清前使用 `--scope discovery`：只加载工程根目录 `AGENTS.override.md`、`AGENT.override.md`、`AGENT.md` 或 `AGENTS.md`，并列出已发现的微服务 AGENT 位置。
2. 需求澄清和设计方案大致确定受影响服务后，使用 `--scope affected --service services/<service>` 或 `--scope affected --path <path>` 重新加载。
3. 开发和测试阶段只加载受影响服务目录下的 `AGENT.md` 或 `AGENTS.md`，通常是 `services/<service>/AGENT.md`。
4. 只有全仓规则确实会影响本次任务时，才使用 `--scope all` 显式全量加载。

优先级是：用户当前指令 > 更深层 AGENT > 更外层 AGENT > skill 默认规则。

### 2. 检查 Superpowers

```powershell
python ..\skills\e2e-dev-workflow\scripts\superpowers_probe.py --mode auto
```

正式流程建议使用 strict：

```powershell
python ..\skills\e2e-dev-workflow\scripts\superpowers_probe.py --mode strict --phase clarification
python ..\skills\e2e-dev-workflow\scripts\superpowers_probe.py --mode strict --phase implementation
```

澄清阶段使用：

- `superpowers:using-superpowers`
- `superpowers:brainstorming`

实施阶段使用：

- `superpowers:writing-plans`
- `superpowers:test-driven-development`

### 3. 扫描 memory

```powershell
python ..\skills\e2e-dev-workflow\scripts\memory_capture.py scan .
python ..\skills\e2e-dev-workflow\scripts\memory_capture.py validate .
```

首次初始化 memory：

```powershell
python ..\skills\e2e-dev-workflow\scripts\memory_capture.py init .
```

追加已验证或用户确认的记忆：

```powershell
python ..\skills\e2e-dev-workflow\scripts\memory_capture.py add . `
  --type decision `
  --source user-approved `
  --confidence approved `
  --text "Use Spring Framework 6.x directly rather than Spring Boot."
```

按阶段和微服务选择最小 memory 上下文：

```powershell
python ..\skills\e2e-dev-workflow\scripts\memory_capture.py select . `
  --phase code `
  --service services/sample-service
```

一次 agent run 结束后，先在 `proposed-memory-updates.md` 里把每条更新标记为 `accepted`、`rejected`、`deferred` 或 `skipped`，再晋升已确认的记忆：

```powershell
python ..\skills\e2e-dev-workflow\scripts\memory_capture.py promote . `
  --from-file docs\agent-runs\<run>\proposed-memory-updates.md
```

### 4. 判断是否需要多 agent 编排

```powershell
python ..\skills\e2e-dev-workflow\scripts\orchestration_plan.py . `
  --mode auto `
  --service-scope discovery `
  --design-doc docs\design\feature-design-template.md
```

设计方案大致确定受影响服务后再按服务收敛：

```powershell
python ..\skills\e2e-dev-workflow\scripts\orchestration_plan.py . `
  --mode auto `
  --service-scope affected `
  --service services/sample-service `
  --design-doc docs\design\feature-design-template.md
```

模式说明：

- `single`：小任务，一个 agent 串行完成。
- `multi`：中大型、高风险、跨服务任务，拆成多个 agent。
- `auto`：根据服务数量、设计文档和风险关键词自动建议。

多 agent 模式下建议角色：

- Requirements Clarifier：需求澄清。
- Use Case Designer：用例设计。
- Test Case Developer：测试用例设计，遵循 Superpowers TDD。
- Code Developer：代码实现和验证；跨微服务时按服务拆成多个 service-scoped Code Developer。
- Coverage Reviewer：完成前检查设计覆盖、UT 证据和业务逻辑审查。

关键原则：交接靠文件，不靠聊天记忆。跨服务任务的实施计划必须按微服务粒度放在 `docs/agent-runs/<date-feature>/service-plans/<service>/`，避免相似业务描述在同一个 agent 上下文里互相污染。
`kg_refresh.detect()` 返回的 `service_candidates` 只是候选服务列表，不能直接当成本次实现范围。`discovery` 阶段不会基于全量候选服务生成 service plan；只有 `affected` 或显式 `all` 才会生成服务级计划。

### 5. 编写或更新设计文档

脚手架提供模板：

```text
docs/design/feature-design-template.md
docs/design/requirements-template.md
docs/design/use-cases-template.md
docs/design/test-plan-template.md
docs/design/implementation-plan-template.md
docs/design/exec-plan-template.md
docs/design/agent-handoff-template.md
```

进入实现前，设计文档中影响行为、接口、数据、测试的 open questions 必须清零。

复杂功能、跨服务改动、迁移或长时间重构建议创建一次 agent run 归档：

`discovery` 阶段也不会生成完整 agent plan、ExecPlan 路径或 handoff artifact map，只返回服务候选摘要和下一步提示。真正创建 `docs/agent-runs/<run>/` 归档时，先用 `--service-scope affected --service ...` 或 `--path ...` 锁定本次实施范围。

```powershell
python ..\skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py plan . `
  --design-doc docs\design\feature-design-template.md `
  --service-scope affected `
  --service services/sample-service `
  --create-archive
```

默认生成路径：

```text
docs/agent-runs/<YYYY-MM-DD-feature>/
  exec-plan.md
  handoffs/
    01-requirements-clarifier.md
    02-use-case-designer.md
    03-test-case-developer.md
    04-code-developer.md
  service-plans/
    <service>/
      implementation-plan.md
      code-agent.md
      unit-test-evidence.txt
      coverage-matrix.md
      business-review.md
  evidence/
    coverage-matrix.md
    business-review.md
  proposed-memory-updates.md
```

### 6. 刷新知识图谱

在脚手架目录执行：

```powershell
.\scripts\update-knowledge-graph.ps1
```

只使用 Graphify：

```powershell
.\scripts\update-knowledge-graph.ps1 -Mode graphify
```

已有 `graphify-out/graph.json` 时可快速刷新：

```powershell
.\scripts\update-knowledge-graph.ps1 -Mode graphify -Execute -UseSuggestedCommands
```

首次 Graphify 抽取必须显式传命令，避免误触发需要 LLM/API key 的流程：

```powershell
.\scripts\update-knowledge-graph.ps1 -Mode graphify -Execute -GraphifyCommand "graphify extract ."
```

同时使用 GitNexus 和 Graphify：

```powershell
.\scripts\update-knowledge-graph.ps1 -Mode both `
  -Execute `
  -GitNexusCommand "gitnexus analyze ." `
  -GraphifyCommand "graphify update ."
```

### 7. 运行门禁检查

设计阶段检查，不跑 Maven：

```powershell
.\scripts\verify.ps1 -DesignDoc docs\design\feature-design-template.md `
  -AgentInstructionsMode strict `
  -AgentMode auto `
  -SuperpowersMode strict `
  -MemoryMode strict `
  -SkipMaven
```

跨平台统一 CLI 版本：

```powershell
python ..\skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py verify . `
  --design-doc docs\design\feature-design-template.md `
  --agent-mode strict `
  --superpowers-mode strict `
  --memory-mode strict `
  --skip-maven
```

implementation gate 可用于实施前检查设计、知识图谱状态和红灯测试证据：

```powershell
python ..\skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py gate . `
  --phase implementation `
  --design-doc docs\design\feature-design-template.md `
  --red-test-evidence docs\design\feature-red-test.txt
```

completion gate 用于完成前检查设计覆盖、UT 通过证据和业务逻辑审查：

```powershell
python ..\skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py gate . `
  --phase completion `
  --design-doc docs\design\feature-design-template.md `
  --red-test-evidence docs\agent-runs\<run>\evidence\red-test.txt `
  --coverage-matrix docs\agent-runs\<run>\evidence\coverage-matrix.md `
  --unit-test-evidence docs\agent-runs\<run>\evidence\green-test.txt `
  --business-review docs\agent-runs\<run>\evidence\business-review.md `
  --memory-updates docs\agent-runs\<run>\proposed-memory-updates.md
```

coverage matrix 需要逐项映射：

```text
id | acceptance | use_case | service | tests | code_refs | business_review | status
```

只有每个验收项都关联到用例、服务、测试、代码引用和业务审查，且状态为 `covered` / `verified` 等通过状态，completion gate 才会放行。传入 `--memory-updates` 时，未标记处理状态的 proposed memory update 也会阻断完成。

完整验证：

```powershell
.\scripts\verify.ps1 -DesignDoc docs\design\feature-design-template.md `
  -Module services/sample-service `
  -AgentInstructionsMode strict `
  -AgentMode auto `
  -SuperpowersMode strict `
  -MemoryMode strict
```

也可以直接运行 Maven：

```powershell
mvn -pl services/sample-service -am test
mvn test
```

## AGENT 指令策略

根目录 `AGENT.md` 用于记录整个工程的工程规范，例如技术栈、禁止 Spring Boot、测试规则、目录约定、知识图谱和 memory 策略。

每个微服务目录的 `AGENT.md` 用于记录服务边界，例如 owned APIs、领域规则、数据归属、测试重点和禁止跨边界修改的规则。

`agent_instructions.py` 会发现：

- 根目录 `AGENTS.override.md` / `AGENT.override.md` / `AGENT.md` / `AGENTS.md`
- `services/*` 中包含 `pom.xml` 或 `src/` 的微服务
- 根 `pom.xml` 中声明、且包含 `pom.xml` 与 `src/` 的 Maven module
- `--path` 指定路径的父目录链上的 AGENT 文件
- `--service` 指定的微服务目录或服务名

`--scope auto` 是默认策略：没有 `--path` / `--service` 时解析为 `discovery`，只加载根 AGENT 并列出服务 AGENT；传入 `--path` / `--service` 时解析为 `affected`，只加载相关服务。`strict` 模式会在根 AGENT 或选中的受影响服务 AGENT 缺失时阻断；discovery 阶段发现某些服务缺少 AGENT 只报告，不把全部服务内容加载进上下文。旧仓库改造初期可用 `auto` 或 `optional`，但正式项目建议回到 `strict`。

## Agent Run 归档策略

不要移动 `AGENT.md` / `AGENTS.md`，它们必须留在各自目录作用域内。

生成的 agent 过程文件应单独归档：

- `docs/design/`：长期设计文档和模板。
- `docs/agent-runs/<date-feature>/`：某次 agent 执行的 ExecPlan、handoff、证据和 proposed memory updates。
- `memory/`：用户确认或验证后的长期记忆。
- `knowledge-graph/`：本地知识图谱刷新状态。

这样可以避免 `docs/design/` 被过程文件污染，也方便回放一次多 agent 执行过程。
知识图谱刷新默认跳过 `agent-runs` 目录，避免历史执行过程污染当前代码/设计分析。

## Knowledge Graph 策略

默认策略：

- GitNexus：用于 Java/Spring/Maven 代码结构、调用链、影响分析。
- Graphify：用于设计文档、架构材料、图、PDF、跨服务关系和可视化分析。
- 两者一起用：适合多微服务、跨服务契约变更、设计文档驱动的改动。

脚本会检测：

- Maven modules
- Spring 6 入口类
- 设计文档和媒体材料
- Graphify 是否安装
- GitNexus 是否安装
- `graphify-out/graph.json` 是否存在

状态文件写入：

```text
knowledge-graph/knowledge-graph-refresh.json
```

这是本地运行产物，不需要提交，也不需要手动修改。删除后可重新生成。

## Memory 策略

项目 memory 位于：

```text
memory/
```

包含：

- `project.md`：项目长期摘要、技术栈、术语、约定。
- `decisions.md`：用户确认或验证过的决策。
- `service-boundaries.md`：服务边界、API、事件、数据归属。
- `graph-findings.md`：复用价值较高的 Graphify/GitNexus 发现。
- `workflow-preferences.md`：团队工作流偏好。

Graphify 自身的反馈记忆位于：

```text
graphify-out/memory/
```

它通常是本地工具产物，默认不提交。

记录规则：

- 只记录已验证事实或用户确认的决策。
- 不记录猜测、密钥、个人信息、本机路径。
- 标注来源和置信度。
- 当前代码、测试和最新知识图谱优先级高于旧 memory。
- 多 agent 模式下，各 agent 先在交接文档里提出 memory 更新，主控确认后再写入 `memory/*.md`。

## `.ps1` 脚本说明

`.ps1` 是 PowerShell 脚本，主要面向 Windows。

当前脚本：

- `scripts/update-knowledge-graph.ps1`：封装知识图谱刷新。
- `scripts/verify.ps1`：封装 AGENT 指令检查、Superpowers、agent orchestration、memory、澄清门禁和 Maven 验证。

Linux/macOS 可以直接调用底层 Python 脚本，或后续补充 `.sh` 脚本。

## 当前能力评估

当前 skill 已覆盖：

- 澄清前分阶段加载 AGENT 指令：先加载根规则和服务索引，确定受影响服务后再加载对应服务规则。
- 跨平台统一 Python CLI：`prepare` / `clarify` / `plan` / `gate` / `verify`。
- Superpowers 可插拔适配，优先使用其 brainstorming 和 TDD 范式。
- Graphify/GitNexus 工具选择和刷新门禁。
- 单 agent / 多 agent 编排建议、ExecPlan 和 agent handoff 模板。
- hook-like planning / implementation / completion gate。
- coverage matrix 检查设计实现覆盖、UT 证据和业务逻辑审查。
- 多微服务时按 `service-plans/<service>/` 生成独立实施计划和 code agent 文件。
- memory 初始化、扫描和受控写入。
- Java 21 + Spring Framework 6.x + Maven 非 Spring Boot 脚手架。

仍需注意：

- `verify.ps1` 是 Windows 入口；跨平台优先使用 `e2e_dev_workflow.py`。
- 真正的需求澄清仍要由执行 agent 按 `load_order` 或 `--include-content` 加载内容；discovery 阶段不要打开 `discovered_service_agent_files`，除非设计已经收敛到对应服务。
- Graphify 首次抽取可能依赖本机 LLM/API key 配置，因此脚本不会自动执行未知的初始抽取命令。
- Maven 需要本机安装或后续补充 Maven Wrapper。

## 可拓展方向

### 增加微服务

新增目录：

```text
services/<new-service>/
```

并在根 `pom.xml` 注册：

```xml
<module>services/<new-service></module>
```

同时新增：

```text
services/<new-service>/AGENT.md
```

### 增加共享模块

可新增：

```text
shared/<module-name>/
```

适合 DTO、契约、工具类或共享领域模型。跨服务共享要谨慎，优先保持服务边界清晰。

### 接入 CI

推荐 CI 步骤：

```powershell
python skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py prepare . --agent-mode strict --agent-scope discovery --service-scope discovery --superpowers-mode strict --memory-mode strict
python skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py prepare . --agent-mode strict --agent-scope affected --service-scope affected --service <affected-service> --superpowers-mode strict --memory-mode strict
python skills\e2e-dev-workflow\scripts\superpowers_probe.py --mode strict
python skills\e2e-dev-workflow\scripts\memory_capture.py scan . --mode strict
python skills\e2e-dev-workflow\scripts\memory_capture.py validate .
python skills\e2e-dev-workflow\scripts\kg_refresh.py . --mode auto
python skills\e2e-dev-workflow\scripts\clarification_gate.py <design-doc>
python skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py gate . --phase planning --design-doc <design-doc>
python skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py gate . --phase completion --design-doc <design-doc> --red-test-evidence <red-test> --coverage-matrix <coverage-matrix> --unit-test-evidence <unit-test-evidence> --business-review <business-review> --memory-updates <proposed-memory-updates>
python -m unittest discover tests
mvn -pl <changed-modules> -am test
mvn test
```

### 将脚手架并入 skill 分发

当前脚手架独立放在：

```text
java21-spring-tdd-kg-scaffold/
```

如果要做成更标准的一体化 skill 包，可迁移到：

```text
skills/e2e-dev-workflow/assets/scaffold/
```

## 后续优化建议

- 增加 Maven Wrapper：`mvnw` / `mvnw.cmd`。
- 增加 Linux/macOS `.sh` 脚本。
- 增加 Spring MVC `MockMvcBuilders` 示例。
- 增加 contract test 示例。
- 增加多服务示例模块。
- 让 `agent_instructions.py` 支持从 git diff 自动推导 `--path`。
- 将 Graphify/GitNexus 查询结果自动汇总为“受影响服务/类/接口”。
- 增加 memory 与 Graphify `save-result` 的自动衔接。
- 增加 CI 示例。
- 将统一 Python CLI 接入更多真实 Maven/Graphify/GitNexus 执行证据。

## 常见问题

### 为什么有 `skills/` 和 `java21-spring-tdd-kg-scaffold/` 两个目录？

因为它们是两个交付物：

- `skills/` 是 Codex skill。
- `java21-spring-tdd-kg-scaffold/` 是 Java/Spring/Maven 工程模板。

### `knowledge-graph-refresh.json` 需要手动改吗？

不需要。它是本地状态文件，由脚本自动生成。

### 每个人电脑上的安装目录不同怎么办？

AGENT 指令、memory 和脚手架本身都放在工程目录内，不依赖个人安装目录。Graphify、GitNexus、Superpowers 的本机安装路径由探测脚本或命令行 `PATH` 处理；不要把个人绝对路径写入项目文档或 memory。

### 没有 Maven 能不能先用？

可以。先运行：

```powershell
cd java21-spring-tdd-kg-scaffold
.\scripts\verify.ps1 -DesignDoc docs\design\feature-design-template.md -AgentInstructionsMode strict -SuperpowersMode strict -MemoryMode strict -SkipMaven
```

这会检查 AGENT 指令、Superpowers、memory 和设计澄清门禁，但不会执行 Maven 测试。
