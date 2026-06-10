# Enterprise Harness Target Architecture

> Date: 2026-06-03
> Scope: `skills/e2e-dev-harness`
> Status: architecture recommendation

## Executive Summary

当前 `e2e-dev-harness` 的方向是正确的，不应该推翻重写。它已经从脚本集合进化成一个确定性控制面：状态机、phase lock、dispatch、context pack、evidence、checkpoint、compact stdout 都在往企业级 harness 的正确方向走。

真正的问题不是理念，而是工程形态还没有完全产品化。当前系统已经具备强控制力，但仍然有脚本边界过厚、状态来源分散、策略硬编码、runtime adapter 边界不够清晰、可观测性不足等问题。

企业级更好的设计应该是：

1. 保留现有 deterministic gates 作为信任锚。
2. 将 coordinator 固化为瘦控制面，只做决策、派发、对账、恢复。
3. 将每个 phase 的具体执行移动到隔离 worker。
4. 将状态从多个 JSON 文件约定升级为事件日志加快照。
5. 将 gate、scanner、runtime、policy 做成可注册扩展点。
6. 将 CLI、模板、配置、观测面产品化。

## 关键校准：交付保真是前提，不是默认（2026-06-10 补）

> 依据：jeepay 端到端试跑产物审计 + 保真链蓝图 `docs/2026-06-10-harness-delivery-fidelity-blueprint.md`。

本文档默认了一个未经验证的前提：**harness 的 deterministic gate 与 evidence 链是可信的信任锚**。jeepay 的真实试跑推翻了这个前提——

- `mvn test` 55 个测试全绿、`run-state` 标 `VERIFIED`、harness 判定"交付完成"；
- 但设计文档要求的风控引擎、T+1 清结算、乐观锁、资金冻结**一个都没真正落地**；空方法配空断言、乐观锁无 `@Version` 靠 mock 掩盖、`verification` 证据 sha256 是占位符且根本不被校验。

即：**当前 harness 的"可信"是"看起来可信"。它优化的是"通过 gate"，而不是"符合设计文档"，两者之间没有任何机制绑定。**

因此本文档原列的 5 个 gap（控制面形态、状态分散、扩展点、runtime adapter、observability）全部是**工程形态**问题；它们之上还缺一个更根本的维度——**交付保真（delivery fidelity）**。把一个空壳 gate 产品化、事件化、插件化，只会把"自动自欺"做得更精致。**保真必须前置于产品化。** 详见下方 Gap 0 与 Phase 0。

## Current Strengths

### 1. Coordinator And Worker Separation

当前 harness 已经形成 coordinator/worker 分离的核心模型：

- `skills/e2e-dev-harness/scripts/coordinator_flow.py`
  - 生成 `execution_packet`。
  - 明确当前 lifecycle 的目标、下一条命令、允许写入、禁止动作、证据要求。
  - 将 coordinator 定位为 `coordinator-only`。
- `skills/e2e-dev-harness/scripts/dispatcher.py`
  - 生成 runtime spawn request。
  - 支持 Claude Code `Task`、Codex `multi_agent_v1.spawn_agent`、manual dispatch。
  - 要求 dispatch ack 和 worker handle。
- `skills/e2e-dev-harness/scripts/context_pack.py`
  - 对 worker 输入施加 12 文件 / 120KB 上限。
  - 声明 request-scoped no-inherited context policy。

这是企业级 harness 的正确内核：主 agent 不再携带全部业务上下文，而是只负责生命周期推进、任务派发和结果对账。

### 2. Deterministic Gates Over Prompt Advice

当前 harness 不是靠提示词劝 agent 遵守流程，而是靠文件锁、状态机、证据链和 hook 约束行为。

关键能力包括：

- `agent_scheduler.complete()` 要求 dispatcher-confirmed completion。
- `dispatcher.worker_identity_blockers()` 阻止复用 coordinator identity。
- `phase_guard.guidance_for_lifecycle()` 将每个 lifecycle 的合法动作显式化。
- `run_state.py` 记录状态转换历史。
- `handoff_gate.py`、`reviewer_gate.py`、`implementation_gate.py`、`coverage_gate.py` 分别验证关键证据。

