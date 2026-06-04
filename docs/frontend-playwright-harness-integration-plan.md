# 前端 Playwright Harness 与 e2e-dev-harness 结合方案设计

## Summary

目标是把前端浏览器验证能力接入现有 `e2e-dev-harness`，形成 **Playwright-backed frontend adapter**。现有 harness 继续作为确定性控制面，负责生命周期、阶段门禁、worker 调度、证据协议、artifact registry、review 和 completion proof；Playwright 只负责真实浏览器执行、截图/trace/console/network 证据采集和用户路径验证。

推荐采用 **adapter-first** 路线，不新建独立前端状态机，不削弱当前 TDD/R1/R2/R3/dispatch 规则。v1 先支持“发现前端项目 -> 生成前端测试计划 -> 运行 Playwright 证据 -> 纳入现有 gate/completion”，后续再扩展视觉 diff、a11y、场景 DSL 和多浏览器矩阵。

## Key Changes

- 新增 `frontend-playwright adapter`，作为 `skills/e2e-dev-harness/scripts/` 下的一组脚本/CLI 子命令，复用现有 `command_evidence.py`、`artifact_registry.py`、`context_pack.py`、`dispatch-beat`、`completion gate`。
- 新增前端运行清单：记录前端 app root、package manager、dev server command、base URL、Playwright command、report/trace 输出位置。
- 新增标准证据文件：`docs/agent-runs/<run>/evidence/frontend-playwright.json`，只保存摘要、命令结果、失败分类、关键 artifact 路径；大文件 trace/video/screenshot 只以路径登记，避免污染 coordinator 上下文。
- 新增前端测试计划：`docs/agent-runs/<run>/evidence/frontend-test-plan.json`，等价于当前后端 `test-impact-plan.json`，列出必须执行的 Playwright/build/typecheck/lint 命令。
- 扩展 review profile：加入前端专用 R2/R3 检查项，包括选择器稳定性、用户路径覆盖、console error、network failure、responsive viewport、表单/导航状态、loading/error/empty states。
- 不新增生命周期状态。前端需求仍走 `CREATED -> PLANNED -> RED_READY -> IMPLEMENTED -> VERIFIED`，只是 TDD red/green 和 completion evidence 可以来自 Playwright。

## Implementation Design

### Frontend Discovery

- 探测 `package.json`、`playwright.config.*`、`vite/next/react/vue/angular` 常见配置。
- 输出 `frontend-apps.json`，每个 app 只包含可执行事实：root、scripts、framework hint、test command、dev command。
- 如果没有 Playwright，则 adapter 只报告缺失能力，不自动安装依赖；安装行为必须由用户或后续实现计划显式批准。

### Evidence Runner

- 包装现有命令证据模型运行 `npx playwright test` 或项目已有脚本，例如 `npm run e2e`。
- 捕获 exit code、stdout/stderr 摘要、Playwright report 路径、trace/video/screenshot 路径、console/network 摘要。
- 失败分类固定为：`app_boot_failed`、`test_failed`、`selector_failed`、`console_error`、`network_error`、`visual_mismatch`、`timeout`、`environment_missing`。

### Harness Workflow Integration

- Clarification 阶段要求前端需求声明用户路径、目标 viewport、可观察成功条件、非目标浏览器范围。
- TDD red 阶段允许 test worker 创建或更新 Playwright spec，并用失败证据证明当前行为未满足 AC。
- Implementation gate 接受前端 red evidence，但仍要求 R2 test review 通过后才能打开生产代码修改。
- Completion gate 要求 green Playwright evidence、frontend test plan 全部必跑命令通过、R3 review 覆盖每个前端 AC。

### Coordinator and Dispatch

- coordinator 只读取 `frontend-playwright.json` 摘要和 artifact 路径。
- Playwright trace、视频、截图、HTML report 保留在 evidence 目录，由 worker/reviewer 按需读取。
- 前端 worker 类型建议分为：`frontend-test-developer`、`frontend-code-developer`、`frontend-ux-reviewer`、`frontend-a11y-reviewer`，但 v1 只要求 test/code/review 角色隔离，不强制所有细分角色同时存在。

## Public Interfaces

CLI 入口建议：

- `e2e-dev-harness frontend detect --run-state <path>`
- `e2e-dev-harness frontend plan --app <app-id> --run-state <path>`
- `e2e-dev-harness frontend run --plan <frontend-test-plan.json> --output <frontend-playwright.json>`
- `e2e-dev-harness frontend summarize --evidence <frontend-playwright.json>`

标准 artifact：

- `evidence/frontend-apps.json`
- `evidence/frontend-test-plan.json`
- `evidence/frontend-playwright.json`
- `evidence/playwright/<scenario-or-command>/trace.zip`
- `evidence/playwright/<scenario-or-command>/screenshots/`

v1 不引入自定义场景 DSL。优先复用项目内 Playwright tests；如果项目没有测试，test worker 按 AC 创建最小 Playwright spec。

## Test Plan

- 单元测试：前端项目探测能识别 npm/pnpm/yarn、Playwright config、常见 dev/test scripts。
- 单元测试：Playwright evidence parser 能把通过、失败、超时、缺失依赖、console error 分成稳定分类。
- 单元测试：artifact registry 只登记大文件路径，不把 trace/video 内容写入 compact stdout。
- 集成测试：一个 mock frontend app 产生 red Playwright evidence，implementation gate 接受其作为 TDD red 输入。
- 集成测试：green Playwright evidence 和 frontend test plan 全部命令通过后，completion gate 可把前端 AC 判定为覆盖。
- 回归测试：没有 Playwright 的后端-only repo 行为不变；现有 Java/Spring/Maven workflow 不受 adapter 影响。

## Assumptions

- 继续沿用当前 `e2e-dev-harness` 作为主控制面，不重写为 Playwright 原生 harness。
- v1 目标是可验证前端工程交付，不追求完整视觉测试平台。
- 默认不自动安装 Playwright 或浏览器二进制，避免 adapter 在 gate 中引入不可控副作用。
- 前端验证证据必须以文件路径和摘要进入 coordinator，上下文预算规则继续优先。
- 如果一个业务需求同时改后端 API 和前端 UI，应使用同一个 run-state，并让后端 test-impact plan 与 frontend-test-plan 同时进入 completion proof。
