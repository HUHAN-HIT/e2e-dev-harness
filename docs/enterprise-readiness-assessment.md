# E2E Dev Harness 企业级就绪度评估报告（2026-05-31 更新）

> 评估日期：2026-05-31
> 版本：0.2.0
> 评估方法：全量测试执行 + 源码审读 + 安装验证 + CLI 体验测试
> 对照基准：2026-05-30 评估报告（6.66/10，45 个测试失败）

---

## 一、基线变化（相比上次评估）

| 指标 | 上次（05-30） | 本次（05-31） | 变化 |
|------|-------------|-------------|------|
| 测试总数 | 619 | 651 | +32 新测试 |
| 测试通过率 | 92.7%（574/619） | **100%（651/651）** | **全绿** |
| 失败测试 | 45 | **0** | 彻底修复 |
| `pyproject.toml` | 无 | **有** | 可 pip install |
| `--version` | 无 | **0.2.0** | 版本可追溯 |
| `CHANGELOG.md` | 无 | **有** | 变更可追溯 |
| `doctor` 命令 | 无 | **有** | 环境自检 |
| `harness_stop_guard` | 无 | **有** | 停止守卫 |
| pip install -e . | 不可能 | **成功** | 企业安装可行 |
| CLI entry point | 仅 python 调用 | **e2e-dev-harness 全局命令** | 体验提升 |

**结论：Phase 1（修复基线）已基本完成。这是从"原型可用"到"内部工具可用"的关键一步。**

---

## 二、当前状态评分（8维度）

| 维度 | 上次 | 本次 | 变化 | 核心依据 |
|------|------|------|------|----------|
| 架构设计 | 9.0 | 9.0 | — | 未变，仍然是最强项 |
| 代码质量 | 6.5 | 7.0 | +0.5 | 接口收敛、doctor/stop_guard 新增 |
| 测试健康度 | 6.0 | **8.5** | +2.5 | 全绿、新增 32 测试、doctor 覆盖 |
| 可维护性 | 5.5 | **7.0** | +1.5 | pyproject.toml、version、changelog |
| 可扩展性 | 5.0 | 5.0 | — | 未变，仍是最短板 |
| 用户体验 | 5.5 | 6.5 | +1.0 | doctor 命令、全局 CLI、但输出仍全 JSON |
| 安全性 | 5.5 | 5.5 | — | 未变 |
| 参考文档 | 7.5 | 7.5 | — | 未变 |
| **综合** | **6.66** | **7.19** | **+0.53** | |

---

## 三、当前已完成的能力清单

### 3.1 企业一键可用的基础 ✅

| 能力 | 状态 | 证据 |
|------|------|------|
| `pip install -e .` | ✅ | 成功安装 |
| `e2e-dev-harness --version` | ✅ | 输出 0.2.0 |
| `e2e-dev-harness doctor .` | ✅ | 检查 Python/pytest/Maven/GitNexus/hooks |
| 全局 CLI entry point | ✅ | 安装后直接使用 `e2e-dev-harness` |
| 651 测试全绿 | ✅ | 0 失败 |
| Python >=3.10 声明 | ✅ | pyproject.toml |
| 可选依赖管理 | ✅ | tree-sitter、pytest 分组 |
| 变更日志 | ✅ | CHANGELOG.md |

### 3.2 核心机制 ✅

| 能力 | 状态 | 说明 |
|------|------|------|
| 状态机生命周期 | ✅ | 9 阶段，文件级 run-state.json |
| Phase Lock 物理阻止 | ✅ | hook 层拦截未授权代码写入 |
| 证据链 | ✅ | SHA-256 + exit_code + output hash |
| TDD 红绿循环 | ✅ | basic/strict/auto 三模式 |
| 三轮独立审查 | ✅ | R1/R2/R3 独立 agent/session |
| 返工路由 | ✅ | 6 种回退映射 |
| 多服务编排 | ✅ | single/single-review/multi |
| Agent 交接 | ✅ | ready markers + hash 校验 |
| Agent 任务调度 | ✅ | claim/lease/reclaim/complete |
| Review profiles | ✅ | JSON + extends 继承 |
| 跨平台 hook | ✅ | Claude Code/Codex/Gemini CLI |
| 知识图谱集成 | ✅ | GitNexus(主) + Graphify(辅) |
| 跨服务依赖扫描 | ✅ | regex + tree-sitter AST |
| 上下文打包 | ✅ | 文件/字节预算 |
| 记忆选择与捕获 | ✅ | 分层、验证、防重复 |
| 执行追踪 | ✅ | 阶段计时 + token 计数 |
| 运行摘要 | ✅ | JSON/MD 双格式 |
| CI 集成 | ✅ | GitHub Actions 模板 |
| Spring 静态检查 | ✅ | MQ routing、注入检查 |

---

## 四、当前仍然存在的关键问题

### P0：架构债务（阻碍规模化）

#### 4.1 主入口单体 — `e2e_dev_harness.py`（2,111 行）

**问题**：单一文件承担了 14 个子命令路由 + 13 个模板函数（~381 行 f-string）+ CLI 参数定义 + 所有业务逻辑。

