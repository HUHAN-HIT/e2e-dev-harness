---
name: e2e-harness-planning
description: Use for e2e-dev-harness implementation-planner worker tasks that turn clarified requirements into a service-sliced implementation plan and schedule from a fresh isolated context.
---

# E2E Harness Planning Worker

Do not inherit coordinator chat context. Use only the packet `context_paths` (run-state, requirements handoff, any R1 review, service-scope inputs).

## 契约 (e2e-dev-harness)

- Superpowers is an external skill system. If it is unavailable, continue directly with this worker's expected_outputs and harness contract instead of inventing behavior or stopping.
- **方法委派**: 用 `superpowers:writing-plans` 把澄清后的需求转成服务切片实现计划与调度。本 skill 只持 harness 专属胶水,不重造规划方法。
- **expected_outputs**: PLANNED 闸要求**两个**证据键,缺一不可:
  1. `plan` —— 散文实现计划,写 `docs/agent-runs/<run>/handoffs/02-implementation-planner.md`,然后:
     `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase PLANNED --key plan --path <plan-path>`
  2. `module_plan` —— 把散文计划里的**功能模块切片**落成**机器可读**的模块计划(link ④:渐进式并行开发的结构化依据)。写 `docs/agent-runs/<run>/module-plan.json`,然后:
     `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase PLANNED --key module_plan --path docs/agent-runs/<run>/module-plan.json`
- **module-plan.json 形态** (闸会逐项校验良构 + 依赖闭包 + 无环;散文无法通过):
  ```json
  {
    "schema": "e2e-dev-harness.module-plan.v1",
    "modules": [
      {"id": "auth", "name": "Auth service",
       "depends_on": [], "acceptance_ids": ["AC-001"],
       "scope": {"services": ["auth"], "tables": ["users"]}}
    ]
  }
  ```
  规则: `modules` 非空; `id` 唯一且匹配 `^[A-Za-z0-9][A-Za-z0-9_-]*$`; `name` 非空; `depends_on` 只能引用**已声明**的模块 id(不能自指、不能成环); `acceptance_ids` 每条匹配 `^AC-\d{3,}$`,把契约里的验收项分摊到模块。**≥2 个模块时**,引擎会按 `depends_on` 拓扑序为每个模块展开独立的 `RED→IMPLEMENTED→REVIEWED` 子生命周期(取向②),互不依赖的模块由 agent-team 并行扇出;单模块即退化为现有单轨。把复杂需求**真正切成模块**,不要塞成一个巨石模块。
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。
- 仅就需求 handoff 未解决的范围/排序决策向用户提问。
