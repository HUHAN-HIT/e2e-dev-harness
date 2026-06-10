---
name: e2e-harness-clarification
description: Use for e2e-dev-harness requirements-clarifier worker tasks that must clarify intent, acceptance criteria, impact, and open questions from a fresh isolated context.
---

# E2E Harness Clarification Worker

Do not inherit coordinator chat context.

Use only the context pack, allowed inputs, project instructions selected for clarification, and GitNexus/dependency evidence requested by the schedule.

Write `docs/agent-runs/<run>/handoffs/01-requirements-clarifier.md`.

Ask the user only for intent confirmation, unresolved product decisions, or explicit tool-degradation approval.

## 契约 (e2e-dev-harness)

- **方法委派**: 用 `superpowers:brainstorming` 完成澄清(意图、验收标准、影响、开放问题)。本 skill 只持 harness 专属胶水,不重造方法。
- **expected_outputs**: CLARIFIED 闸要求**两个**证据键,缺一不可:
  1. `clarification` —— 写散文交接 `docs/agent-runs/<run>/handoffs/01-requirements-clarifier.md`,然后:
     `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase CLARIFIED --key clarification --path <handoff-path>`
  2. `acceptance_contract` —— 把验收标准转成**结构化、可机器校验**的验收契约(link ①:需求保真)。写 `docs/agent-runs/<run>/acceptance-contract.json`,然后:
     `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase CLARIFIED --key acceptance_contract --path docs/agent-runs/<run>/acceptance-contract.json`
- **acceptance-contract.json 形态** (闸会逐项校验良构,散文勾选框**无法**通过):
  ```json
  {
    "schema": "e2e-dev-harness.acceptance-contract.v1",
    "items": [
      {"id": "AC-001",
       "criterion": "<一条人读验收标准>",
       "observable_behavior": "<一个会失败的测试将观察到的具体行为/输入→输出>"}
    ]
  }
  ```
  规则: `items` 非空; `id` 唯一且匹配 `^AC-\d{3,}$`; 每项 `criterion` 与 `observable_behavior` 均非空。设计文档/需求里的**每一条**验收标准都要落成一条 `AC-NNN`——后续 RED 测试与实现闸将逐条引用这些 ID。
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。
