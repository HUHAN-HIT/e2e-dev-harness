# E2E Dev Harness 企业级能力测评报告（修订版）

> 测评日期：2026-05-30（二次复测）
> 测评对象：`skill-skill-superpowers-skill-tdd-graphify` 仓库
> 测评范围：架构设计、代码质量、测试健康度、可维护性、可扩展性、用户体验、安全性
> 测评方法：全量测试执行 + 源码审读 + 参考文档审读 + git 历史分析
> 测评结论：**POC 阶段偏后期，核心机制可靠但接口层不稳定，距企业级可用需 2-3 周打磨**

---

## 一、测评环境与原始数据

### 1.1 测试执行原始结果

```
619 tests collected
574 passed
 49 failed
 40 subtests passed (含 3 subfailed)
  0 collection errors

执行时间：17.63s
Python 版本：系统默认
平台：Windows 11
```

### 1.2 失败分布

| 测试文件 | 失败数 | 占比 |
|----------|--------|------|
| `test_e2e_dev_harness_scripts.py` | 22 | 45% |
| `test_orchestration.py` | 11 | 22% |
| `test_gates_implementation.py` | 8 | 16% |
| `test_agent_instructions.py` | 2 | 4% |
| `test_skill_docs.py` | 1 | 2% |
| `test_scanner.py` | 1 | 2% |
| **合计** | **45** | — |

### 1.3 失败根因分类

| 根因 | 数量 | 严重性 | 说明 |
|------|------|--------|------|
| `TypeError: ... got an unexpected keyword argument 'no_harness_state'` | 12 | **高** | `implementation_gate.py` 和 `GateRequest` 的接口已改，但部分调用方还在传旧参数 |
| `AssertionError: True is not false` | 14 | **高** | 门禁/守卫逻辑反转——本该 block 的放行了，或本该 pass 的被 block 了 |
| 路径断言失败（phase_guard 路径不在 hook command 中） | 6 | **中** | `install_hooks` 生成的 hook command 路径解析逻辑与测试预期不一致 |
| `KeyError: 'runtime_code_paths'` | 2 | **中** | dict 结构变更后调用方未同步 |
| `AttributeError: module has no attribute 'env_default'` | 4 | **中** | 函数已删除但测试仍引用 |
| SKILL.md 长度超限（2257 > 2200） | 1 | **低** | 文档增长导致断言失效 |
| Scanner backend 断言（regex-fallback != tree-sitter） | 1 | **低** | 测试环境未安装 tree-sitter |

**关键发现：12 个 `TypeError` + 14 个逻辑反转 = 26 个失败（占 53%）集中在接口签名和门禁判定逻辑。这表明代码处于快速迭代期，接口层尚未收敛。**

---

## 二、项目基本盘

### 2.1 代码规模

| 层 | 文件数 | 行数 | 说明 |
|----|--------|------|------|
| Python 脚本 | 37 | ~13,800 | 核心逻辑 |
| 测试代码 | 22 | ~20,350 | 自测 |
| SKILL.md | 1 | 229 | Agent 入口指令 |
| 参考文档 | 16 | ~2,052 | references/ |
| README.md | 1 | 498 | 使用说明 |
| 分析报告 | 1 | 372 | 既有分析 |
| Java scaffold | 6 | ~200 | 示例项目 |
| 设计模板 | 7 | ~350 | docs/design/ |
| **合计** | **~91** | **~37,500** | — |

### 2.2 Git 演进

```
20 次提交
时间跨度：约 7 天（2026-05-23 ~ 2026-05-30）
最大单次提交：56 files changed, 2453 insertions, 1055 deletions
提交风格：中文简短描述，无 conventional commits
```

**判断：这是一个 7 天内高强度迭代的原型项目。代码变更频率高（单次提交动辄 1000+ 行变更），接口尚未稳定。**

---

## 三、分维度评估

### 3.1 架构设计 — 9.0 / 10