**影响**：
- 企业用户无法定制模板而不改源码
- 新增子命令需要理解 2,111 行代码
- 代码审查困难

**13 个硬编码模板函数**：
```
design_template, service_design_template, coverage_matrix_template,
impact_summary_template, impact_evidence_template, test_impact_plan_template,
implementation_manifest_template, unit_test_evidence_template,
requirements_archive_template, review_checklist_template,
review_request_template, semantic_review_template, service_plan_template
```

**建议**：拆分为 `commands/` 子目录（每命令一模块）+ `templates/` 目录（Markdown/JSON 文件）。

#### 4.2 测试文件巨型单体 — `test_e2e_dev_harness_scripts.py`（10,061 行）

**问题**：占全部测试代码的 47%，包含 29 个测试类。

**影响**：
- 定位失败测试困难
- 与其他专项测试文件有重复
- CI 并行化困难

**建议**：按脚本名拆分为 `test_<script_name>.py`，每个文件 200-500 行。

### P1：可扩展性（阻碍企业定制）

#### 4.3 无插件/扩展机制

当前无法在不改源码的情况下：
- 注册自定义 lifecycle 阶段（如 `SECURITY_REVIEW`）
- 注册自定义 gate（如对接 SonarQube）
- 替换模板格式（如多语言团队）
- 自定义 rework routing
- 注册自定义 scanner（如 Go/TypeScript 项目）

**建议**：设计 `harness-plugins.json` 配置 + Python entry_points 机制。

#### 4.4 技术栈锁定 Java/Spring/Maven

Scanner、Spring static check、Maven test-impact 全部 Java 专用。企业如果有 Go/Python/TypeScript 微服务，无法使用。

**建议**：抽象 scanner 接口，提供 Go/TypeScript scanner 插件示例。

### P2：用户体验（阻碍日常使用）

#### 4.5 CLI 输出全 JSON

所有输出都是 JSON，即使是 `doctor` 和 `next` 这种人读命令。企业用户需要：
- 彩色终端输出（红/黄/绿状态）
- `--verbose` / `--quiet` 分级
- 人类友好的表格/列表
- 进度指示

**建议**：添加 `--format json|text|table` 参数，默认 text。

#### 4.6 无 Quickstart 教程

README 直接进入命令参考，缺少"5 分钟上手"引导。

**建议**：添加 `docs/quickstart.md`，包含一个完整的单服务 basic 层级端到端示例。

#### 4.7 Scaffold 示例简陋

只有 4 个 Java 文件 + 1 个测试，缺少 JPA/MQ/Security/Testcontainers 示例。

**建议**：提供 `scaffold/` 目录，包含 basic/standard/critical 三种示例项目。

### P3：生产加固

#### 4.8 安全风险

| 风险 | 严重性 | 位置 |
|------|--------|------|
| `command_evidence.py` 执行用户命令无白名单 | 高 | subprocess.run(--command) |
| `install_hooks.py` 修改 settings.json 无原子写入 | 中 | 无备份机制 |
| `phase_guard.py` stdin 无大小限制 | 中 | hook 输入未校验 |

#### 4.9 多 Agent 并发安全

当前依赖文件系统锁，无 fcntl/msvcrt 锁，高并发下可能竞态。

#### 4.10 缺少结构化日志

所有输出都是 print/JSON，无 logging 模块。企业需要 ELK/Grafana 集成。

#### 4.11 run-state 无 schema version

升级时无法自动迁移旧格式。

---

## 五、改进路线图（更新版）

### Phase 1：修复基线 ✅ 已完成

| # | 改进项 | 状态 |
|---|--------|------|
| 1 | 修复全部失败测试 | ✅ 651/651 通过 |
| 2 | 添加 pyproject.toml | ✅ 可 pip install |
| 3 | 添加 --version + CHANGELOG | ✅ 0.2.0 |
| 4 | 添加 doctor 命令 | ✅ 环境自检 |
| 5 | 添加 stop guard | ✅ 停止守卫 |

### Phase 2：架构解耦（5-7 天）← 当前阶段

| # | 改进项 | 工作量 | 优先级 | 交付物 |
|---|--------|--------|--------|--------|
| 6 | 拆分 e2e_dev_harness.py | 3-4 天 | P0 | commands/ 子目录 + 共享 core 层 + CLI 薄壳 |
| 7 | 模板外置 | 1-2 天 | P0 | templates/ 目录（13 个 .md/.json 文件） |
| 8 | 拆分 test_e2e_dev_harness_scripts.py | 1 天 | P0 | 按脚本一一对应拆分 |
| 9 | run-state schema version | 0.5 天 | P1 | version 字段 + 迁移工具 |

**Phase 2 完成标志**：无超过 500 行的 Python 文件、模板可外部替换、测试文件与源码一一对应。

### Phase 3：可扩展性 + 体验（5-7 天）

