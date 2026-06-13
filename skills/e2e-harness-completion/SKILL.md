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

- Superpowers is an external skill system. If it is unavailable, continue directly with this worker's expected_outputs and harness contract instead of inventing behavior or stopping.
- **方法委派**: 用 `superpowers:verification-before-completion` 做完成前验证(全测通过、验收对齐)。
- **expected_outputs 随 tier 变化** —— 永远产出 `next_action.expected_outputs` 列的那几个键(不多不少)。VERIFIED 闸的键集:
  - **默认 (minimal/standard/critical)**: `verification` + `scope_manifest`。
  - **audited**: `verification` + `audit_replay` + `agent_team_dispatch`(audited.yaml 把 VERIFIED 覆盖成这三个,**不含** `scope_manifest`)。
- **录命令证据(verification 和 audit_replay 的 claim 都要用它)**: 没有 CLI verb,用 `record_command` 录真证据(手写占位 hash 会被判 `forged-evidence`):
  ```bash
  python -c "import sys,json; sys.path.insert(0,'skills/e2e-dev-harness/scripts'); from e2e_harness.adapters.evidence.command_evidence import record_command; open('docs/agent-runs/<run>/VERIFIED-full-suite.json','w').write(json.dumps(record_command('.', 'python -m pytest skills/e2e-dev-harness/tests -q')))"
  ```
- 各键产出 + submit:
  1. `verification` —— 验证命令证据(exit 0, gate 会**重跑复算**)。录证据(上法)后:
     `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase VERIFIED --key verification --path docs/agent-runs/<run>/VERIFIED-verification.json`
  2. `scope_manifest` (**默认 tier**) —— 设计范围 vs 交付范围(link ②)。写 `docs/agent-runs/<run>/scope-manifest.json`,然后 submit `--key scope_manifest`。
     形态(子集交付**必须**诚实记 `PARTIAL`;声明 `COMPLETE` 但 grounded 交付是子集会被**拒绝**——声明交付的表必须在 repo 里真有 `CREATE TABLE`):
     ```json
     {"schema": "e2e-dev-harness.scope-manifest.v1", "status": "COMPLETE 或 PARTIAL",
      "expected":  {"services": ["payment","merchant"], "tables": ["t_risk_rule"], "phases": ["P1","P2"]},
      "delivered": {"services": ["payment"],            "tables": [],              "phases": ["P1"]}}
     ```
     `delivered` 子集时 `status` 必须 `PARTIAL` → harness 标 `delivery=PARTIAL`+`undelivered`,而非完整 VERIFIED。
  3. `audit_replay` (**仅 audited**) —— **不是散文**! 是 manifest,每条 claim 指向一条**真命令证据**(用上面的 record_command 各录一条:全量套件、installer sync 等):
     ```json
     {"schema": "e2e-dev-harness.audit-replay.v1",
      "claims": [
        {"name": "full local suite", "evidence": "docs/agent-runs/<run>/VERIFIED-full-suite.json", "expect_exit": 0},
        {"name": "installer sync",    "evidence": "docs/agent-runs/<run>/VERIFIED-installer.json",   "expect_exit": 0}
      ]}
     ```
     写好后 submit `--key audit_replay --path docs/agent-runs/<run>/VERIFIED-audit_replay.json`。`evidence` 相对 repo root 解析。**强度**: anti-forgery(结构必须真)但**非 anti-tamper**(不重跑 exit_code,手改 exit_code 会过)——别当 verification 级。
  4. `agent_team_dispatch` (**仅 audited**) —— 就是 `dispatch` 命令写下的 dispatch-invocation.json:
     `python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase VERIFIED --key agent_team_dispatch --path docs/agent-runs/<run>/dispatch-invocations/<phase>-<ts>.json`
     校验: schema=dispatch-invocation.v1、有 descriptors 或非空 blocked(manual runtime 的 block 也接受)、其 `team_plan_path` 指向的 agent-team-plan.json 真实存在。
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。