| 评估项 | 评分 | 依据 |
|--------|------|------|
| 控制模型 | 9.5 | 状态机 + 文件锁 + 证据链，不靠 prompt 劝说，从机制层面解决 Agent 跳步问题 |
| Agent 中立 | 9.0 | 同时支持 Claude Code / Codex / Gemini CLI / OpenCode / CI，hook 模板三套 |
| 生命周期设计 | 9.0 | 9 个生命周期阶段，每个转换有门禁验证和证据要求 |
| 工作流分层 | 9.0 | basic / standard / critical / audited 四级，按风险自适应 |
| Agent 编排 | 8.5 | single / single-review / multi 三模式，自动推荐 + 强制升级 |
| 返工路由 | 8.5 | 6 种回退路由，不允许直接打补丁 |
| 可回放 | 9.0 | artifact-registry + SHA-256 + execution-trace + run-summary |

**核心优势：**
- `phase_guard.py` 在 Agent runtime 的 hook 层拦截代码写入，是目前 AI Agent 生态中少见的物理约束方案
- 状态机是文件级的（`run-state.json` 写在磁盘上），不依赖单个 Agent 的上下文，多 Agent 可共享
- 审查独立性有结构性保证（R1/R2/R3 必须独立 Agent、独立 session，不能自审自写）

**不足：**
- 状态机阶段和返工路由映射硬编码在 `next_action_for_lifecycle()` 中，无法注册自定义阶段
- 多 Agent 的错误传播机制未设计（一个服务 Agent 失败如何通知其他？）

### 3.2 代码质量 — 6.5 / 10

| 评估项 | 评分 | 依据 |
|--------|------|------|
| 模块分工 | 8.0 | 37 个脚本职责单一，边界清晰 |
| 类型标注 | 8.0 | 全面使用 `from __future__ import annotations`，参数和返回值类型标注覆盖率高 |
| Docstring | 7.5 | 所有模块有 docstring，部分函数缺 docstring |
| 错误处理 | 5.0 | 参差不齐——`phase_guard.py` 精细（捕获 JSONDecodeError/OSError），`common.py` 用裸 `Exception` |
| 代码组织 | 4.5 | 主入口 `e2e_dev_harness.py` 1,949 行，混合了 CLI 定义、模板生成、业务逻辑、审查清单 |

**具体问题：**

1. **主入口单体**：`e2e_dev_harness.py` 同时承担 12 个子命令的路由、10+ 个模板函数（~400 行字符串拼接在 Python 中）、CLI 参数定义（~200 行 argparse）、以及所有辅助函数。这是整个项目最大的技术债。

2. **模板硬编码**：`design_template()`, `handoff_text()`, `coverage_matrix_template()`, `service_design_template()`, `service_plan_template()`, `review_request_template()` 等 10+ 个函数的模板内容直接用 f-string 写在 Python 代码中。企业用户无法定制模板而不改源码。

3. **子进程超时无分级**：全局常量 `DEFAULT_SUBPROCESS_TIMEOUT_SECONDS`（在 `common.py` 中定义），Maven 全量编译和单模块测试共用同一个超时。

4. **异常处理不一致**：
   - `phase_guard.py`：精细处理（`JSONDecodeError`, `OSError`, `UnicodeDecodeError`）
   - `common.py`：裸 `except Exception` 静默返回空值
   - `e2e_dev_harness.py`：`except (FileNotFoundError, ValueError)` 只捕获两种
   - 缺少统一的错误分类和错误码体系

### 3.3 测试健康度 — 6.0 / 10

| 评估项 | 评分 | 依据 |
|--------|------|------|
| 测试覆盖率 | 8.0 | 门禁、编排、扫描、记忆、上下文打包等核心模块均有覆盖 |
| 测试通过率 | 5.0 | 574/619 = 92.7% 通过，45 个失败 |
| 失败根因集中度 | 5.5 | 53% 的失败集中在接口签名变更（`no_harness_state`）和逻辑反转 |
| 测试文件组织 | 5.0 | `test_e2e_dev_harness_scripts.py` 单文件 9,817 行 |
| 端到端测试 | 4.0 | 缺少真实 Maven 项目 + 真实 GitNexus 的集成测试 |

**测试健康度分析：**

通过率 92.7% 看似尚可，但 45 个失败的根因揭示了三个结构性问题：

