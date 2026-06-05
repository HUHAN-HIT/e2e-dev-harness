# e2e-harness CLI 设计文档

- 日期: 2026-06-05
- 状态: 已批准设计,待实现计划
- 方案: A(全局命令包装器)+ npx / Node bin 分发

## 1. 背景与问题

### 1.1 现象
目标工程 `petalpay/.claude/settings.json` 的 hook 指向了 skill 的**开发源码仓库**:

```
C:\Users\14907\Documents\Codex\2026-05-23\skill-skill-superpowers-skill-tdd-graphify\skills\e2e-dev-harness\scripts\phase_guard.py
```

而 skill 的规范安装位置是 `C:\Users\14907\.claude\skills\e2e-dev-harness\scripts\phase_guard.py`。

### 1.2 根因
harness 存在**两套互相矛盾的定位模型**:

- `SKILL.md` 全文把命令写成工程相对路径 `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py ...`,假设 skill vendored 在目标工程的 `skills/` 下。
- 实际安装在全局 `~/.claude/skills/e2e-dev-harness`。

`install_hooks.py` 用 `SCRIPT_DIR = Path(__file__).resolve().parent` 推导脚本路径,并把它烤进 hook。因此**写入哪条路径,取决于运行的是哪一份 `install_hooks.py`**。安装 petalpay 时跑的是开发仓副本,于是 petalpay 的门禁被绑死在一个临时实验目录上。

### 1.3 影响
- 脆弱耦合:开发仓一旦改名/移动/清理,petalpay 的 `phase_guard.py` / `harness_stop_guard.py` hook 立即失效,门禁与 Task 派发拦截全部失灵(回到 manual-dispatch 无法自动 spawn 子 agent 的老问题)。
- 版本漂移:目标工程实际运行的是开发版,而非已发布版。

### 1.4 设计目标
让调用入口与 cwd / 副本位置彻底解耦,从机制上消除"路径取决于跑哪份脚本"。**不通过加校验约束实现,而是通过规范化安装与调用入口实现。**

## 2. 选型

| 方案 | 形态 | 根除 footgun | 改动量 | 决定 |
|---|---|---|---|---|
| A. 全局命令包装器 | 稳定入口 `e2e-harness <子命令>`,内部恒定解析 `~/.claude/skills`;`init` 写绝对路径 hook | 是,彻底 | 中 | **采用** |
| B. 统一长命令模板 | 无 wrapper,SKILL.md 命令改绝对路径 + install 子命令 | 是 | 小 | 否 |
| C. 工程内 vendoring | 把 skill 拷进每个工程 skills/,命令用相对路径 | 是(靠副本同地) | 中 | 否 |

入口形态:**npx e2e-harness / Node bin**(可跨机分发)。

## 3. 设计

### 3.1 分发与安装模型
- 整个 harness 打成一个 npm 包(名 `e2e-harness`),**Python 脚本随包打进 tarball**,包是唯一分发单元。
- 发布形态:**本地包优先**(`npm link` / 本地目录,走 npx cache,与环境里 zai 插件一致);后续可改公开 `npm publish`,不影响接口。
- 安装命令:`npx e2e-harness install`
  - 把包内 `skills/e2e-dev-harness/` 拷到 `~/.claude/skills/e2e-dev-harness`;若已存在,先备份为 `e2e-dev-harness.bak`(同名 .bak 已存在则覆盖该 .bak),再覆盖更新。
  - 探测 Python 解释器,并把绝对路径记录到 `~/.claude/skills/e2e-dev-harness/.harness-env.json`,供 hook 与后续命令复用同一 python。

### 3.2 Node bin = 薄启动器(footgun 根除点)
bin 不使用 `__file__` 推导,改用两个常量:

- `SKILL_HOME = ~/.claude/skills/e2e-dev-harness`(可用环境变量 `E2E_HARNESS_HOME` 覆盖)
- `PYTHON = .harness-env.json 记录值`(可用环境变量 `E2E_HARNESS_PYTHON` 覆盖)

