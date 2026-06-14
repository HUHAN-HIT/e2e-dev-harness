---
name: e2e-dev-harness
description: Default canonical delivery harness. Use when a feature/bugfix/refactor needs a multi-agent dev workflow that reliably runs to completion — clarification, TDD, review, verification — with a single source of truth, declarative tier-scaled gates, and worker subagents that self-load Superpowers skills.
---

# E2E Dev Harness

把需求变成"澄清→TDD→实现→(审查)→验证"的多 agent 流程,**保证跑到 VERIFIED**。

## Coordinator 纪律 (控制面 only)

- 你只读 run-state、发 worker packet、记证据、推进主干。**不**做本地代码探索/设计/TDD/审查/实现。
- worker packet 是**指针**(role + skill + context_paths + expected_outputs),worker 子 agent **首动作是 invoke 自己的 skill**,方法委派给 Superpowers。
- 每步看 `navigation_map`:全旅程 `CREATED→…→VERIFIED`,始终对照终点目标,避免局部最优。

## 6 动词

```bash
# Use the installed CLI entrypoint so resume/compaction works from any business repo.
# Do not use repo-relative `skills/e2e-dev-harness/...` unless you are inside this
# harness source checkout; business repos normally do not contain that path.
# 含中文/非 ASCII 的需求：写进 UTF-8 文件用 --request-file/--feature-file，避免
# Windows/git-bash 控制台编码把 argv 损坏（损坏会被 start 显式拒绝，不再静默降级）。
printf '%s' "<原始需求>" > /tmp/req.txt
# Human/coordinator startup is preview-first: compute recommendation without creating run-state.
PYTHONUTF8=1 e2e-harness start --preview-tier --repo . --feature "<feat>" --request-file /tmp/req.txt
# coordinator 展示 recommended_tier/options/reasons；用户确认后创建唯一 run-state：
PYTHONUTF8=1 e2e-harness start --repo . --feature "<feat>" --request-file /tmp/req.txt --tier <choice>
# Automation/CI with a pre-confirmed tier may call normal start directly; do not add stdin prompts.
# 纯 ASCII 时也可直接用 --request "<req>" 替代 --request-file /tmp/req.txt。
e2e-harness next   --state <run-state>     # 推进主干或返回单一 blocker + navigation_map
e2e-harness dispatch --state <run-state>   # 产出当前阶段的指针 worker packet
e2e-harness submit --state <run-state> --phase <P> --key <k> --path <p>  # 记录 worker 证据
e2e-harness gate   --state <run-state>     # 跑当前阶段声明式门禁
e2e-harness status --state <run-state>     # 人读导航地图
# GitNexus impact is ON by default (start --impact-mode auto); coordinator-only:
e2e-harness approve-impact-degradation --state <run-state> --approval <file.md>  # 记录降级信任锚
```

## 循环 (单游标 + 多轨 beat)

`start` → 循环 → 直到 `VERIFIED`。两种节奏由 `next` 返回的 `region` 决定:

**prologue / epilogue (单游标):** `next` → 若 `complete` 收尾;否则 `dispatch` 当前阶段 → spawn 1 个 worker 子 agent(自加载 `next_action.skill`)→ worker `submit` 证据 → 回到 `next`。

**module_band (多轨 beat):** `next` 返回 `tracks_frontier`(每条活跃轨一个 blocker)。**一个 beat** = 一次并发循环:

1. `next` → 看到 `tracks_frontier`(独立轨可处不同 base 阶段)。
2. `dispatch` → band 区一次拿到整批 descriptor,按轨记 `tracks[m].dispatch = dispatched`。
3. coordinator **一个回合**发 N 个 `Task`/`spawn_agent` 并 `await` 全部 ← 真并发在这里。
4. 各 worker `submit` 自己的 namespaced 证据(经 `run_state.mutate` 串行化)。
5. `next` 对账:所有过 gate 的轨推进;失败轨进轨内 rework(**不卡兄弟轨**);新解锁的依赖轨进下一拍 frontier。

循环 beat 直到所有轨 complete → join → `region=epilogue`、`current_phase=VERIFIED`。

> harness 仍是纯控制面:`tracks_frontier` 只是并行**意图**,真正并发 spawn 永远是 coordinator 的工具调用。`current_phase` 是派生的"领头游标",单游标读者(guards/gate/navigation)照常工作。

## tier 与流水线 (M2)

`start --tier <t>` selects the pipeline. The default `auto` classifies the request text; use `minimal` only when explicitly pinned:

