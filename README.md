# E2E Dev Harness

一个**与运行时无关（agent-neutral）的多 agent 交付 harness**：把一个需求变成
"澄清 → 规划 → TDD → 实现 →（审查）→ 验证"的多 agent 流程，并通过**单一事实源
（SSOT）run-state、声明式分级门禁、自加载 Superpowers 技能的 worker 子 agent，以及可选的
运行时 Hook**，**保证流程跑到 `VERIFIED` 才结束**。

它不是单纯的流程文档，而是一套可被机器校验的控制面。可在 **Codex、Claude Code、Gemini CLI、
OpenCode、CI 任务**，以及任何"能读 `SKILL.md` 并执行随包 Python 脚本"的运行时上工作。
默认领域适配器面向 **Java / Spring / Maven**，并内置 **frontend** 适配器。

> 本仓库自身被 GitNexus 索引为 **e2e-dev-workflow**。改动代码符号前请按 `CLAUDE.md` 的约定
> 先做 GitNexus 影响分析；本 README 仅为文档，不在该约束内。

---

## 目录

- [核心保证](#核心保证)
- [两个包、两个 CLI（先看这里）](#两个包两个-cli先看这里)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [安装器 CLI：`e2e-harness`（Node）](#安装器-clie2e-harnessnode)
- [控制面：8 个动词（Python）](#控制面8-个动词python)
- [执行循环](#执行循环)
- [tier 与流水线](#tier-与流水线)
- [领域适配器（DomainAdapter）](#领域适配器domainadapter)
- [Agent-Team 派发与 worker 技能](#agent-team-派发与-worker-技能)
- [run 归档目录](#run-归档目录)
- [门禁与证据语义](#门禁与证据语义)
- [运行时 Hook（强制执行）](#运行时-hook强制执行)
- [验证 Hook 行为](#验证-hook-行为)
- [非 ASCII 需求与编码](#非-ascii-需求与编码)
- [多运行时安装器与可编辑 Python 安装](#多运行时安装器与可编辑-python-安装)
- [环境变量](#环境变量)
- [GitNexus 集成](#gitnexus-集成)
- [开发与测试](#开发与测试)
- [文档索引](#文档索引)
- [许可证](#许可证)

---

## 核心保证

- **单一事实源**：每个 run 只有一份 `run-state.json`。所有动词读/改它，没有平行调度文件。
- **终止性主干（spine）**：`CREATED → … → VERIFIED`，每一步对照终点，避免局部最优。
- **声明式分级门禁**：门禁按 tier 裁剪、校验**真实产物**（文件存在 + 非空 + 哈希；红/绿测试须为
  带正确退出码的命令证据），通过与否只由证据键决定。
- **协调者只管控制面**：Coordinator 只读 run-state、发 worker packet（指针）、记证据、推进主干，
  **不**亲自做代码探索/设计/TDD/审查/实现。
- **worker 自加载技能**：每个 worker 子 agent 在隔离上下文中**首动作即 invoke 自己的技能**，
  具体方法委派给 Superpowers 技能库。
- **可选硬 Hook**：在支持阻塞式 Hook 的运行时上，实现阶段前的生产代码写入会被拦截、未到
  `VERIFIED` 的提前收尾会被阻止。

---

## 两个包、两个 CLI（先看这里）

仓库里有两套东西，名字相近，职责不同，**务必区分**：

| | npm 包 `e2e-harness` | Python 包 `e2e-dev-harness` |
|---|---|---|
| 角色 | 安装器 + 控制面命令的**薄转发层** | harness **控制面本体** |
| 入口 | `bin/e2e-harness.js` | `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`（控制台脚本 `e2e-dev-harness` / `e2eh`） |
| 命令 | `link`/`unlink`/`install`/`update`/`uninstall`/`env`/`version`/`init` + 转发 8 个动词 | `start`/`next`/`dispatch`/`submit`/`gate`/`status`/`validate-pipeline`/`doctor` |
| 元数据 | `package.json`（v0.2.0） | `pyproject.toml`（v0.2.0，requires-python ≥ 3.10，依赖 `pyyaml>=6`） |

`e2e-harness <verb> ...`（除自有的生命周期/`init` 子命令外）会原样转发给
`e2e_dev_harness.py <verb> ...`。所以下文"控制面 8 动词"既可用 `e2e-harness next --state …`
调用，也可直接 `python …/e2e_dev_harness.py next --state …`。

---

## 目录结构

```text
.
├── bin/e2e-harness.js              # Node CLI：安装器 + 动词转发
├── lib/                            # Node CLI 内部实现
│   ├── paths.js                    #   skillHome / Python 解析 / .harness-env.json
│   ├── install.js  resolve.js      #   拷贝技能 / argv → spawn 描述
│   ├── init.js     lifecycle.js    #   一键初始化 / link 检测 / selfCheck
│   ├── hooks.js    opencode-hooks.js  # Hook 物化（Claude / OpenCode）
├── tools/
│   ├── install-e2e-dev-harness.mjs # 多运行时安装器（Codex/Claude/Gemini/OpenCode）
│   ├── pre-merge-check.mjs         # 合并前总检查（node + pytest + gitnexus）
│   └── clean-pack.mjs
├── skills/e2e-dev-harness/
│   ├── SKILL.md                    # 协调者纪律 + 6 动词 + 循环（中文）
│   ├── pipelines/                  # minimal / standard / critical / audited .yaml
│   ├── agent-teams/                # default-*.yaml：每阶段的 worker 角色编排
│   ├── references/agent-orchestration.md
│   ├── hooks/
│   │   ├── claude-code-settings.example.json   # __HARNESS_SCRIPTS__ 占位模板
│   │   └── opencode-plugin.example.js
│   ├── scripts/
│   │   ├── e2e_dev_harness.py      # CLI 透传入口
│   │   └── e2e_harness/            # Python 包
│   │       ├── cli/                #   main.py + commands/*
│   │       ├── core/               #   run_state / engine / gates / lifecycle / navigation …
│   │       ├── adapters/           #   hooks / runtime / domain / agent_team / evidence / tier …
│   │       └── pipeline.py
│   └── tests/                      # harness Python 测试（64 文件）
├── test/                           # Node CLI 测试（node --test）
├── tests/test_node_installer.py    # 安装器 Python 测试
├── docs/                           # 设计 / 安装器文档
├── pyproject.toml  package.json
```

---

## 快速开始

### 0. 把命令做成全局命令

本包**只在仓库内分发，未发布到 npm**，所以 `npx e2e-harness …` 会 404。先 `npm link` 一次：

```bash
npm link              # 在仓库根目录执行
e2e-harness --version # 任意目录下可直接裸调用
e2e-harness unlink    # 以后想移除全局命令
```

### 1. 安装到本机

```bash
e2e-harness install
```

把随包技能拷到 `~/.claude/skills/e2e-dev-harness`，把所用 Python 解释器记录到
`.harness-env.json`，并把任何旧安装备份到 `~/.claude/skill-backups/`（在 skills 目录之外，
避免备份被再次当成重复技能发现）。

### 2. 在业务仓库里一键初始化

在业务仓库内（或把它的路径作为参数）执行：

```bash
e2e-harness init                 # 目标 = 当前目录
e2e-harness init <business-repo>
```

`init` 一步到位：检测运行时 → **技能缺失则先安装** → 把 `phase_guard` + `stop_guard` 两个
Hook 物化进 `<repo>/.claude/settings.json`（把模板里的 `__HARNESS_SCRIPTS__` 重写为已安装技能的
**绝对** `scripts/` 路径，绝不指向你的检出目录）→ 跑一次 `doctor`。已存在的 `settings.json`
会先备份，合并是幂等的（重复执行不新增）。

可选参数：`--runtime auto|claude|opencode`、`--dry-run`（只预览不写）、`--no-doctor`、
`--force`（即使找不到 Python 也照样写 Hook）。

> 默认只发 Claude 格式 Hook 模板，所以 `init` 总是落到 `.claude/`。检测到 `.opencode/`
> 会改用 OpenCode 插件；检测到只有 `.codex/` 时仍写 Claude 格式 Hook 并给出警告。

### 3. 跑一个 run（控制面）

```bash
S=skills/e2e-dev-harness/scripts/e2e_dev_harness.py

# 创建唯一 run-state（current_phase = CREATED）
python $S start --repo . --feature login --request "实现手机号登录"

# 循环推进：next 给出下一步或单一 blocker
python $S next   --state docs/agent-runs/<run>/run-state.json
python $S dispatch --state docs/agent-runs/<run>/run-state.json
python $S submit --state docs/agent-runs/<run>/run-state.json --phase <P> --key <k> --path <evidence>
python $S gate   --state docs/agent-runs/<run>/run-state.json
python $S status --state docs/agent-runs/<run>/run-state.json   # 人读导航地图
```

---

## 安装器 CLI：`e2e-harness`（Node）

本机生命周期命令：

```bash
e2e-harness link        # 注册全局命令（npm link）
e2e-harness unlink      # 移除全局命令
e2e-harness install     # 拷贝随包技能到 ~/.claude/skills（旧的先备份）
e2e-harness update      # 重新拷贝（同样先备份旧版本）
e2e-harness uninstall   # 删除 ~/.claude/skills/e2e-dev-harness（不动全局命令，需另跑 unlink）
e2e-harness env         # JSON 诊断：node / python / 安装 / link 状态
e2e-harness version     # 打印包名与版本（别名 -v / --version）
```

`env` 在技能未安装或找不到 Python 时退出码非零，可直接当作 CI 就绪探针。

项目命令（在业务仓库内运行；除 `init` 外都转发给 `e2e_dev_harness.py`）：

```bash
e2e-harness init [project-dir] [--runtime auto|claude|opencode] [--dry-run] [--no-doctor] [--force]
e2e-harness start --repo . --feature <f> --request <q> [--tier t] [--pipeline p]
e2e-harness next   --state <s>
e2e-harness dispatch --state <s>
e2e-harness submit --state <s> --phase <P> [--key k] [--path p]
e2e-harness gate   --state <s> [--phase P]
e2e-harness status --state <s>
e2e-harness validate-pipeline --pipeline <p>
e2e-harness doctor . --json
e2e-harness exec <script.py> [args]   # 运行 scripts/<script>.py（裸文件名）
```

> 历史说明：旧版本曾有 `map` / `gc` / `cleanup` / `clarify` / `prepare` / `plan` / `verify` /
> `guard` 等命令，已在 2026-06 的控制面重设计中**移除**。请勿沿用旧文档里的这些命令。

---

## 控制面：8 个动词（Python）

入口 `e2e_dev_harness.py`（= 控制台脚本 `e2e-dev-harness` / `e2eh`）。所有动词**输出 JSON 到 stdout**
（即使在 cp936/GBK 控制台也强制 UTF-8）。

### `start` — 创建唯一 run-state

```bash
python $S start --repo . \
  --feature <feat>            # 或 --feature-file <utf8.txt>
  --request "<原始需求>"      # 或 --request-file <utf8.txt>
  [--tier auto|minimal|standard|critical|audited]   # 默认 auto
  [--pipeline <内建名|yaml路径>]   # 覆盖 --tier 推出的 spine
  [--adapter backend|frontend]     # 强制领域适配器
  [--scan]                         # 跑适配器扫描以抬高 tier 下限
```

写出 `docs/agent-runs/<run_id>/run-state.json`，其中 `run_id = <UTC时间戳>-<feature>`。
输出包含 `run_id`、`run_state`（路径）、`current_phase: CREATED`、`tier`、`pipeline`、
`tier_reasons`、`domain`。`--tier auto` 时分类器读需求文本判定 tier（见下文 G4 下限）。

### `next` — 推进主干或给出单一 blocker

`--state <s>`（必填）、`--repo .`。评估当前 spine：
- 可推进则前进一阶段；
- 否则返回**单一 blocker** + `navigation_map`（全旅程"你在这里"视图）。
- 阶段 `CLARIFIED` 受阻时，额外列出仍待用户确认的 `open_questions`（澄清→回答→重提→推进的闭环）。
- 到达完成时，依据 scope manifest 把交付标注为 `COMPLETE` 或 `PARTIAL`，子集交付不会被静默当成 `VERIFIED`。

### `dispatch` — 产出当前阶段的 worker packet

```bash
python $S dispatch --state <s> \
  [--runtime codex|codex-app|claude-code|opencode|manual]   # 默认 codex
  [--team-profile <名>] [--max-workers N]
```

把当前阶段规划成 agent-team，写出 `agent-team-plan.json` 与
`dispatch-invocations/<phase>-<时间戳>.json`，并返回**自包含的 worker 描述符**（含
`context_paths` 与 `expected_outputs`）。
- 能自动 spawn 的运行时（codex/claude-code/opencode）→ 标记阶段 `DISPATCHED`，退出码 0；
- 不能自动 spawn 的 `manual`（及未知运行时）→ 返回 `dispatch_blocked`（退出码 3，
  reason `manual_runtime_requires_human_dispatch`），由协调者手动 spawn worker，再 `submit` 证据。
  （没有 `WAITING_DISPATCH` 状态，也没有 `dispatch-ack` 握手——均已在重设计中移除。）

### `submit` — 记录 worker 证据

```bash
python $S submit --state <s> --phase <P> [--key <k>] [--path <evidence>] \
  [--status done|failed] [--reason <文本>]
```

把某阶段的证据键 → 证据文件路径写入 run-state；`--status failed --reason …` 标记失败。

### `gate` — 跑阶段声明式门禁

`--state <s>`、`[--phase P]`（默认当前阶段）。通过 → 退出码 0；未过 → 退出码 1 并返回
`missing_evidence`。门禁只看声明的 `exit_gate` 证据键，本身不推进状态。

### `status` — 人读导航地图

`--state <s>`。只读地返回 `navigation_map`（与 `next` 同源），不推进生命周期。

### `validate-pipeline` — 校验流水线 yaml

`--pipeline <内建名|路径>`。对内建或自定义流水线做不变式校验（阶段闭包、门禁闭包等）。

### `doctor` — 环境/状态体检

```bash
python $S doctor [project_root] [--json] [--state <run-state>]
```

检查 Python、技能布局、项目标记、Hook 就绪等；带 `--state` 时附带只读的 run-state 一致性诊断。

---

## 执行循环

```text
start  ── 创建唯一 run-state（CREATED）
  │
  └─▶ 循环 {
        next      ── 若 complete → 收尾；否则给出当前阶段
        dispatch  ── 产出当前阶段 worker packet（指针）
        spawn     ── 子 agent 在隔离上下文中 invoke 自己的技能并干活
        submit    ── 记录该阶段证据
        gate      ── 跑阶段门禁
      } 直到 VERIFIED
```

worker packet 是**指针**（role + skill + context_paths + expected_outputs），不是任务详述。
子 agent 只读自己的 `context_paths`、只写本阶段声明的产物。

---

## tier 与流水线

`start --tier <t>` 选择流水线（`pipelines/*.yaml`）。裁剪是**结构性**的：被跳过的阶段从计算出的
spine 中移除，`next` 直接越过，导航地图渲染 `– skipped`。

| tier | 活跃阶段 | 说明 |
|---|---|---|
| `minimal` | `CREATED → CLARIFIED → RED → IMPLEMENTED → VERIFIED` | 跳过 `PLANNED` / `REVIEWED` |
| `rapid` *(pipeline opt-in)* | `CREATED → CLARIFIED → IMPLEMENTED → VERIFIED` | 三步快速实施: 澄清、实施、校验; 跳过 `PLANNED` / `RED` / `REVIEWED`,用 `--pipeline rapid` 显式选择 |
| `standard` | 全主干 | 单 reviewer |
| `critical` | 全主干 | `REVIEWED` 派 r1/r2/r3 三份独立审查（隔离上下文，不审自己的实现） |
| `audited` | 全主干 | r1/r2/r3 + `VERIFIED` 增 `verification` 与 `audit_replay` 证据 |

完整主干：`CREATED → CLARIFIED → PLANNED → RED → IMPLEMENTED → REVIEWED → VERIFIED`。
**只有 `IMPLEMENTED` 阶段 `allows_code_write: true`**——生产代码只能在此阶段写。

- `--tier auto`（默认）：分类器读需求文本判定 tier，并应用 **G4 基线下限**——派生（非显式钉住）的
  tier **不会**降到 `minimal`，审查是默认。只有显式 `--tier minimal` 才会降级。
- `--pipeline <名|路径>`：覆盖 `--tier` 推出的 spine，可指向内建名或自定义 yaml。
- 每个内建 tier 都通过门禁闭包校验（`gate_closure_ok`）。

`rapid` 不是 tier recommendation 的候选项,不会被 `--tier auto` 自动选择。它是显式 opt-in 的快速流水线:当需求足够小、用户接受跳过独立计划/红测/审查时,用 `start --pipeline rapid` 选择。

自定义流水线 yaml 形如：

```yaml
name: standard
phases:
  - CREATED
  - CLARIFIED
  - PLANNED
  - RED
  - phase: IMPLEMENTED
    allows_code_write: true
  - REVIEWED
  - VERIFIED
```

`critical` / `audited` 还会在阶段上声明 `produces:` 与 `exit_gate:`（如 `[r1_review, r2_review, r3_review]`）。

---

## 领域适配器（DomainAdapter）

适配器位于 CLI 层（`start` 内），core 不感知。
- **backend**（默认，Java/Spring/Maven）：不贡献任何 override、不带 domain 块——backend run 与
  引入适配器前**逐字节一致**（parity 契约）。
- **frontend**：检测 JS/TS UI 仓库（`package.json` + react/vue/svelte/angular，或 vite/vitest 配置），
  把范围发现路由到前端扫描器，并带一个自描述 `domain` 块（`test_runner: vitest`、
  `review_profile: frontend-default`），在 `dispatch` 时透传给 worker。当前**不改**流水线 spine。

选择顺序：`--adapter` 显式指定 → 否则按检测器顺序（frontend 优先，更具体）→ 否则回落 backend。
`--scan` 会跑适配器扫描以抬高 tier 下限。未知的显式适配器名 → 退出码 2。

---

## Agent-Team 派发与 worker 技能

`dispatch` 在生命周期阶段与运行时描述符之间多一层 agent-team 规划：

```text
pipeline phase → agent_team provider/profile → worker packet(s) → runtime adapter → descriptor(s)
```

- 生命周期阶段定义**所需证据**；内建 provider 决定该证据由**几个 worker** 产出；
  运行时适配器把一个 worker packet 翻成 Codex / Claude Code / OpenCode / manual 描述符；
  门禁仍只凭证据键决定阶段切换——agent-team 计划本身不能通过任何门禁。
- 单 worker 阶段保留顶层 `worker_descriptor`；多 worker 阶段额外输出 `agent_team_plan`、
  `worker_descriptors`，以及 `agent-team-plan.json` 与 `dispatch-invocations/<phase>-<时间戳>.json`。
- 内建 profile 在 `agent-teams/default-*.yaml`；项目自定义 profile 用 `--team-profile` 显式选择，
  建议放在 `.e2e/agent-teams/`。

各阶段对应的 worker 角色与技能（`default-standard` 为例）：

| 阶段 | 角色 | worker 技能 |
|---|---|---|
| `CLARIFIED` | requirements-clarifier | `e2e-harness-clarification` |
| `PLANNED` | implementation-planner | `e2e-harness-planning` |
| `RED` | tdd-red / test-case-developer | `e2e-harness-tdd-red` |
| `IMPLEMENTED` | code-developer | `e2e-harness-implementation` |
| `REVIEWED` | semantic-reviewer | `e2e-harness-review` |
| `VERIFIED` | coverage-reviewer | `e2e-harness-completion` |

> 运行时不钉死模型：worker 继承协调者可访问的默认模型。可用环境变量
> `E2E_HARNESS_SUBAGENT_TYPE_<ROLE>` 覆盖某角色的 subagent 类型。

---

## run 归档目录

```text
docs/agent-runs/<run_id>/
  run-state.json                         # SSOT，唯一控制文件
  agent-team-plan.json                   # 最近一次 dispatch 的 team 规划
  dispatch-invocations/<phase>-<stamp>.json
  evidence/<file>                        # worker submit 进来的证据（约定路径）
```

`run-state.json` 由 CLI 独占；`phase_guard` 会**硬拒绝**对它和 Hook 配置本身的直接写入
（中途改任一个都会破坏状态或关闭强制执行）。

---

## 门禁与证据语义

门禁校验**真实产物**，不是叙述：
- 文件**存在 + 非空 + 哈希**；
- 红/绿测试键（`failing_tests` / `passing_tests`）必须是**命令证据且退出码正确**——红测试退出码非零、
  绿测试退出码为零；
- 高风险（API/MQ/支付/数据/安全/跨服务）工作**不能**靠事后补一段轻量测试备注静默通过。

因此"编译通过、发了总结、跳过审查/验证"这类行为在门禁与 Stop Hook 面前不成立。

---

## 运行时 Hook（强制执行）

两个 stdlib-only 守卫，位于
`skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/`：

### `phase_guard.py`（PreToolUse，matcher `Edit|Write|MultiEdit|NotebookEdit|Bash`）

代码写入的**阶段锁**。只有当前阶段 `allows_code_write`（即 `pipeline.can_write_code`）时才放行生产代码写入，
否则 deny 并给出指向 `status`/`submit`/`gate`/`next` 的恢复提示。它还会：
- **硬拒绝**对 `run-state.json` 和 Hook 配置自身的直接写入；
- 拦截绕过 `Edit`/`Write` 的写法——`Bash` 重定向、`sed -i` / `cp` / `mv` / `tee` / `dd`、
  `patch` / `git apply`、内联 `python -c` 写入——在非代码写入阶段保守地拒绝不透明写。

`docs/agent-runs/` 下的 harness 产物不算代码路径，可在实现前写；只有 `run-state.json` 与 Hook 配置是硬拒绝。
参数：`--repo .`、`--hook-input -`（工具事件以 JSON 从 stdin 传入）；run-state 在 `docs/agent-runs/` 下自动发现，无需 `--state`。

### `stop_guard.py`（Stop）

读 `run-state.current_phase`，在它不是 `VERIFIED` 之前**阻止结束 run**，并返回应执行的下一步
（`next` → `dispatch` → `submit` → `gate`，循环）。这是阻止"提前收尾"的守卫。

### Hook 模板与物化

模板：`hooks/claude-code-settings.example.json`，命令里用 `__HARNESS_SCRIPTS__` 占位。
`e2e-harness init`（或下文多运行时安装器）会把占位重写为已安装技能的**绝对** `scripts/` 路径，
并转成正斜杠（Hook 命令经 shell 执行，Windows 上反斜杠会被吞）；合并幂等，已存在的 settings 先备份成 `.bak`。

最小 Claude 项目配置（`.claude/settings.json`）：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash",
        "hooks": [
          { "type": "command",
            "command": "python \"<scripts>/e2e_harness/adapters/hooks/phase_guard.py\" --repo . --hook-input -" }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command",
            "command": "python \"<scripts>/e2e_harness/adapters/hooks/stop_guard.py\" --repo . --hook-input -" }
        ]
      }
    ]
  }
}
```

> 不要把示例命令逐字复制到别的仓库——物化后的命令只有在该仓库能访问到已安装技能源树时才解析得对。
> 用 `init` 重写占位符才安全。

### 各运行时

- **Claude Code**：`e2e-harness init --runtime claude`。两守卫均为硬拦截。
- **OpenCode**：`e2e-harness init --runtime opencode` 写出 `.opencode/plugins/e2e-dev-harness.js`。
  `tool.execute.before → phase_guard`（**硬**阶段锁，与 Claude PreToolUse deny 等价）；
  `event session.idle → stop_guard`（**软**提醒——OpenCode 没有"否决 stop"原语，
  `session.idle` 只能观测）。即 OpenCode 上**阶段写锁是硬门禁，跑到 VERIFIED 只是建议性**。
- **Codex / Gemini CLI**：未随包发 Hook 模板。若 runner 支持阻塞式 pre-tool/pre-action 钩子，
  可手工接同一条 `phase_guard.py` 命令（把工具事件 JSON 从 stdin 喂入，`blocking: true`），
  并按各自工具名调整 matcher。若无法阻塞，则只能在本地 wrapper 或 CI 里 best-effort 跑该命令。

---

## 验证 Hook 行为

先用 `start` 建一个 run，再在代码写入阶段之前探一次写：

```bash
G=skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks
python "$G/phase_guard.py" --repo . \
  --hook-input '{"tool_name":"Edit","tool_input":{"file_path":"services/payment/src/main/java/PaymentService.java"}}'
```

代码写入阶段之前（被阶段锁拦截）应返回：

```json
{ "hookSpecificOutput": { "hookEventName": "PreToolUse",
  "permissionDecision": "deny", "permissionDecisionReason": "Blocked: ... phase-locked. ..." } }
```

run 未到 `VERIFIED` 时探 stop 守卫：

```bash
python "$G/stop_guard.py" --repo . --hook-input -
# → {"decision":"block","reason":"Do not stop yet: ... not VERIFIED. ..."}
```

把 run 推进到 `IMPLEMENTED`（记证据 → 过门禁 → `next`）后再探一次 `phase_guard`，应返回
`permissionDecision: "allow"`。

---

## 非 ASCII 需求与编码

含中文/非 ASCII 的需求，请写进 UTF-8 文件用 `--request-file` / `--feature-file` 传入，避免
Windows / git-bash 控制台编码把 argv 损坏：

```bash
printf '%s' "<原始需求>" > /tmp/req.txt
PYTHONUTF8=1 python $S start --repo . --feature login --request-file /tmp/req.txt
```

`start` 会显式拒绝被控制台损坏（含 U+FFFD）的文本而非静默降级。纯 ASCII 时可直接 `--request "<req>"`。

---

## 多运行时安装器与可编辑 Python 安装

### 多运行时安装器（`tools/install-e2e-dev-harness.mjs`）

`e2e-harness init` 之外的另一条路，覆盖 Codex/Gemini/OpenCode 的技能同步与 Hook 安装。默认 dry-run，
加 `--yes` 才真正执行：

```bash
node tools/install-e2e-dev-harness.mjs --sync --yes
node tools/install-e2e-dev-harness.mjs --project <business-repo> --yes
node tools/install-e2e-dev-harness.mjs --target opencode --project-root . --with-hooks --runtime opencode --yes
```

常用参数：

| 参数 | 含义 |
|---|---|
| `--target codex\|claude\|agents\|opencode\|all` | 技能目标运行时（默认 `codex`） |
| `--sync` | 预设：`--target all --skip-python-cli --skip-external` |
| `--project <path>` | 预设：同步全部技能 + 装 Hook + 跑 doctor |
| `--full` | 预设：`--target all --install-external --with-hooks --runtime claude --doctor` |
| `--project-root <path>` | 业务仓库根（Hook 与 doctor 的目标，别名 `--hook-repo`） |
| `--with-hooks --runtime <r>` | 安装运行时 Hook |
| `--hooks-only` | 只装 Hook，不拷技能、不跑 pip |
| `--doctor` / `--check-only` | 跑 doctor / 只检查不规划写入 |
| `--yes` | 执行（否则 dry-run） |

完整用法见 [`docs/e2e-dev-harness-installer.md`](docs/e2e-dev-harness-installer.md)。

### 可编辑 Python 安装（控制台脚本）

想要全局的 `e2e-dev-harness` / `e2eh` 控制台命令时：

```bash
python -m pip install -e .[dev,ast]   # dev=pytest；ast=tree_sitter（可选）
e2e-dev-harness --version
e2e-dev-harness doctor . --json
```

> 注意：`e2e-dev-harness` / `e2eh` 现在**只**是控制面（start/next/…/doctor），不再承担安装职责——
> 安装走 Node CLI `e2e-harness` 或上面的 `.mjs` 安装器。

---

## 环境变量

| 变量 | 作用 |
|---|---|
| `E2E_HARNESS_HOME` | 覆盖技能位置（默认 `~/.claude/skills/e2e-dev-harness`） |
| `E2E_HARNESS_PYTHON` | 覆盖 Python 解释器（优先于 `.harness-env.json` 记录值与自动探测） |
| `PYTHONUTF8=1` | 非 ASCII 需求时建议设置 |
| `E2E_HARNESS_SUBAGENT_TYPE_<ROLE>` | 覆盖某 worker 角色的 subagent 类型 |

`.harness-env.json`（位于技能 home）记录安装时所用的 Python。Node CLI 在转发时会自动设置
`PYTHONDONTWRITEBYTECODE=1`，避免在随包脚本目录里产生 `__pycache__`（可显式覆盖）。

---

## GitNexus 集成

本仓库被 GitNexus 索引（见 `CLAUDE.md` / `AGENTS.md`）。对 backend 的 `critical` / `audited` run，
GitNexus 的影响分析可作为门禁证据；索引刷新由 GitNexus CLI 负责：

```bash
npx gitnexus analyze   # 刷新知识图谱索引
```

GitNexus 命令角色是刻意分开的：`context` 接收**代码符号**（类/函数/方法/`Class.method`），
`impact` / `detect-changes` 负责受影响范围分析。改动代码符号前请按 `CLAUDE.md` 的约定先做 impact，
提交前跑 `detect-changes`。

> harness 自身已不再随包 `cross_service_dependency_scan.py` 等旧脚本——依赖/影响证据统一以 GitNexus 为源。

---

## 开发与测试

合并前总检查（Node 测试 + Python 测试 + GitNexus detect-changes）：

```bash
npm run pre-merge-check
```

也可分别运行：

```bash
npm test                                   # Node CLI 测试（test/，node --test）
python -m pytest skills/e2e-dev-harness/tests tests/test_node_installer.py -q \
  -p no:cacheprovider --basetemp=.test-tmp/pre-merge-pytest
python -m compileall -q skills/e2e-dev-harness/scripts
git diff --check
```

---

## 文档索引

| 文档 | 内容 |
|---|---|
| [`skills/e2e-dev-harness/SKILL.md`](skills/e2e-dev-harness/SKILL.md) | 协调者纪律、6 动词、循环、tier（权威操作指南） |
| [`docs/e2e-dev-harness-installer.md`](docs/e2e-dev-harness-installer.md) | 安装器完整用法 |
| [`skills/e2e-dev-harness/references/agent-orchestration.md`](skills/e2e-dev-harness/references/agent-orchestration.md) | agent 编排参考 |
| [`MIGRATION.md`](MIGRATION.md) / [`CHANGELOG.md`](CHANGELOG.md) | 从旧 harness 的迁移与变更记录 |
| `docs/` | 交付保真蓝图、目标架构、各项设计与审计文档 |

---

## 许可证

- npm 包 `e2e-harness`：`package.json` 标注 **MIT**。
- Python 包 `e2e-dev-harness`：`pyproject.toml` 标注 **Proprietary**。