所有子命令都调用 `SKILL_HOME` 下那份脚本。因此 `init` 触发的 `install_hooks.py` 的 `__file__` 恒为 canonical 位置 → 写进目标工程的 hook 路径**永远是 `~/.claude/skills/...` 绝对路径**,与 cwd、与开发副本位置无关。

### 3.3 命令集

| 命令 | 内部映射 | 用途 |
|---|---|---|
| `e2e-harness install` | 拷贝 + 探测 python + 写 .harness-env.json | 安装/升级到本机 |
| `e2e-harness init <proj> [--runtime claude]` | `SKILL_HOME/scripts/install_hooks.py <proj> --runtime ...` | 给工程写正确 hook(替代手跑) |
| `e2e-harness status <proj>` | `harness_doctor.py <proj>` | 查 hook 就绪 / 索引 / run-state |
| `e2e-harness next <proj>` | `e2e_dev_harness.py next <proj>` | 当前应执行步骤 |
| `e2e-harness dispatch <proj>` | `e2e_dev_harness.py dispatch-beat / dispatch-status <proj>` | 派发心跳 / 子 agent 状态 |
| `e2e-harness <其它> <proj>` | 透传 `e2e_dev_harness.py <其它> <proj>` | 兜底,不漏现有子命令 |

`<proj>` 省略时默认当前工作目录。

### 3.4 单元边界
- **bin 启动器(JS)**:仅负责路径/python 解析与参数转发;不含业务逻辑。输入=argv,输出=子进程退出码与透传 stdout/stderr。
- **install 逻辑(JS 或随包 node 脚本)**:拷贝目录、备份、探测 python、写 env 文件。可独立测试(给定源/目标临时目录)。
- **Python harness 脚本**:保持现状,不改动其内部逻辑与校验。
- 三者通过"文件系统位置 + 子进程命令行"接口通信,可分别测试。

### 3.5 文档同步(防复发)
`SKILL.md` 里所有 `python skills/e2e-dev-harness/scripts/...` 相对写法改为 `e2e-harness <子命令>`。不改文档,footgun 会从文档抄写复发。

### 3.6 存量修复
对已坏的 petalpay:`e2e-harness init C:\...\petalpay --runtime claude` 重写 hook(`install_hooks.py` 的 `merge_claude` 会清掉旧 phase_guard/stop_guard 条目再写新)。

## 4. 错误处理
- `install`:目标已存在 → 备份再覆盖;备份失败 → 中止并报错,不破坏现有安装。
- python 探测失败(无 `python`/`python3`/py 启动器)→ 报错并提示设置 `E2E_HARNESS_PYTHON`。
- `init`/`status`/`next`/`dispatch`:`SKILL_HOME` 不存在 → 提示先跑 `e2e-harness install`。
- 透传命令:原样返回 Python CLI 的退出码与输出,不吞错。

## 5. 测试策略
- bin 路径解析:cwd 在任意目录、设/不设 `E2E_HARNESS_HOME`,断言解析到 canonical SKILL_HOME。
- install:临时目录模拟 `~/.claude/skills`,验证拷贝、备份 `.bak`、`.harness-env.json` 内容。
- init 端到端:对临时工程跑 `init`,断言生成的 `.claude/settings.json` hook 路径为 canonical 绝对路径(回归 petalpay 缺陷)。
- 透传:`e2e-harness next <tmp>` 退出码与直接调 Python 一致。

## 6. 不做(YAGNI)
- 不修改 `install_hooks.py` 的校验逻辑(不加 SCRIPT_DIR 守卫);正确性由"bin 恒调 canonical 副本"保证。
- 不做 Python console_script / pip 安装。
- 不做自动卸载。
- 暂不公开 npm publish(本地包优先)。

## 7. 待实现决策(已定默认)
1. 发布形态:本地包优先。
2. 覆盖策略:覆盖前备份 `.bak`。
3. 包名:`e2e-harness`(无 scope)。