| tier | 活跃阶段 | 说明 |
|---|---|---|
| `minimal` | CREATED→CLARIFIED→RED→IMPLEMENTED→VERIFIED | 跳过 PLANNED/REVIEWED |
| `rapid` *(pipeline opt-in)* | CREATED→CLARIFIED→IMPLEMENTED→VERIFIED | 三步快速实施:澄清、实施、校验;跳过 PLANNED/RED/REVIEWED,用 `start --pipeline rapid` 显式选择 |
| `standard` | 全主干 | 单 reviewer |
| `critical` | 全主干 | REVIEWED 派 r1/r2/r3 三份独立 review(隔离上下文,不 review 自己实现) |
| `audited` | 全主干 | r1/r2/r3 + VERIFIED 用 `verification`+`audit_replay`(命令证据背书的 manifest)+`agent_team_dispatch`(dispatch-invocation),**不含** scope_manifest |
| `adversarial` *(opt-in)* | 全主干 | REVIEWED 派 code/design/test-design 三个**对抗视角**独立 reviewer(攻击实现/设计/测试用例假设,各持一个证据键);不在 `--tier auto` 集合内 |

`rapid` 不属于 `--tier auto` 候选集合,也不是风险降级;它是用户显式选择的快速流水线。实施 worker 必须在 IMPLEMENTED 内提交 `passing_tests` 与 `test_substance`,并在 rapid 模式下自行提供同批次失败/转绿测试证据。

> `adversarial` 是 opt-in 流水线,不属于 `--tier` 自动分级集合。用 `start --pipeline adversarial` 显式选择;`dispatch` 自动配对 `default-adversarial` 团队档案,把 REVIEWED 扇出成三个隔离的对抗视角 reviewer(`adversarial_code_review` / `adversarial_design_review` / `adversarial_test_design_review`),门禁要求三个键齐备才过。

### Tier recommendation contract

`start --tier auto` emits and persists `tier_recommendation`. Its `options`
list contains `minimal`, `standard`, `critical`, and `audited` choices with
cost and reason summaries.

- `recommended_tier`: highest floor justified by request text, scanner scope,
  and GitNexus impact evidence.
- `selected_tier`: actual tier used for the run.
- Auto selection uses the recommendation.
- Explicit `--tier` selections are preserved even when below the
  recommendation. In that case downgrade metadata records
  `requested_below_recommended`, `requires_provenance=true`, and `blocked=false`
  under the current contract.

GitNexus impact evidence raises the recommendation for MEDIUM, HIGH, or
CRITICAL risk. Missing GitNexus verification on cross-service dependencies
must stay visible in `tier_recommendation.reasons`.

`tier_recommendation` 还带一个**建议性**的 `adversarial_review` 块(不改 tier):
当请求命中高风险触发——高 GitNexus impact、安全敏感、控制面、跨模块并发、
证据/门禁/派发、验证/测试语义——`suggested=true` 并在 `reasons` 列出触发项。它
**不**自动选流水线(`selected_tier` 仍是普通 tier);由用户确认后用 `select_with`
(`start --pipeline adversarial`)显式启用三视角对抗审查。

### Tier preview confirmation

Use `start --preview-tier` when Codex should show the user the recommended
workflow before creating a run. The command emits `tier-preview.v1`, includes
the same `tier_recommendation` options as normal `start`, and does not create
`run-state.json`.

Codex should present the recommendation, tier costs, and GitNexus/scanner
reasons to the user. After the user chooses, create the real run with
`start --tier <choice>` using the same repo, feature, request, adapter, scan,
and pipeline inputs.

Do not implement this as a stdin prompt. The CLI remains JSON-only and
non-interactive; the user choice happens in the coordinator conversation.

裁剪是结构性的:被跳阶段从计算出的 spine 移除,`next` 越过、导航地图渲染 `– skipped`。每个内建 tier 都过 I2 门禁闭包(`gate_closure_ok`)。门禁校验**真实产物**(文件存在+非空+哈希;`failing_tests`/`passing_tests` 须为命令证据且退出码正确)。

## GitNexus Impact Assessment (on by default)

`start --impact-mode <off|auto|strict>` (**default `auto` = on**) drives a
structured impact gate between `CLARIFIED` and `PLANNED`. Pass `off` to opt a run
out entirely (then the subsystem is inert and the run behaves exactly as before).
When on, as the engine reaches `PLANNED` it runs one idempotent bridge
(`impact_bridge.ensure_assessment_for_planning`, keyed on the acceptance-contract
hash) that persists `impact-assessment.json` next to `run-state.json` and a
`state.impact_assessment` binding.

Trigger policy (pure; `core/impact_trigger.py`): impact is required when the
request names code surfaces, the contract carries `impact_seed_candidates`, the
tier is `critical`/`audited`, the contract is compatibility/migration/security/
cross-service/persistence-sensitive, or the user explicitly asks for impact.
Documentation-only runs are `not_applicable`.

Status ownership:

- `blocked` (seeds missing / GitNexus unavailable / ambiguous / timeout) is owned
  by the **CLARIFIED edge**: the run stays at `CLARIFIED` and its `IQ-*` questions
  are merged into the re-clarify loop (`next.open_questions`). Answer them by
  amending the acceptance contract — the changed hash re-runs the assessment.
- `verified` advances to `PLANNED`, which then requires `module_plan` modules to
  carry `impact_refs` covering the artifact seeds (`impact_gate.planned_missing`).
- `degraded` is trusted only when `state.approvals.impact_degradation.sha256`
  matches the artifact's approval hash. The coordinator writes that anchor with
  `approve-impact-degradation` (a worker-authored markdown file is not the anchor).
- `not_applicable` passes with no planner obligation.

**Problem → ask the user to degrade.** Because impact is on by default, an
unverifiable assessment (GitNexus unavailable/timeout, unresolvable or ambiguous
seeds) does not silently stall: `next` returns blocked at `CLARIFIED` with
`open_questions` AND an `impact` block (`degradation_available: true`,
`approve_with: approve-impact-degradation`). The coordinator presents the choice —
**resolve** (answer the questions / index GitNexus, then amend the contract) or
**degrade** (record an approval). On the next `next`, a recorded approval converts
the blocked assessment to an auditable `degraded` one and the run proceeds (no
`impact_refs` required for degraded).

The runtime adapter only transports the artifact path into worker `context_paths`
(by phase + status); it never interprets GitNexus output. `recommend_tier` stays
pure — the control plane derives `scope.gitnexus` from the artifact via
`adapters/tier/impact_scope.py` (max seed risk → `impact_summary.risk`; verified
iff `status == verified`).

> Impact is on by default (`auto`). A run that legitimately needs no impact
> analysis (docs-only, or a focused test of an orthogonal gate) can pass
> `--impact-mode off`. Tests that drive runs to completion in an unindexed repo
> without exercising impact pin `off` for that reason.
>
> **CI / unattended automation without GitNexus.** Degradation is deliberately a
> *human* decision — there is no auto-degrade. A `required`-impact code run whose
> assessment cannot be `verified` (GitNexus unavailable in the CI image, no index)
> stays blocked at `CLARIFIED` until a coordinator records an
> `approve-impact-degradation`. With no human in the loop, such a run never reaches
> `VERIFIED` — it is held, not failed, by design. **CI that runs code features
> without GitNexus must pass `--impact-mode off` explicitly** to opt those runs out;
> otherwise keep impact on and have a coordinator resolve the `IQ-*` questions or
> approve degradation. (Index GitNexus in the CI image instead if you want CI to
> actually exercise the gate rather than skip it.)

## Language Profiles

`start` resolves Java, Python, javascript, and typescript language profiles at
run creation, writes immutable `language-profile.json` next to `run-state.json`,
and stores only a compact trusted binding in run-state. Use
`--language-profile <name-or-path>` to force a profile name or a project-local
`.e2e/language-profile.json` contract.

Workers must read the active `language-profile.json` from `context_paths`, use
its language for test commands and evidence shape, and must not edit
`run-state.language` or replace the profile artifact. `test_substance` manifests
for Python, Java, javascript, and typescript are re-analyzed by the harness.
JS/TS analyzer limitations travel through `analyzer_warnings`; the validator
checks warning identity by code and line, not prose wording.
## Agent-Team Dispatch Boundary

`dispatch` has an agent-team planning layer between lifecycle phases and
runtime descriptors:

```text
pipeline phase -> agent_team provider/profile -> worker packet(s) -> runtime adapter -> descriptor(s)
```

The lifecycle phase still defines required evidence. The builtin agent-team
provider decides how many workers should produce that evidence. Runtime adapters
translate one worker packet into a Codex, Claude Code, OpenCode, or manual
descriptor. Gates still decide phase transitions from evidence keys; an
agent-team plan never passes a gate by itself.

Default single-worker phases preserve the legacy top-level worker packet and
`worker_descriptor` output, but the worker packet also carries the profile's
`runtime_subagent_type` so the role intent is auditable. Claude Code and
OpenCode descriptors record `requested_subagent_type`; they use the requested
runtime subagent only when it is explicitly confirmed by
`E2E_HARNESS_AVAILABLE_SUBAGENTS` (comma-separated names, or `*`). Otherwise
they safely fall back to `general-purpose` and record
`subagent_fallback_reason: runtime_subagent_not_confirmed`. Per-role
`E2E_HARNESS_SUBAGENT_TYPE_<ROLE>` overrides still win.

Multi-worker phases additionally include
`agent_team_plan`, `worker_descriptors`, and generated artifacts under the run
directory:

- `agent-team-plan.json`
- `dispatch-invocations/<phase>-<timestamp>.json`

Bundled profiles live in `agent-teams/default-*.yaml`. Project-local profiles
must be explicitly selected with `--team-profile` and should live under
`.e2e/agent-teams/`.
