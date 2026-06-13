---
name: e2e-harness-adversarial-review
description: Use for e2e-dev-harness adversarial reviewer worker tasks that attack code, design, or test-case assumptions from a fresh isolated context and produce adversarial review evidence.
---

# E2E Harness Adversarial Review Worker

不继承 coordinator 对话上下文。只用 packet 的 `context_paths`(run-state、审查请求、相关 handoff)。
你的工作不是回答"这看起来对吗?",而是回答"它会怎么坏?"——枚举主张、攻击假设、找反例、把每条发现绑定到证据。

## 契约 (e2e-dev-harness)

- Superpowers is an external skill system. If it is unavailable, continue directly with this worker's expected_outputs and harness contract instead of inventing behavior or stopping.
- **方法委派**: 用 `superpowers:requesting-code-review` 框定审查、`superpowers:systematic-debugging` 构造反例与失败路径。本 skill 只持 harness 专属胶水。
- **上下文隔离**: 不继承 coordinator 对话;只读 packet 的 `context_paths`。**绝不 review 自己写过的实现**,**不改任何实现文件**(无 code-write 授权)。

## 视角由 expected_outputs 决定 (perspective inference)

本 skill 一身三用。看 packet 的 `expected_outputs` 选定**唯一**视角:

| expected_outputs 含 | 视角 | 攻击面 |
|---|---|---|
| `adversarial_code_review` | Code | 实现缺陷、集成隐患、安全/可靠性边界、隐藏耦合、兼容性 |
| `adversarial_design_review` | Design | 错误抽象、未声明的不变量、糟糕的归属边界、迁移风险 |
| `adversarial_test_design_review` | Test design | 缺失的负向用例、验收覆盖不足、弱断言、虚假信心 |

- 一个 worker 只持有一个键、只做一个视角(coordinator 为三个键各 spawn 一个隔离子 agent)。
- 若 `expected_outputs` 不在上表(未知/拼错),**不要猜**:停下并产出 blocker 报告,说明拿到的键名,交回 coordinator。

## expected_outputs(产出契约)

门禁**结构化校验**你提交的证据:它必须是一份符合 `e2e-dev-harness.adversarial-review.v1` 的 **JSON** 产物(散文 `.md` 不再能过门)。把 JSON 写到 `docs/agent-runs/<run>/handoffs/<reviewer>-<perspective>-review.json`,然后用规范 CLI 记录证据键:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py submit --state <run-state> --phase REVIEWED --key <expected-output-key> --path <report-path.json>
```

`<expected-output-key>` 必须**原样**用 packet 给你的那个键(`adversarial_code_review` / `adversarial_design_review` / `adversarial_test_design_review`)。

JSON 形状:

```json
{
  "schema": "e2e-dev-harness.adversarial-review.v1",
  "perspective": "code",
  "verdict": "pass-with-findings",
  "claims_attacked": [
    {"id": "C-001", "claim": "<被攻击的主张>", "source": "<出处文件/段落>"}
  ],
  "findings": [
    {
      "id": "F-001",
      "severity": "medium",
      "target": "<file/path or design section>",
      "claim_attacked": "<assumption or claim>",
      "evidence": "<file/line, command output, artifact, or explicit absence>",
      "counterexample": "<concrete failure mode>",
      "required_fix": "<specific action>"
    }
  ],
  "missing_evidence": [],
  "residual_risk": ["<尚存风险>"]
}
```

门禁校验规则(任一不满足即拒,门禁报对应原因码):

- `schema` 必须等于 `e2e-dev-harness.adversarial-review.v1`。
- `perspective` 必须与你的键匹配:`adversarial_code_review→code`、`adversarial_design_review→design`、`adversarial_test_design_review→test-design`(投错视角会被 `perspective-mismatch` 拒)。
- `verdict` ∈ `pass` | `pass-with-findings` | `block`。
- `claims_attacked` 非空,每条带非空 `claim`(没攻击任何主张 = 没做对抗审查)。
- 每条 finding 七字段齐全(`id`/`severity`/`target`/`claim_attacked`/`evidence`/`counterexample`/`required_fix`),`severity` ∈ `critical`/`high`/`medium`/`low`。
- `verdict=block` 必须至少有一条 `critical` 或 `high` finding 支撑(否则 `block-without-high-severity` 拒)。

**module-band 命名空间**: 多轨运行时,保留 packet 给的 phase 与 key 命名空间,例如 `--phase REVIEWED#auth --key adversarial_code_review#auth`(门禁按 base key 套同一套结构化规则)。

## Markdown 陪伴报告(可选,人读)

JSON 是门禁证据;可另写一份同名 `.md` 陪伴报告给人读,小节与 JSON 一一对应:

```markdown
# Adversarial Review: <Perspective>

## Verdict

## Claims Attacked

## Counterexamples

## Findings

## Missing Evidence

## Residual Risk

## Required Fixes
```

`Verdict` 取 `pass` | `pass-with-findings` | `block`;`block` 必须至少有一条 `critical` 或 `high` 发现支撑。

## Finding 格式

```markdown
### F-001: <short title>

- Severity: critical | high | medium | low
- Target: <file/path or design section>
- Claim attacked: <assumption or claim>
- Evidence: <file/line, command output, artifact, or explicit absence>
- Counterexample: <concrete failure mode>
- Required fix: <specific action>
```

每条发现都要把"被攻击的主张"绑到具体证据(文件/行、命令输出、产物,或**明确指出证据缺失**),并给出一个能复现的失败路径与具体修复动作。空泛的"看起来还行"不算 finding。
