# E2E Dev Harness 全面审计报告

> **审计日期**: 2026-06-09
> **审计范围**: 全项目（架构、代码质量、CLI、Skill 描述、全链路流程）
> **审计方法**: 5 个专项 Agent 并行分析
> **项目规模**: Python 8864 行 + JavaScript 433 行，287 个测试全部通过

---

## 目录

1. [总体评价](#1-总体评价)
2. [架构分析](#2-架构分析)
3. [全链路流程与门禁检查](#3-全链路流程与门禁检查)
4. [潜在问题与安全隐患](#4-潜在问题与安全隐患)
5. [CLI 功能检查](#5-cli-功能检查)
6. [Skill 描述审计](#6-skill-描述审计)
7. [综合问题清单](#7-综合问题清单)
8. [各维度评分](#8-各维度评分)
9. [优先执行路线](#9-优先执行路线)

---

## 1. 总体评价

E2E Dev Harness 是一个 **架构设计成熟的 Agent 工作流引擎**，采用六边形架构（core/adapters/cli 三层分离），声明式流水线驱动需求从 CREATED 到 VERIFIED 的完整生命周期。项目在以下方面表现优秀：

- **架构设计**: 核心层纯净无 I/O，适配器层封装外部交互，职责分离清晰
- **跨平台兼容**: Windows/macOS/Linux 全面覆盖，是项目亮点
- **声明式流水线**: YAML 配置阶段序列，扩展性极强
- **SSOT 状态管理**: 单一 run-state JSON + 原子写入 + 并发锁 + Schema 版本化
- **协议接口**: DomainAdapter 使用 Python Protocol，支持多领域扩展
- **数学不变量**: I1 终止性 + I2 门禁闭包，由代码和测试严格保证

主要改进方向：
1. 补充核心逻辑的测试覆盖（当前为零）
2. 重构遗留代码，消除 sys.path hack
3. 修复 Skill 描述冲突和 Graphify 过长问题
4. 加强安全敏感路径的防护

---

## 2. 架构分析

### 2.1 架构概览

项目采用 **双语言混合架构**：Node.js 负责工具侧（安装/初始化/CLI 入口），Python 负责核心控制面逻辑。

```
项目根目录
 |
 +-- bin/e2e-harness.js              [Node CLI 入口 -- 路由器]
 |     |
 |     +-- lib/                       [Node 工具层]
 |           hooks.js                 - Hook 模板替换与合并
 |           init.js                  - 项目初始化编排
 |           install.js               - Skill 安装到本地机器
 |           lifecycle.js             - 版本/自检/卸载/npm link
 |           paths.js                 - Python 解析/Skill Home 路径
 |           resolve.js               - 命令路由 -> Python 脚本
 |
 +-- skills/e2e-dev-harness/          [核心 Skill 包]
       |
       SKILL.md                       [Skill 描述 -- agent 读取入口]
       hooks/                         [Hook 模板]
       pipelines/                     [声明式流水线 YAML]
       scripts/
            e2e_dev_harness.py        [Python CLI 入口垫片]
            e2e_harness/
              |
              cli/                    [CLI 层 -- 6 个动词]
              |   main.py             - argparse 路由
              |   commands/           - start/next/dispatch/submit/gate/status/validate-pipeline
              |
              core/                   [核心域层 -- 纯逻辑，无 I/O]
              |   lifecycle.py        - Phase 数据类 + 阶段目录
              |   run_state.py        - SSOT run-state (JSON, 版本化, 原子写入, 并发锁)
              |   pipeline.py         - YAML 流水线加载 -> spine 构建
              |   gates.py            - 声明式门禁评估 + 闭包不变量
              |   engine.py           - 状态推进引擎 + 证据提交
              |   dispatch.py         - Worker 分派状态枚举 + 包指针
              |   navigation.py       - 派生导航地图
              |   pipeline_validate.py - 流水线规范验证
              |
              adapters/               [适配器层 -- 外部系统接入]
                  domain/             - 领域适配器 (backend/frontend, Protocol 接口)
                  evidence/           - 证据验证 (哈希/命令证据/校验)
                  hooks/              - 运行时 Hook (phase_guard/stop_guard/paths)
                  runtime/            - 运行时适配器 (claude-code/codex/opencode/manual)
                  tier/               - Tier 分类器
                  scanner/            - 代码扫描器 (含 _legacy/)
                  kg/                 - 知识图谱刷新 (含 _legacy/)
                  memory/             - 记忆捕获 (含 _legacy/)
```

### 2.2 关注点分离

**优点**:
- core/ 层完全纯净，无文件 I/O（除 run_state.py 负责状态持久化）
- adapters/ 层封装了所有外部交互
- DomainAdapter 使用 Python Protocol 定义接口，backend 和 frontend 通过 registry 模式按优先级自动检测

**问题**:
- `run_state.py` 身兼两职：数据模型 + 并发锁机制
- `engine.py` 职责混杂：证据提交和 dispatch 状态更新耦合，门禁评估和状态推进耦合
- `pipeline.py` 位于 `e2e_harness/` 顶层包，被 core/engine 和 cli 同时引用，层级定位不清

### 2.3 扩展性

**优秀的扩展性设计**:

| 扩展点 | 机制 | 新增成本 |
|--------|------|---------|
| 新流水线 | 新增 YAML 文件 | 仅配置 |
| 新领域 | 实现 DomainAdapter Protocol + 注册 | 仅 adapter |
| 新运行时 | 添加 `_xxx(packet)` 函数 | 仅函数 |
| 新证据类型 | 在 `COMMAND_KEYS` 字典注册 | 仅配置 |

**扩展性不足**:
- Phase 目录 (`_CATALOG`) 硬编码，新增阶段类型需修改源码
- Tier 分类关键字全部硬编码，不支持外部配置
- 门禁校验逻辑简单（仅证据存在性），不支持条件性门禁

### 2.4 依赖关系

依赖方向总体遵循 **cli -> adapters -> core**，core 层不依赖任何外层模块。

**依赖问题**:
- `pipeline.py` 的桥接角色形成隐式循环：`core/engine -> e2e_harness.pipeline -> core/lifecycle`
- Legacy 模块的 `sys.path.insert(0, ...)` 反模式散布于 15+ 处
- `e2e_dev_harness.py` 入口垫片与 `pyproject.toml` 可编辑安装功能重叠

### 2.5 技术债

| 优先级 | 技术债 | 规模 | 风险 |
|--------|--------|------|------|
| 高 | Legacy 代码未清理 | ~3000+ 行 | bug 难追踪，重构易遗漏 |
| 高 | Core 层零单元测试 | 6 个模块 | 回归难以检测 |
| 中 | 缺少类型系统 | 全局 | 重构信心不足 |
| 中 | 测试覆盖不均衡 | Node 有/Python 少 | Python 端回归风险 |
| 低 | README 过长 | 754 行 | 信息过载 |
| 低 | 临时/缓存目录残留 | 6 个目录 | 视觉噪音 |

---

## 3. 全链路流程与门禁检查

### 3.1 完整流程路径

```
start -> CREATED
  -> next -> CLARIFIED (clarification worker)
    -> submit -> next -> [PLANNED (plan worker)]      (minimal tier 跳过)
      -> submit -> next -> RED (tdd-red worker)
        -> submit -> next -> IMPLEMENTED (implementation worker)
          -> submit -> next -> [REVIEWED (review worker(s))]  (minimal tier 跳过)
            -> submit -> next -> VERIFIED (completion worker)
```

### 3.2 三层门禁体系

| 层 | 位置 | 作用 | 评价 |
|---|---|---|---|
| **I2 门禁闭包** | `core/gates.py` | 启动前验证所有 exit_gate 引用的证据键都有产出阶段 | 优秀 -- 不存在不可满足的门禁 |
| **阶段门禁** | `core/gates.py` | 验证证据文件存在、非空、SHA256 哈希匹配、退出码正确 | 良好 -- 验证真实产物而非标记位 |
| **PreToolUse Hook** | `adapters/hooks/phase_guard.py` | 阻止在非 `allows_code_write` 阶段写入代码文件 | 有问题 -- RED 阶段被阻止 |

### 3.3 死锁分析

**不存在循环依赖**。Pipeline 是严格的线性链（I1 终止性不变量保证），`pipeline_validate.py` 验证了 spine 恰好有一个终端阶段且无重复阶段名。

**文件锁竞态风险**:
- Windows 上 `O_EXCL` 锁在 `close -> unlink` 间存在微小竞态窗口
- `os.replace` 在 NTFS 上如果目标被锁定（杀毒软件扫描）可能失败，无重试
- Critical tier 的 r1/r2/r3 reviewer 并行 spawn，如果其中一个崩溃，整个流程被阻塞，无部分推进机制

### 3.4 状态机分析

**Dispatch 生命周期**:
```
(implicit PENDING) -> DISPATCHED -> DONE
                                 -> FAILED
                (reserved) -> RUNNING  [不可达 -- 预留给 runtime adapter]
```

**Pipeline 阶段**:
```
CREATED -> CLARIFIED -> [PLANNED] -> RED -> IMPLEMENTED -> [REVIEWED] -> VERIFIED
```

无不可达状态（除 RUNNING），无不可退出状态，被 tier 裁剪的阶段标记为 `skipped`。

### 3.5 全链路发现的问题

| # | 问题 | 严重度 | 位置 |
|---|------|--------|------|
| F-1 | RED 阶段 `allows_code_write=false` 阻止测试文件写入 | **高** | `pipelines/*.yaml`, `phase_guard.py` |
| F-2 | Worker 崩溃后 DISPATCHED 状态无超时恢复 | **高** | `dispatch.py`, SKILL.md |
| F-3 | `--tier auto` 不自动扫描，可能低估风险 | **高** | `start.py` |
| F-4 | 缺少阶段停滞超时告警 | 中 | `engine.py` / `navigation.py` |
| F-5 | 失败后重试路径未文档化 | 中 | SKILL.md |
| F-6 | Critical tier review fan-out 无部分降级 | 中 | `gates.py`, `engine.py` |
| F-7 | 无阶段回退机制 | 中 | engine 层 |
| F-8 | Tier 不支持运行时降级 | 中 | `start.py`, `run_state.py` |
| F-9 | RUNNING 状态已定义但不可达 | 低 | `dispatch.py` |
| F-10 | Navigation map 不显示 blocker 原因 | 低 | `navigation.py` |
| F-11 | 锁超时 TimeoutError 未被 CLI 特别处理 | 低 | `main.py` |
| F-12 | `discover_run_state` 取最新而非活跃 run | 低 | `paths.py` |

---

## 4. 潜在问题与安全隐患

### 4.1 安全问题

| # | 问题 | 严重度 | 文件 | 说明 |
|---|------|--------|------|------|
| S-1 | 动态模块加载无安全校验 | **高** | `plugin_registry.py` | 将仓库内 `.e2e/providers/` 加入 sys.path 并动态导入任意模块 |
| S-2 | `shlex.split` 在 Windows 上的行为 | 中 | `command_evidence.py` | 强制 `posix=True`，Windows 路径反斜杠被当作转义符 |
| S-3 | 修改全局 node_modules | 低 | `fix-gitnexus-fts.js` | 直接修改 GitNexus 包文件，npm update 后会丢失 |
| S-4 | 拒绝消息中包含路径注入风险 | 低 | `phase_guard.py` | 用户提供的路径直接嵌入消息，日志系统处理时可能注入 |

### 4.2 潜在 Bug

| # | 问题 | 严重度 | 文件 | 说明 |
|---|------|--------|------|------|
| B-1 | Windows 文件锁竞态 | 中 | `run_state.py` | `O_EXCL` 锁在极端并发下有微小风险 |
| B-2 | 临时文件名仅基于 PID | 低 | `run_state.py` | 同进程多线程或崩溃残留时可能冲突 |
| B-3 | 损坏 JSON 静默丢弃 | 低 | `hooks.js` | `readJsonOrEmpty` 吞掉解析错误，可能导致用户设置丢失 |
| B-4 | Regex fallback 与 AST 结果不一致 | 低 | `cross_service_dependency_scan.py` | 无声降级导致分析结果环境间不一致 |

### 4.3 性能瓶颈

| # | 问题 | 严重度 | 文件 | 说明 |
|---|------|--------|------|------|
| P-1 | 5 次独立文件树遍历 | **高** | `cross_service_dependency_scan.py` | 大型 Java 仓库下 O(n^2) 级别性能问题 |
| P-2 | Jaccard 相似度 O(n^2) 去重 | 中 | `memory_capture.py` | 内存条目数百条时变慢 |
| P-3 | 每个 Java 文件读取 3 次 | 低 | `kg_refresh.py` | `contains_text` 对每个文件检查 3 个注解 |

### 4.4 健壮性问题

| # | 问题 | 严重度 | 说明 |
|---|------|--------|------|
| R-1 | 15+ 处裸 `except Exception` 吞掉异常 | **高** | 真正的错误被完全隐藏，调试困难 |
| R-2 | 锁文件残留无清理 | 中 | 进程崩溃后残留锁文件，需等待 10 秒超时 |
| R-3 | 写入回滚不完整 | 中 | `hooks.js` 恢复备份失败时 settings.json 可能损坏 |
| R-4 | 缺少全局日志系统 | 中 | 整个 Python 代码库未使用 `logging` 模块 |

### 4.5 可维护性问题

| # | 问题 | 严重度 | 说明 |
|---|------|--------|------|
| M-1 | `common.py` 重复三份 | **高** | `_legacy/` 下三个副本，违反 DRY 原则 |
| M-2 | `sys.path.insert` 反模式 15+ 处 | **高** | 导致模块名冲突和导入解析混乱 |
| M-3 | `memory_capture.py` 1211 行过大 | 中 | 承担过多职责 |
| M-4 | 硬编码管道阶段名称 | 低 | 字符串比较，拼写出错无编译时错误 |

### 4.6 测试覆盖缺口

| 缺失测试 | 文件 | 风险 |
|----------|------|------|
| Core 层单元测试 | `engine.py`, `gates.py`, `navigation.py`, `dispatch.py` | 回归风险高 |
| `plugin_registry.py` | 动态加载无测试 | 安全敏感路径 |
| Node.js `resolve.js` | 边界条件未测试 | 路径遍历等 |
| `fix-gitnexus-fts.js` | 完全无测试 | 修改第三方代码 |
| `exec` 命令 | CLI 无测试 | 命令路由 |

### 4.7 依赖风险

| 依赖 | 版本 | 风险 |
|------|------|------|
| `pyyaml` | `>=6` | 唯一运行时 Python 依赖，建议锁定 `<7` |
| `tree_sitter` | `>=0.22` | API 变化大，需明确最低支持版本 |
| Node.js | 零运行时依赖 | 极好，完全消除供应链风险 |
| Python | `>=3.10` | 合理，EOL 2026-10 |

---

## 5. CLI 功能检查

### 5.1 命令覆盖

**Node.js 层（8 个命令）**: link, unlink, install, update, uninstall, env, version, init

**Python 层（7 个动词 + 1 通用）**: start, next, dispatch, submit, gate, status, validate-pipeline, exec

**缺失命令**: `list-pipelines`, `list-phases`, `show-pipeline`（辅助查询命令）

### 5.2 各维度评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整性 | **A** | 15 个命令覆盖完整生命周期 |
| 入口点配置 | **A** | package.json 正确，入口文件存在且有正确 shebang |
| 错误处理 | **A-** | 全链路 JSON 错误输出，缺少开发模式调试信息 |
| 参数验证 | **A** | argparse + 手写验证 + pipeline 校验三重保障 |
| 跨平台兼容 | **A+** | Windows/macOS/Linux 全面覆盖，是项目亮点 |
| 用户体验 | **B+** | JSON 输出规范，缺少 `--quiet`/`--verbose`/彩色输出 |
| 集成测试 | **A-** | Python 端到端测试全面，Node.js CLI 层有缺口 |

### 5.3 CLI 发现的问题

| # | 问题 | 严重度 | 位置 |
|---|------|--------|------|
| C-1 | 缺少辅助查询命令 | 低 | Node.js CLI |
| C-2 | Node.js CLI 层无单元测试 | 低 | `test/` |
| C-3 | Python 错误缺少调试模式堆栈 | 低 | `main.py` |
| C-4 | 缺少 `--quiet`/`--verbose` 输出控制 | 低 | Node.js CLI |
| C-5 | Python 错误 JSON 无错误码分类 | 低 | `main.py` |
| C-6 | `exec` 命令无测试 | 低 | CLI |
| C-7 | `init` 命令无端到端测试 | 低 | CLI |

### 5.4 跨平台兼容性亮点

- `detectPython()` 在 Windows 上尝试 `['python', 'python3', 'py']`
- `npmBinary()` 在 Windows 上返回 `'npm.cmd'`
- `commandMatches()` 在 Windows 上使用 `where` 而非 `which`
- `toShellScriptsDir()` 将反斜杠转正斜杠（hook 通过 bash 执行）
- `pre-merge-check.mjs` 在 Windows 上使用 `cmd.exe /d /s /c`
- `run_state.py` 使用 `os.replace()` 做原子写入（跨平台安全）

---

## 6. Skill 描述审计

### 6.1 审计范围

- 项目本地 `.claude/skills/gitnexus/` 下 6 个 SKILL.md
- 全局 `~/.claude/skills/` 下 8 个 SKILL.md
- 项目根目录 CLAUDE.md

### 6.2 高优先级问题

| # | 问题 | 文件 | 说明 |
|---|------|------|------|
| K-1 | Graphify 命名三件不一致 | `graphify/SKILL.md` | 目录名 `graphify` / name `graphify-windows` / trigger `/graphify` |
| K-2 | Graphify 描述过宽与 GitNexus 冲突 | `graphify/SKILL.md` | "any question about a codebase" 与 gitnexus-exploring 高度重叠 |
| K-3 | Graphify 1435 行过长 | `graphify/SKILL.md` | 严重挑战大模型上下文窗口和注意力 |
| K-4 | GitNexus Schema 不完整 | `gitnexus-guide/SKILL.md` | 仅列 7 种节点/7 种边，实际支持 20+ 种 |
| K-5 | GitNexus-pr-review 项目本地缺失 | `.claude/skills/gitnexus/` | 仅存在于全局，CLAUDE.md 未列出 |

### 6.3 Graphify 详细问题

| 维度 | 问题 |
|------|------|
| **长度** | 1435 行，远超大模型有效注意力范围 |
| **结构** | Step 编号不连续（2, 2.5, 3A, 3B0-3B3, 3C, 4-9, 7b, 7c, 7d） |
| **平台** | 所有脚本为 PowerShell，无 Linux/macOS 支持，但未标注平台限制 |
| **子代理** | Step B2 要求 Agent 工具，但无回退方案 |
| **约束** | MANDATORY / NEVER / MUST 分散在 1400+ 行多处，难以追踪 |

### 6.4 中优先级问题

| # | 问题 | 说明 |
|---|------|------|
| K-6 | gitnexus-exploring 与 debugging 触发条件重叠 | "What calls this function?" 同时出现在两者中 |
| K-7 | 所有 gitnexus skill 未处理索引不存在的情况 | 首次使用引导不够 |
| K-8 | gitnexus-impact-analysis 未提及跨仓库分析 | MCP 工具支持但 skill 未描述 |
| K-9 | CLAUDE.md "MUST run impact analysis" 过度强制 | 包括拼写修复、注释修改等低风险变更 |

### 6.5 命名一致性问题

| 位置 | 不一致 |
|------|--------|
| 项目本地 vs 全局 | 本地嵌套结构 `.claude/skills/gitnexus/gitnexus-cli/`，全局扁平 `~/.claude/skills/gitnexus-cli/` |
| Graphify | 目录 `graphify` / name `graphify-windows` / trigger `/graphify` |
| gitnexus-pr-review | 仅全局存在，项目本地缺失 |
| Worktree 副本 | 4 个 worktree 各持 skill 副本，不自动同步 |

---

## 7. 综合问题清单

### 高优先级（必须处理）

| 编号 | 问题 | 来源 | 影响 |
|------|------|------|------|
| **H-1** | RED 阶段 `allows_code_write=false` 阻止测试写入 | 全链路 | TDD 流程可能被 phase guard 拦截 |
| **H-2** | Core 层零单元测试 | 架构+潜在 | 核心逻辑回归难以检测 |
| **H-3** | 动态模块加载无安全校验 | 潜在问题 | 恶意代码执行风险 |
| **H-4** | 15+ 处静默吞掉异常 | 潜在问题 | 生产环境调试极度困难 |
| **H-5** | Graphify 1435 行过长，描述冲突 | Skill 审计 | 大模型可能误判或遗漏约束 |
| **H-6** | Worker 崩溃无自动恢复 | 全链路 | DISPATCHED 状态永久停留 |
| **H-7** | `--tier auto` 不自动扫描 | 全链路 | 高风险需求可能走 minimal tier |

### 中优先级（应该尽快处理）

| 编号 | 问题 | 来源 |
|------|------|------|
| **M-1** | Legacy 代码 ~3000+ 行未重构 | 架构 |
| **M-2** | GitNexus Schema 不完整 | Skill 审计 |
| **M-3** | pipeline.py 层级定位不清 | 架构 |
| **M-4** | Windows 文件锁极端竞态 | 潜在问题 |
| **M-5** | 缺少全局日志系统 | 潜在问题 |
| **M-6** | 缺少阶段停滞超时告警 | 全链路 |
| **M-7** | 失败后重试路径未文档化 | 全链路 |
| **M-8** | Tier 不支持运行时降级 | 全链路 |
| **M-9** | 锁文件残留无清理 | 潜在问题 |
| **M-10** | 写入回滚不完整 | 潜在问题 |
| **M-11** | common.py 重复三份 | 潜在问题 |
| **M-12** | sys.path.insert 反模式 15+ 处 | 潜在问题 |

### 低优先级（改善质量）

| 编号 | 问题 | 来源 |
|------|------|------|
| **L-1** | 缺少 `list-pipelines` 等辅助命令 | CLI |
| **L-2** | Node.js CLI 层无单元测试 | CLI |
| **L-3** | Python 错误缺少调试模式堆栈 | CLI |
| **L-4** | 缺少 `--quiet`/`--verbose` 输出控制 | CLI |
| **L-5** | gitnexus-exploring 与 debugging 触发条件重叠 | Skill |
| **L-6** | README 过长 754 行 | 架构 |
| **L-7** | 两个测试目录 test/ 和 tests/ 命名不一致 | 架构 |
| **L-8** | memory_capture.py 1211 行过大 | 潜在问题 |
| **L-9** | shlex.split 在 Windows 上的路径解析 | 潜在问题 |
| **L-10** | hooks.js 损坏 JSON 静默丢弃 | 潜在问题 |
| **L-11** | `discover_run_state` 取最新而非活跃 run | 全链路 |
| **L-12** | RUNNING 状态已定义但不可达 | 全链路 |
| **L-13** | Navigation map 不显示 blocker 原因 | 全链路 |
| **L-14** | `exec` 命令无测试 | CLI |
| **L-15** | 临时/缓存目录残留在项目树 | 架构 |

---

## 8. 各维度评分

| 维度 | 评分 | 关键发现 |
|------|------|---------|
| **架构设计** | A | 六边形架构清晰，声明式流水线扩展性强，Protocol 接口设计好 |
| **跨平台兼容** | A+ | Windows/macOS/Linux 全面覆盖，是项目最大亮点 |
| **测试覆盖** | B | CLI 端到端 287 个测试优秀，但 core 层零单元测试 |
| **安全性** | B- | yaml.safe_load、O_EXCL 锁良好，但动态加载和静默异常有风险 |
| **Skill 描述** | B- | gitnexus 系列优秀，graphify 过长且描述冲突严重 |
| **CLI 功能** | A- | 15 命令覆盖完整生命周期，缺少辅助查询命令 |
| **可维护性** | B | legacy 代码 3000+ 行未清理，sys.path hack 散布 15+ 处 |
| **健壮性** | B | SSOT + 原子写入 + 并发锁设计好，但崩溃恢复和日志不足 |
| **性能** | B- | 核心流程无明显瓶颈，legacy scanner 有 O(n^2) 问题 |

**综合评分: B+**

---

## 9. 优先执行路线

### Phase 1 -- 立即修复（1-2 天）

| 任务 | 关联问题 | 预估工时 |
|------|---------|---------|
| 修复 RED 阶段 `allows_code_write` | H-1 | 2h |
| 修复 Graphify 命名一致性 | H-5 | 1h |
| 缩窄 Graphify 描述触发范围 | H-5 | 1h |
| `--tier auto` 默认启用 scan | H-7 | 2h |

### Phase 2 -- 本周完成（3-5 天）

| 任务 | 关联问题 | 预估工时 |
|------|---------|---------|
| 补充 core 层单元测试 | H-2 | 2-3 天 |
| 引入统一日志模块 | M-5 | 4h |
| 加强 plugin_registry 安全 | H-3 | 4h |
| 补全 GitNexus Schema | M-2 | 2h |
| 补充 Worker 超时恢复机制 | H-6 | 4h |

### Phase 3 -- 下周完成（3-5 天）

| 任务 | 关联问题 | 预估工时 |
|------|---------|---------|
| 重构 legacy 代码 | M-1 | 3-5 天 |
| pipeline.py 归入 core 层 | M-3 | 2h |
| 统一 sys.path 处理 | M-12 | 4h |
| 合并重复 common.py | M-11 | 2h |
| 拆分 graphify 为子 skill | H-5 | 1 天 |

### Phase 4 -- 后续优化（持续）

| 任务 | 关联问题 |
|------|---------|
| Tier 运行时降级 | M-8 |
| 阶段回退机制 | M-7 |
| Node.js CLI 单元测试 | L-2 |
| 拆分 README | L-6 |
| 引入 Python 静态类型检查 | 架构 |
| 结构化日志 | 架构 |

---

> 报告由 5 个专项 Agent 并行生成，经人工审核汇总。
>
> Agent 1: 潜在问题与提升空间分析 | Agent 2: 全链路门禁与死锁检查
> Agent 3: Skill 描述准确性审计 | Agent 4: CLI 功能完整性检查
> Agent 5: 架构全局优化分析