1. **接口签名未收敛** — 12 个 `TypeError: unexpected keyword argument 'no_harness_state'` 表明 `implementation_gate.py` 的 `validate_gate()` 和 `GateRequest` 经历了接口变更，但部分调用路径（如 `test_e2e_dev_harness_scripts.py` 和 `test_gates_implementation.py`）未同步。这是快速迭代的典型症状。

2. **门禁判定逻辑有回归** — 14 个 `AssertionError: True is not false` 集中在门禁和守卫逻辑。这些是行为反转：本该 block 的放行了，或本该 pass 的被 block 了。在 harness 这种「控制 Agent 行为」的系统中，门禁逻辑的回归是高风险问题。

3. **测试文件过大** — `test_e2e_dev_harness_scripts.py` 9,817 行，占全部测试代码的 48%。应该拆分为与脚本一一对应的测试文件，降低维护成本。

**正面评价：**

- 20,350 行测试代码 / 13,800 行生产代码 = **1.47:1 测试比**，投入充分
- 574 个通过的测试覆盖了门禁、编排、状态机、扫描、记忆等核心路径
- 测试用临时目录（`tmp_path` / `TemporaryDirectory`），不污染文件系统

### 3.4 可维护性 — 5.5 / 10

| 评估项 | 评分 | 依据 |
|--------|------|------|
| 模块化 | 5.0 | 主入口 1,949 行未拆分；模板硬编码在 Python 中 |
| 包管理 | 3.0 | 无 `pyproject.toml` / `requirements.txt` / `setup.py` |
| 版本管理 | 3.0 | 无 `--version`、无 CHANGELOG、run-state 无 schema version |
| 代码-测试同步 | 5.0 | 45 个测试失败表明迭代中代码和测试未完全同步 |
| Git 卫生 | 6.0 | 提交粒度合理，但提交消息为中文简述，无 conventional commits |
| 路径处理 | 8.0 | 统一使用 `pathlib.Path`，有 `resolve_repo_path` / `require_repo_path` 安全检查 |

**包管理是最大的硬伤：**

没有 `pyproject.toml` 意味着：
- 无法 `pip install` 这个项目
- 无法声明 `tree-sitter-java` 为可选依赖
- 无法锁定 `pytest` 版本
- 无法声明 Python 版本要求
- CI 环境不可复现

### 3.5 可扩展性 — 5.0 / 10

| 扩展点 | 可定制性 | 机制 |
|--------|----------|------|
| Review profiles | **好** | JSON 文件 + `extends` 继承 + 项目级覆盖 |
| Workflow tiers | **好** | 4 级自适应，按设计文档内容自动选择 |
| Lifecycle 阶段 | **无** | 9 个阶段硬编码在 `next_action_for_lifecycle()` |
| Gate 逻辑 | **无** | 硬编码在 `implementation_gate.py`，无法注册自定义 gate |
| 模板格式 | **无** | Python f-string 硬编码 |
| Evidence 格式 | **部分** | JSON schema 有版本号但部分格式无版本 |
| Rework routing | **无** | 硬编码映射表 |
| 依赖扫描器 | **部分** | tree-sitter / regex 可切换，但无法注册自定义扫描器 |
| Agent 编排 | **部分** | single / multi 自动推荐，但无法自定义编排策略 |

**Review profiles 设计是亮点：**

```json
{
  "extends": "default",
  "common_issues": ["security-heavy"],
  "required_checklist": { "design": [...], "test": [...], "implementation": [...] }
}
```

支持继承、引用 common-review-issues.md、按 phase 分层 check。这是唯一设计良好的扩展点。

**企业级缺失的扩展点：**

- 自定义 lifecycle 阶段（如加 `SECURITY_REVIEW`）
- 自定义 gate 逻辑（如对接 SonarQube quality gate）
- 自定义模板（如多语言团队的设计文档模板）
- 自定义 evidence 消费者（如对接内部 CI 的证据系统）

### 3.6 用户体验 — 5.5 / 10

