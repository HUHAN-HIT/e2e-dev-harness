---
name: e2e-harness-clarification
description: Use for e2e-dev-harness requirements-clarifier worker tasks that must clarify intent, acceptance criteria, impact, and open questions from a fresh isolated context.
---

# E2E Harness Clarification Worker

Do not inherit coordinator chat context.

Use only the context pack, allowed inputs, project instructions selected for clarification, and GitNexus/dependency evidence requested by the schedule.

Write `docs/agent-runs/<run>/handoffs/01-requirements-clarifier.md`.

**澄清要跑到底,不是问一轮就停。** 把每一处歧义/未定产品决策/工具降级,都落成验收契约里的一条 `open_questions`,然后**循环**:向用户提问 → 用户答复后把该条 `status` 翻成 `resolved` 并写 `resolution` → 直至**没有任何 `status: open` 残留**。只有用户**显式**同意推迟的,才标 `deferred`(同样要写 `resolution` 记录推迟理由)。CLARIFIED 闸会逐条校验:只要还有 `open`,闸**不放行**,`next` 会把待确认问题列回给你继续问。不要用自行假设替代提问。

## 契约 (e2e-dev-harness)

- Superpowers is an external skill system. If it is unavailable, continue directly with this worker's expected_outputs and harness contract instead of inventing behavior or stopping.
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
    ],
    "open_questions": [
      {"id": "OQ-001",
       "question": "<一条歧义/未定决策,需用户拍板>",
       "status": "open|resolved|deferred",
       "resolution": "<resolved/deferred 必填:用户的答复或推迟理由;open 可省略>"}
    ]
  }
  ```
  规则: `items` 非空; `id` 唯一且匹配 `^AC-\d{3,}$`; 每项 `criterion` 与 `observable_behavior` 均非空。设计文档/需求里的**每一条**验收标准都要落成一条 `AC-NNN`——后续 RED 测试与实现闸将逐条引用这些 ID。
- **open_questions 账本** (澄清闭环,link ①): 每条 `id` 唯一且匹配 `^OQ-\d{3,}$`,`question` 非空,`status ∈ {open, resolved, deferred}`;`resolved`/`deferred` 必带非空 `resolution`。**只要有任意一条 `status: open`,CLARIFIED 闸就不放行**——这是"循环问到底"的机器化保证。无歧义时该字段可为空数组或省略;但有歧义却不落账=没澄清。
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。