这类硬约束是 harness 的护城河。企业级设计必须继续保留，不要因为引入 team/subagent 就弱化 gate。

### 3. Coordinator Context Pollution Is Being Addressed

当前系统已经开始治理 coordinator 上下文污染：

- `session_checkpoint.py` 统计 evidence bytes、phase events、tool calls、dispatch waves。
- `output_contract.py` 将完整结果落盘，stdout 只保留 compact contract。
- `coordinator_summary.py` 持久化 coordinator 可恢复摘要。
- `WAITING_DISPATCH` 把 runtime 无法自动 spawn 的场景变成显式暂停，而不是让 coordinator 本地代做。

这个方向非常关键。企业级 harness 的最大失败模式不是 agent 不会做事，而是 coordinator 被中间态、证据块、review 输出和路径噪声淹死，最后绕过 harness 手工编码。

## Current Gaps

### 0. Delivery Fidelity Is Assumed, Not Enforced（最根本）

下列 5 个 gap 都是"形态"问题；本 gap 是"是否真的在交付"问题，优先级最高。harness 把"需求→交付物"用证据钉死的链条，在每一环都断了（jeepay 实证）：

| 保真环 | 应保证 | jeepay 实际 | 缺的机制 |
| --- | --- | --- | --- |
| ① 需求保真 | 设计文档→可机器校验的验收契约 | clarification 把验收标准记成 prose 勾选框，不绑定任何校验 | acceptance contract（验收项→ID→可观察行为）|
| ② 范围保真 | 设计的范围=交付的范围 | `tier=minimal` 把 80+ 文件需求缩成 Phase1 骨架仍标 VERIFIED；payment/前端/MQ 零改动、无建表 SQL | 范围分解 + 按范围核完成度；子集记 PARTIAL |
| ③ 实现保真 | 测试派生自验收项、断言真实行为 | 空方法 + assertDoesNotThrow 空断言；乐观锁无 @Version 用 mock 掩盖 | 测试实质闸门（红绿同批、非空断言、覆盖验收项）|
| ④ 证据保真 | 每个"完成"可被独立复算 | sha256 占位符、手写证据；最终 `verification` key 根本不在校验范围 | gate 自验复算，拒绝自报 |
| ⑤ 认证层自身保真 | 认证系统自己得可靠 | harness 自测随机顺序污染（7 failed→固定 3 failed）、Windows 编码基线长期红 | 测试隔离 + 清零基线 |

> 元教训：会执行的 Agent 在无人逐步核验时**天然倾向产出"看起来完成"而非"真正完成"**（本次审计中执行 Agent 自身也发生过伪造工具输出）。故全自动交付的前提是 ④⑤ 这种"不信任何自报、强制独立复算、认证层自身可信"。否则"全自动"="全自动自欺"。

### 1. Control Plane Is Still Script-Shaped

当前核心文件仍然偏大：

- `e2e_dev_harness.py`: 主 CLI 仍然承担大量路由和模板逻辑。
- `phase_guard.py`: hook enforcement、lifecycle guidance、write budget、dispatch context parsing 混在一起。
- `dispatcher.py`: runtime capability、spawn request、ack、completion、manual recovery、event 写入都在一个模块中。

这说明控制面概念已经存在，但还没有成为清晰的 domain package。

### 2. State Truth Is Distributed

一次 harness run 的真相分散在多个文件：

- `run-state.json`
- `agent-schedule.json`
- `.phase-lock`
- `dispatch-events/*.json`
- `context-packs/*.json`
- `coordinator-summary.json`
- `session-checkpoint.json`

这使 doctor 必须做一致性审计，也让恢复逻辑容易复杂化。企业级系统需要一个更强的状态模型：append-only event log 加派生快照。

### 3. Extension Points Are Too Hard-Coded

当前可配置性比较强的是 review profiles，但以下能力仍然偏硬编码：

- lifecycle 阶段。
- gate 逻辑。
- rework routing。
- scanner。
- runtime dispatch policy。
- template 格式。
- language-specific checks。

企业团队通常需要接入 SonarQube、内部 CI、安全扫描、合规审批、不同语言 scanner 和自定义质量门禁。如果这些都要改源码，harness 就很难成为团队级平台。