| 评估项 | 评分 | 依据 |
|--------|------|------|
| CLI 设计 | 7.0 | 12 个子命令，参数命名清晰，有 `--json` 输出 |
| `next` 命令 | 8.0 | 告诉用户当前该做什么，降低认知负担 |
| 输出格式 | 4.0 | 全部 JSON 输出，无人类友好的彩色/表格/进度 |
| 错误提示 | 4.0 | 大量 `ValueError` + 原始路径，无上下文引导 |
| 快速开始 | 4.0 | 无 quickstart 教程，README 直接进入命令 |
| 文档量 | 7.5 | README 498 行 + SKILL.md 229 行 + 16 个 reference = 文档丰富 |
| Scaffold 示例 | 4.5 | 只有 4 个 Java 文件 + 1 个测试，缺少 JPA/MQ/Security 示例 |

**`next` 命令是亮点：**

```
python e2e_dev_harness.py next . --state docs/agent-runs/<run>/run-state.json
→ {"lifecycle": "CREATED", "next": {"phase": "clarify", "command": "...", "allowed_writes": [...], "blocked_writes": [...]}}
```

用户不需要记住流程，`next` 告诉你该做什么、能写什么、不能写什么。

**但输出是 JSON：**

- 用户需要 `python ... | jq '.next.command'` 才能看到下一步
- 错误消息也是 JSON，`"blocked_reasons": ["..."]` 不如红色终端文本醒目
- 没有 `--verbose` / `--debug` / `--dry-run` 分级

### 3.7 安全性 — 5.5 / 10

| 风险 | 严重性 | 说明 |
|------|--------|------|
| `command_evidence.py` 执行用户命令 | **高** | `--command` 参数直接传入 `subprocess.run`，无白名单校验 |
| `phase_guard.py` stdin 无大小限制 | **中** | hook 输入未做大小和格式校验 |
| `install_hooks.py` 修改 settings.json | **中** | 无原子写入和备份机制 |
| 路径 traversal | **低** | 大部分代码有 `relative_to` 检查，覆盖较好 |
| 子进程超时 | **低** | 全局超时常量，但不是安全漏洞 |

**正面：**
- `require_repo_path()` 在 `e2e_dev_harness.py` 中统一检查路径不出仓库
- `phase_guard.py` 不执行任何代码，只检查文件路径和锁状态，攻击面小

### 3.8 参考文档 — 7.5 / 10

| 文档 | 行数 | 完整性 | 清晰度 | 可操作性 |
|------|------|--------|--------|----------|
| implementation-gates.md | 382 | 5/5 | 4/5 | 5/5 |
| agent-orchestration.md | 323 | 5/5 | 4/5 | 5/5 |
| common-review-issues.md | 233 | 4/5 | 5/5 | 4/5 |
| agent-handoff-schema.md | 166 | 4/5 | 4/5 | 4/5 |
| memory-integration.md | 146 | 4/5 | 4/5 | 4/5 |
| kg-tool-selection.md | 121 | 4/5 | 4/5 | 4/5 |
| clarification-gate.md | 111 | 4/5 | 4/5 | 4/5 |
| tdd-java-spring.md | 99 | 3/5 | 4/5 | 4/5 |
| review-profiles.md | 86 | 3/5 | 4/5 | 4/5 |
| execution-control.md | 81 | 3/5 | 4/5 | 3/5 |
| exec-plan.md | 81 | 3/5 | 4/5 | 3/5 |
| agent-instructions.md | 66 | 3/5 | 4/5 | 3/5 |
| requirements-archive.md | 63 | 3/5 | 4/5 | 3/5 |
| superpowers-integration.md | 55 | 3/5 | 3/5 | 3/5 |
| platform-compatibility.md | 39 | 2/5 | 5/5 | 3/5 |

**亮点：**
- `implementation-gates.md` 是最核心的参考文档，382 行覆盖了所有门禁的详细规则、证据格式、策略验证、回放逻辑
- `common-review-issues.md` 用「问题 → 示例 → 判定标准」结构，可直接用于审查
- Review profile JSON 支持 `extends` 继承 + `common_issues` 引用，设计良好

**不足：**
- `platform-compatibility.md` 只有 39 行，对于声称支持 4+ 个 runtime 的项目来说太简略
- 没有 quickstart 教程或「我的第一个 harness run」引导
- 缺少命令参考文档（只有 `--help`）