| # | 改进项 | 工作量 | 优先级 | 交付物 |
|---|--------|--------|--------|--------|
| 10 | 插件/扩展点机制 | 3-4 天 | P1 | 可注册 gate/lifecycle/scanner/template |
| 11 | CLI 人性化输出 | 1-2 天 | P2 | 彩色、表格、--format json\|text |
| 12 | Quickstart 教程 | 1 天 | P2 | docs/quickstart.md |
| 13 | 丰富 scaffold 项目 | 2-3 天 | P2 | Spring/JPA/MQ/Testcontainers 示例 |
| 14 | 非 Java scanner 示例 | 2 天 | P2 | Go 或 TypeScript scanner 插件 |

**Phase 3 完成标志**：企业可注册自定义 gate、CLI 有人类友好输出、新用户 30 分钟可上手。

### Phase 4：生产加固（持续）

| # | 改进项 | 工作量 | 优先级 |
|---|--------|--------|--------|
| 15 | command_evidence 命令白名单 | 1 天 | P3 |
| 16 | 多 Agent 并发安全（文件锁增强） | 2-3 天 | P3 |
| 17 | 结构化日志（logging 模块） | 1-2 天 | P3 |
| 18 | 大 monorepo 性能基准 | 2-3 天 | P3 |
| 19 | 多 CI 平台模板 | 1 天 | P3 |
| 20 | 测试覆盖率报告（pytest-cov） | 0.5 天 | P3 |

---

## 六、企业"一键可用"差距分析

### 6.1 什么已经"一键可用"

```bash
# 安装
pip install -e .

# 验证环境
e2e-dev-harness doctor .

# 启动开发
e2e-dev-harness start . --feature "add refund" --request "实现退款功能"

# 查看下一步
e2e-dev-harness next . --state docs/agent-runs/<run>/run-state.json
```

这三步已经可以工作了。✅

### 6.2 什么还不够"一键可用"

| 场景 | 当前体验 | 理想体验 | 差距 |
|------|----------|----------|------|
| 自定义模板 | 改源码 | 编辑 templates/*.md | Phase 2 |
| 非 Java 项目 | 不支持 | 自动检测 + 对应 scanner | Phase 3 |
| 对接内部 CI | 手写脚本 | doctor --ci=gitlab 生成配置 | Phase 3-4 |
| 日志集成 | 无 | 自动输出到 ELK | Phase 4 |
| 团队共享配置 | 无 | .e2e/harness-config.json 继承 | Phase 3 |
| 多语言设计文档 | 不支持 | 模板可替换 | Phase 2 |

### 6.3 "企业一键可用"的关键定义

对企业而言，"一键可用"意味着：

1. **安装一键** ✅ `pip install e2e-dev-harness`（已完成）
2. **验证一键** ✅ `e2e-dev-harness doctor .`（已完成）
3. **启动一键** ✅ `e2e-dev-harness start .`（已完成）
4. **定制不需要改源码** ❌ 当前改模板要改 Python（Phase 2）
5. **非 Java 项目可用** ❌ 当前只有 Java scanner（Phase 3）
6. **团队配置可共享** ❌ 当前无团队配置机制（Phase 3）
7. **CI 集成开箱即用** ⚠️ 有 GitHub Actions 模板，但无 GitLab/Jenkins（Phase 4）

---

## 七、成熟度判定

```
                        上次    本次
                          ↓      ↓
概念验证（POC）     ████████████████████████████░░░░  ← 上次
原型可用            ██████████████████████████████░░  ← 上次边界
内部工具可用        ████████████████████████████████  ← 当前位置
企业级可用          ████████████████████████████░░░░  Phase 2-3
生产级成熟          ████████████████████████░░░░░░░░  Phase 4
```

**当前位置：内部工具可用（Phase 1 完成）**

- 安装、验证、启动三步走通
- 651 测试全绿，核心机制可靠
- CLI 全局可用，doctor 自检
- 但定制需改源码，非 Java 项目不支持

---

## 八、核心结论

### 做对了什么（继续坚持）

1. **Phase 1 执行力强** — 45 个测试失败在 1 天内全部修复，新增 doctor/stop_guard
2. **包管理到位** — pyproject.toml、entry_points、可选依赖、Python 版本约束
3. **doctor 命令** — 一键检查 Python/pytest/Maven/GitNexus/hooks，降低上手门槛
4. **核心机制零回归** — 状态机、文件锁、证据链、门禁判定全部稳定

### 下一步必须做什么

| 优先级 | 任务 | 一句话 |
|--------|------|--------|
| **P0** | 拆分主入口 + 模板外置 | 2,111 行单文件是企业采用的硬阻断 |
| **P0** | 拆分测试巨型单体 | 10,061 行测试文件是维护的硬阻断 |
| P1 | 插件扩展机制 | 无法定制 gate/lifecycle 是企业采用的软阻断 |
| P2 | CLI 人性化 + Quickstart | 全 JSON 输出是日常使用的体验阻断 |
| P2 | 非 Java scanner | 只支持 Java 是用户群的硬边界 |

### 一句话总结

**Phase 1 已完成（651 测试全绿、可安装、有 doctor），从"原型可用"升级到"内部工具可用"。Phase 2（架构解耦：拆主入口、外置模板、拆测试）是通往"企业级可用"的下一个硬门槛，预计 5-7 天。**