### 4. Runtime Adapter Boundary Is Thin

当前 dispatcher 已经支持多 runtime，但 runtime adapter 还没有成为正式抽象。理想情况下，每个 runtime 都应实现统一接口：

- `capabilities()`
- `spawn(task, context_pack)`
- `ack(task, worker_handle, worker_session)`
- `complete(task, evidence)`
- `recover(task, reason)`

并且每个 adapter 应该有契约测试，确保 Claude Code、Codex、manual runtime 在失败语义上保持一致。

### 5. Observability Is Not Yet Product-Grade

当前有 compact stdout、doctor、coordinator summary、dispatch events，但还缺少产品化观测面：

- structured logs。
- trace id。
- run timeline。
- failure taxonomy。
- replay report。
- metrics summary。
- one-command diagnosis。

企业级 doctor 不只应该回答“环境是否可用”，还应该回答：

- 这个 run 为什么卡住？
- 哪个 event 造成状态不一致？
- 哪个 worker 没有返回合法证据？
- 下一条合法修复命令是什么？
- 哪些 manual recovery 还没有审批？

## Target Architecture

### 1. Layered Architecture

推荐目标结构：

```text
e2e_harness/
  domain/
    run_state.py
    lifecycle.py
    schedule.py
    dispatch.py
    evidence.py
    gates.py
    execution_packet.py
  engine/
    state_store.py
    event_log.py
    orchestrator.py
    gate_runner.py
    recovery.py
  adapters/
    runtime/
      claude_code.py
      codex_multi_agent.py
      manual.py
    scanners/
      java_spring.py
      generic.py
    ci/
      github_actions.py
  policies/
    lifecycle_policy.py
    write_policy.py
    review_policy.py
    context_budget_policy.py
  templates/
    prompts/
    handoffs/
    reports/
  cli/
    main.py
    commands/
      start.py
      next.py
      dispatch.py
      gate.py
      doctor.py
      recover.py
```

CLI 应该只是薄壳。真正的 harness 行为应在 `domain/` 和 `engine/` 中表达。

### 2. Domain Model

建议引入明确的 domain objects：

| Object | Responsibility |
| --- | --- |
| `RunState` | 当前 lifecycle、gates、owners、history、schema version |
| `LifecycleTransition` | from/to/gate/evidence/status 的合法转换 |
| `TaskSchedule` | scheduled tasks、dependency phases、parallel groups |
| `DispatchRecord` | task id、agent、runtime、worker handle、status |
| `ContextPack` | worker 输入输出边界、budget、no-inherited context policy |
| `EvidenceRef` | path、sha256、type、producer、validation status |
| `GateResult` | ready、blocked reasons、warnings、required fixes |
| `ExecutionPacket` | coordinator 下一步的 machine-readable contract |

这些对象应有 schema version，并且通过统一 serializer 持久化。

### 3. Event Log Plus Snapshots

推荐将状态写入方式改为：

```text
docs/agent-runs/<run>/
  events/
    000001-run-started.json
    000002-worker-dispatched.json
    000003-worker-acknowledged.json
    000004-worker-completed.json
    000005-gate-passed.json
  snapshots/
    run-state.json
    agent-schedule.json
    coordinator-summary.json
  evidence/
  context-packs/
```

所有状态变化先写 event，再派生 snapshot。这样可以获得：

- 可 replay。
- 可 audit。
- 可 migration。
- 可 recovery。
- 可 diff。
- 可解释 doctor 结论。

当前 `run-state.json` 和 `agent-schedule.json` 可以继续作为兼容 snapshot，但不应该长期作为唯一真相。

### 4. Policy And Gate Registry

企业级 harness 应支持注册式扩展：

```python
class GateProvider:
    name: str
    phases: list[str]

    def validate(self, request: GateRequest) -> GateResult:
        ...


class ScannerProvider:
    name: str
    languages: list[str]

    def discover_scope(self, repo: Path, request: RunRequest) -> ScopeReport:
        ...


class RuntimeAdapter:
    name: str

    def capabilities(self) -> RuntimeCapabilities:
        ...

    def spawn(self, task: ScheduledTask, context: ContextPack) -> SpawnResult:
        ...
```