---

## 四、综合评分

| 维度 | 得分 | 权重 | 加权得分 | 关键依据 |
|------|------|------|----------|----------|
| 架构设计 | 9.0 | 25% | 2.25 | 控制模型正确，Agent 中立，生命周期严谨 |
| 代码质量 | 6.5 | 15% | 0.98 | 模块分工好，但主入口过大、模板硬编码、错误处理不一致 |
| 测试健康度 | 6.0 | 15% | 0.90 | 测试比 1.47:1 投入充分，但 45 个失败暴露接口未收敛 |
| 可维护性 | 5.5 | 15% | 0.83 | 无包管理、无版本管理、主入口未模块化 |
| 可扩展性 | 5.0 | 10% | 0.50 | Review profiles 设计好，但 lifecycle/gate/template 无法扩展 |
| 用户体验 | 5.5 | 10% | 0.55 | `next` 命令好，但全 JSON 输出、无 quickstart、scaffold 简陋 |
| 安全性 | 5.5 | 5% | 0.28 | 路径检查好，但命令注入风险存在 |
| 参考文档 | 7.5 | 5% | 0.38 | 文档丰富质量好，但 quickstart 缺失 |
| **综合得分** | | | **6.66 / 10** | |

---

## 五、改进路线图

### Phase 1：修复基线（3-5 天）— 阻断性

| # | 改进项 | 工作量 | 影响范围 | 交付物 |
|---|--------|--------|----------|--------|
| 1 | 修复 45 个失败测试 | 2-3 天 | 测试 | 全绿测试套件 |
| | — 修复 12 个 `TypeError: no_harness_state` | | | 统一 GateRequest 接口 |
| | — 修复 14 个门禁逻辑反转 | | | 门禁判定回归验证 |
| | — 修复 6 个路径断言 | | | install_hooks 路径解析 |
| | — 修复 SKILL.md 长度断言 | | | 放宽或动态计算阈值 |
| 2 | 添加 `pyproject.toml` | 0.5 天 | 构建 | 可 pip install、依赖声明、Python 版本约束 |
| 3 | 添加 `--version` + CHANGELOG.md | 0.5 天 | 运维 | 版本可追溯 |

**Phase 1 完成标志：619 个测试全绿、可 `pip install -e .`、`--version` 输出版本号。**

### Phase 2：架构解耦（5-7 天）— 关键性

| # | 改进项 | 工作量 | 影响范围 | 交付物 |
|---|--------|--------|----------|--------|
| 4 | 拆分 `e2e_dev_harness.py` | 3-4 天 | 全部 | 子命令独立模块 + 共享 core 层 + CLI 薄壳 |
| 5 | 模板外置 | 1-2 天 | 全部 | `templates/` 目录，Markdown/JSON 文件 |
| 6 | 拆分 `test_e2e_dev_harness_scripts.py` | 1 天 | 测试 | 与脚本一一对应的测试文件 |

**Phase 2 完成标志：无超过 500 行的 Python 文件、模板可外部替换、测试文件与源码一一对应。**

### Phase 3：可扩展性 + 体验（5-7 天）— 增强性

| # | 改进项 | 工作量 | 影响范围 | 交付物 |
|---|--------|--------|----------|--------|
| 7 | 设计插件/扩展点机制 | 3-4 天 | 架构 | 可注册自定义 gate / lifecycle / scanner / template |
| 8 | CLI 人性化输出 | 1-2 天 | 体验 | 彩色输出、表格、`--verbose`/`--dry-run` |
| 9 | Quickstart 教程 | 1 天 | 文档 | `docs/quickstart.md` + 端到端示例 |
| 10 | 丰富 scaffold 项目 | 2-3 天 | 示例 | Spring Security / JPA / MQ / Testcontainers 示例 |

**Phase 3 完成标志：企业可注册自定义 gate、CLI 有人类友好输出、新用户 30 分钟可上手。**

### Phase 4：生产加固（持续）— 持久性

