---
name: e2e-harness-implementation
description: Use for e2e-dev-harness implement worker tasks that make red tests green with minimal code, produce a manifest and coverage rows, from a fresh isolated context.
---

# E2E Harness Implementation Worker

Do not inherit coordinator chat context.

Use only the context pack, the service design, the red-test evidence, and the claimed task listed in the schedule.

Write the code changes, green tests, implementation manifest, and coverage rows named in the task outputs.

Run the service test command and the implementation gate before returning evidence.

Stop after tests pass and the manifest is written; do not perform R1/R2/R3 self-review in this session.

## 契约 (e2e-dev-harness)

- Superpowers is an external skill system. If it is unavailable, continue directly with this worker's expected_outputs and harness contract instead of inventing behavior or stopping.
- **方法委派**: 用 `superpowers:test-driven-development`(绿阶段)写最小实现让红测转绿;遇阻用 `superpowers:systematic-debugging`。
- **expected_outputs**: IMPLEMENTED 闸要求**两个**证据键,缺一不可:
  1. `passing_tests` —— 测试转绿后(命令证据,exit 0):
     `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase IMPLEMENTED --key passing_tests --path <evidence-path>`
  2. `test_substance` —— 证明测试实质而非空壳(link ③)。写 `docs/agent-runs/<run>/test-substance.json`,然后:
     `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase IMPLEMENTED --key test_substance --path docs/agent-runs/<run>/test-substance.json`
- **test-substance.json 形态** (闸会**重新静态分析**列出的测试文件,空壳=零断言/纯 `assert True`/`assertDoesNotThrow(()->{})` 将被阻断;并对契约做 AC 全覆盖交叉校验):
  ```json
  {
    "schema": "e2e-dev-harness.test-substance.v1",
    "acceptance_contract_path": "docs/agent-runs/<run>/acceptance-contract.json",
    "language": "python",
    "test_files": ["<被测的真实测试文件,相对 repo>"],
    "red_tests": ["<RED 阶段那一批失败测试节点>"],
    "green_tests": ["<转绿后同一批测试节点>"],
    "ac_coverage": {"AC-001": ["<证明该验收项的测试节点>"]}
  }
  ```
  约束: `red_tests` 与 `green_tests` 必须是**同一批**(红→绿,非各跑各的); `ac_coverage` 必须覆盖契约里**每一条** `AC-NNN`; `test_files` 里的每个测试都必须有真实断言。
- **多轨/按模块作业** (取向②, link ④): 复杂需求被 PLANNED 切成多个模块时,引擎会把你这一阶段展开成 `IMPLEMENTED#<module>` ——你被派给**某一个模块**。此时:
  - 只实现**当前模块**的范围(看 packet 的 phase 名 `IMPLEMENTED#<module>` 与 `module_plan` 里该模块的 `scope`/`acceptance_ids`),不要越界改其它模块。
  - 证据键**带模块后缀**:提交 `passing_tests#<module>` 与 `test_substance#<module>`(即 `--key passing_tests#<module>` / `--key test_substance#<module>`);闸按基键规则校验,但只判定**该模块**的门。
  - `test_substance#<module>` 的 `ac_coverage` 只需覆盖该模块分到的 `acceptance_ids`。
  - 单模块运行无后缀,沿用上面的 `passing_tests` / `test_substance`。
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。