默认 provider 由 harness 内置，团队 provider 通过 `.e2e/config.yaml` 注册。

### 5. Thin Coordinator Contract

Coordinator 的唯一稳定输出应是 `ExecutionPacket`：

```json
{
  "schema": "e2e-dev-harness.execution-packet.v1",
  "lifecycle": "PLANNED",
  "objective": "Dispatch TDD red and R2 review workers.",
  "primary_command": "python ... dispatch-beat ...",
  "allowed_writes": ["docs/agent-runs/"],
  "forbidden_actions": ["write production code before implementation gate"],
  "required_evidence": ["red-test evidence", "R2 review report"],
  "completion_checks": ["run-state lifecycle becomes RED_READY"],
  "next_gate": "tdd_red"
}
```

全文输出、worker prompt、review report、gate details 都应该落盘，只在 stdout 返回路径。

### 6. Runtime Adapter Contract

推荐统一 runtime 状态机：

```text
planned
  -> dispatch_requested
  -> worker_spawned
  -> worker_acknowledged
  -> worker_running
  -> worker_completed
  -> evidence_validated
  -> task_closed
```

任何 runtime 如果无法证明 `worker_acknowledged`，就进入 `WAITING_DISPATCH`，不允许 coordinator 本地代做。

### 7. Observability Contract

每个命令都应写入：

- full result JSON。
- compact stdout。
- structured log event。
- optional trace event。

建议引入统一字段：

```json
{
  "run_id": "...",
  "trace_id": "...",
  "command": "dispatch-beat",
  "lifecycle": "PLANNED",
  "event": "worker_dispatch_requested",
  "task_id": "T02",
  "status": "blocked",
  "blocked_reason_codes": ["missing_context_pack"],
  "next_command": "..."
}
```

## Recommended Evolution Plan

> 次序校准（2026-06-10）：下列 Phase 1–5 是**产品化形态**演进；它们之前必须先有 Phase 0 建立**交付保真**，否则是在把空壳 gate 产品化。

### Phase 0: Establish Delivery Fidelity（前置地基）

Goal: 让"通过 gate"收敛于"符合设计文档"，使后续产品化建立在可信的 gate/evidence 之上。

Tasks（每项仍走 TDD + `gitnexus_impact` + `detect_changes`，不即兴改码）:

1. ④ 证据保真：gate 自验复算；`verification` 纳入命令证据校验；拒绝非 `record_command` 产出（缺 environment / 哈希非 64hex）。并入 `risk-remediation` plan。
2. ⑤ 认证层自身保真：修 harness 自测的共享状态隔离（随机顺序污染）+ 固定 IO 编码、清零基线红。这是其余一切验证可信的地基，应最先做。
3. ① 需求保真：clarification 产出结构化验收契约（每条验收标准→ID→可观察行为）。
4. ③ 实现保真：测试派生自验收契约；检测空方法/零断言测试；强制 RED 与 GREEN 同一批测试。
5. ② 范围保真：设计→service/表/phase 范围分解；按范围核完成度；子集交付记 PARTIAL 而非 VERIFIED。

Exit criteria:

- 伪造/手写 evidence 无法通过任何 gate（含 verification）。
- harness 自测在随机顺序下稳定全绿，基线无长期红。
- 每条设计验收标准都能追溯到一个会失败的测试，VERIFIED 要求其全部为真。
- 子集交付不会被标记为 VERIFIED。

### Phase 1: Stabilize Current Control Plane

Goal: 不改变用户行为，先让当前控制面边界更清晰。

Tasks:

1. 保持 `coordinator_flow.py`、`output_contract.py`、`session_checkpoint.py` 的现有分工。
2. 将 `e2e_dev_harness.py` 继续瘦身为 CLI router。
3. 将 lifecycle guidance、todo policy、preflight policy 继续移出主入口。
4. 为 compact stdout 和 `ExecutionPacket` 增加契约测试。
5. 保持 top-level `full_result_path` 兼容。

Exit criteria:

- CLI 行为兼容。
- 高频命令 stdout 稳定小于 1KB。
- full result JSON 包含完整机器可读信息。
- `python -m unittest discover -s tests` 通过。

### Phase 2: Introduce Event Log Without Breaking Snapshots

Goal: 先双写 event log 和现有 snapshot。

Tasks:

1. 新增 `events/` append-only writer。
2. 给 dispatch、ack、complete、gate transition 写 event。
3. 从 event 派生 `run-state.json` 和 `agent-schedule.json`。
4. doctor 同时检查 snapshot 和 event consistency。
5. 增加 replay 测试。

Exit criteria:

- 现有 JSON 文件仍兼容。
- 新 run 可以从 event replay 出相同 snapshot。
- doctor 能指出第一个不一致 event。

### Phase 3: Formalize Runtime Adapters

Goal: 把 runtime 差异从 dispatcher 主体中移出。

Tasks:

1. 定义 `RuntimeAdapter` interface。
2. 实现 Claude Code adapter。
3. 实现 Codex adapter。
4. 实现 Manual adapter。
5. 为每个 adapter 写相同契约测试。

Exit criteria:

- dispatcher 只调用 adapter interface。
- 无 hook 环境必然进入 `WAITING_DISPATCH`。
- 不能伪造 worker identity。

### Phase 4: Add Plugin Registry

Goal: 企业定制不改 harness 源码。

Tasks:

1. 增加 `.e2e/config.yaml`。
2. 支持注册 custom gates。
3. 支持注册 scanners。
4. 支持注册 policy packs。
5. 支持模板目录覆盖。

Exit criteria:

- 能通过配置接入一个示例 custom gate。
- 能用非 Java scanner 示例跑通。
- 默认行为不变。

### Phase 5: Productize Observability And Recovery

Goal: harness 能自解释、自恢复、自审计。

Tasks:

1. 增加 structured logging。
2. 增加 `recover` 命令。
3. 增加 run timeline report。
4. 增加 failure taxonomy。
5. 扩展 `doctor --state`，输出单条修复路径。

Exit criteria:

- 用户可以用一个命令知道 run 卡在哪里。
- manual recovery 必须有审批 event 和 evidence hashes。
- run summary 可直接用于 PR 或审计记录。

## Design Principles

### Preserve

- 状态机驱动开发流程。
- phase lock 和 hook enforcement。
- dispatcher-confirmed completion。
- worker identity isolation。
- request-scoped context pack。
- compact stdout 加 full result path。
- GitNexus impact/detect-changes 作为关键证据。
- （限定，2026-06-10）以上"deterministic gates / dispatcher-confirmed completion / evidence 链"作为信任锚，前提是**锚本身可信**；jeepay 证明当前它们形同虚设（见 Gap 0）。Preserve 的是机制骨架，必须先经 Phase 0 补足保真，"信任锚"才名副其实。

### Change

- 将脚本函数提升为 domain/engine 模块。
- 将 JSON 文件约定提升为 schema versioned objects。
- 将分散状态提升为 event log 加 snapshot。
- 将 runtime 分支提升为 adapter。
- 将 gate/scanner/policy 提升为 registry。
- 将错误消息提升为带 next command 的 failure taxonomy。

### Avoid

- 不要引入外部编排框架替代现有 deterministic gates。
- 不要让 subagent 自协调绕过 harness。
- 不要放松 R1/R2/R3 review isolation。
- 不要为了快速体验允许 coordinator 代做 worker 工作。
- 不要用 find-and-replace 或大爆炸重构核心 control plane。

## Practical Verdict

当前 harness 已经有企业级控制模型，但还不是企业级产品形态。

更准确的成熟度判断：

- Control model: strong。
- Gate rigor: strong。
- Multi-agent isolation: improving and directionally correct。
- Context management: recently improved, still needs product hardening。
- Maintainability: medium risk。
- Extensibility: biggest gap。
- Observability and recovery: next major enterprise requirement。

最佳路线不是重写，而是内核化、事件化、插件化、产品化。

一句话：

> 保留 deterministic harness 作为控制面，把 phase 执行彻底 worker 化，把状态升级为 event-sourced audit trail，再用 adapter/plugin/config 把它变成团队可扩展平台。