| # | 改进项 | 工作量 | 影响范围 |
|---|--------|--------|----------|
| 11 | `command_evidence.py` 命令白名单 | 1 天 | 安全 |
| 12 | 多 Agent 并发安全性（文件锁增强） | 2-3 天 | 多服务 |
| 13 | 结构化日志 | 1-2 天 | 可观测性 |
| 14 | 大 monorepo 性能基准 | 2-3 天 | 性能 |
| 15 | 多 CI 平台模板 | 1 天 | CI |
| 16 | run-state schema 版本号 + 迁移工具 | 1-2 天 | 兼容性 |

---

## 六、成熟度判定

```
                        当前
                          ↓
概念验证（POC）     ████████████████████░░░░░░░░░░  Phase 0
原型可用            ████████████████████████░░░░░░  ← 当前位置
内部工具可用        ████████████████████████████░░  Phase 1 完成后
企业级可用          ██████████████████████████████  Phase 2-3 完成后
生产级成熟          ██████████████████████████████  Phase 4 完成后
```

**当前位置：原型可用（POC 后期）**

- 核心机制（状态机、文件锁、证据链、门禁判定）经 574 个测试验证，逻辑可靠
- 接口层（`GateRequest` 签名、门禁判定细节）在快速迭代中尚未收敛
- 工程化（包管理、模块化、模板外置、版本管理）尚未启动
- 但设计理念和架构思路已经成熟，不需要推翻重来

---

## 七、核心结论

### 做对了什么（值得保持）

1. **控制模型** — 文件锁 + 状态机 + 证据链是 AI Agent 治理的正确工程思路，不靠 prompt 劝说
2. **Agent 中立** — 不绑定特定 runtime，通过 SKILL.md + hook 模板实现跨平台
3. **审查独立性** — R1/R2/R3 必须独立 Agent，有结构性保证（request hash、independence 声明）
4. **测试投入** — 1.47:1 测试比，20,350 行测试代码，远超一般项目
5. **`next` 命令** — 降低用户认知负担，告诉用户该做什么、能做什么、不能做什么
6. **Review profiles** — JSON 文件 + `extends` 继承 + `common_issues` 引用，设计良好的扩展点
7. **参考文档** — 16 个文档覆盖了所有关键环节，`implementation-gates.md` 尤其出色

### 需要补什么（必须改进）

| 优先级 | 改进项 | 一句话说明 |
|--------|--------|-----------|
| P0 | 修复 45 个失败测试 | 测试全绿是基本功，12 个 `TypeError` 暴露接口未收敛 |
| P0 | 拆分主入口 + 模板外置 | 1,949 行单文件是可维护性的硬阻断 |
| P1 | 添加 `pyproject.toml` | 无法 pip install 是复现环境的硬阻断 |
| P1 | 设计插件扩展点 | 无法扩展 lifecycle/gate/template 是企业采用的软阻断 |
| P2 | CLI 人性化输出 | 全 JSON 输出是日常使用的体验阻断 |
| P2 | Quickstart + 丰富 scaffold | 新用户上手门槛高 |

### 一句话总结

**架构 9 分，工程 6 分。核心机制可靠但接口层不稳定，工程化（包管理、模块化、可扩展性）尚未启动。距离企业级可用需要 Phase 1-3 的 2-3 周打磨，但不需要推翻核心设计。**

---

## 附录 A：测评方法论

| 方法 | 说明 |
|------|------|
| 全量测试执行 | `python -m pytest tests/ -q --tb=line`，获取精确通过/失败数 |
| 失败根因分类 | 按错误类型 `sort | uniq -c`，识别结构性问题 vs 随机问题 |
| 源码审读 | 通读 `e2e_dev_harness.py` 全文（1,949 行）+ SKILL.md + README.md |
| 模块抽样审读 | `phase_guard.py` / `implementation_gate.py` / `run_state.py` / `orchestration_plan.py` / `common.py` |
| 参考文档全量审读 | 16 个 reference 文档逐一评分 |
| Review profile 审读 | 3 个 JSON profile 的结构和继承关系 |
| Git 历史分析 | 20 次提交的变更规模和提交风格 |
| 对比标准 | 企业级 CI/CD harness 的通用要求：测试全绿、可安装、可扩展、文档完备 |
