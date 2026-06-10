---
name: e2e-harness-completion
description: Use for e2e-dev-harness coverage-review and completion worker tasks that assemble the coverage matrix, completion evidence, and strict guard report from a fresh isolated context.
---

# E2E Harness Completion Worker

Do not inherit coordinator chat context.

Use only the context pack, the implementation manifests, the coverage matrix, the reviews, and any rework records listed in the schedule.

Write the completion evidence, archive, and strict guard report named in the task outputs.

Run the coverage gate and the strict completion guard before returning evidence.

Stop after the guard report is written; do not reopen implementation tasks.

## 契约 (e2e-dev-harness)

- **方法委派**: 用 `superpowers:verification-before-completion` 做完成前验证(全测通过、验收对齐)。
- **expected_outputs**: VERIFIED 闸要求**两个**证据键,缺一不可:
  1. `verification` —— 验证命令证据(exit 0, gate 会**重跑复算**):
     `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase VERIFIED --key verification --path <evidence-path>`
  2. `scope_manifest` —— 设计范围 vs 交付范围(link ②)。写 `docs/agent-runs/<run>/scope-manifest.json`,然后:
     `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase VERIFIED --key scope_manifest --path docs/agent-runs/<run>/scope-manifest.json`
- **scope-manifest.json 形态** (子集交付**必须**诚实记 `PARTIAL`;声明 `COMPLETE` 但 grounded 交付是子集会被**拒绝**——尤其声明交付的表必须在 repo 里真有 `CREATE TABLE`):
  ```json
  {
    "schema": "e2e-dev-harness.scope-manifest.v1",
    "status": "COMPLETE 或 PARTIAL",
    "expected":  {"services": ["payment","merchant"], "tables": ["t_risk_rule"], "phases": ["P1","P2"]},
    "delivered": {"services": ["payment"],            "tables": [],              "phases": ["P1"]}
  }
  ```
  `expected` 来自设计/需求范围;`delivered` 是本次真实交付。子集时 `status` 必须为 `PARTIAL`——harness 会据此把 run-state 标 `delivery=PARTIAL` + `undelivered`,而**不是**当作完整 VERIFIED。
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。
