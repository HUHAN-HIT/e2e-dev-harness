# Gap 4 — RuntimeAdapter 形式化（设计）

> 日期：2026-06-10 · 分支：`fix/harness-utf8-tier-verification-gate`
> 范围：`skills/e2e-dev-harness`（`adapters/runtime/` + `cli/commands/dispatch.py`）
> 依据：`docs/enterprise-harness-target-architecture.md` Gap 4 / Phase 3
> 前序约束：`docs/superpowers/specs/2026-06-07-e2e-dev-harness-u2-spawn-worker-seam-design.md`（窄接缝）
> 处置背景：`docs/2026-06-10-phase0-delivery-fidelity-verification.md`（Gap 4 判为 🟡 部分）

## 1. 问题与冲突

架构文档 Gap 4 / Phase 3 要求把 runtime 差异从 dispatcher 主体移出，形成统一
`RuntimeAdapter` 接口 + 跨 runtime 契约测试。退出标准三条（当前**未满足**）：

1. dispatcher 只调用 adapter 接口（今天 `dispatch.py` 直接调自由函数 `spawn_worker`，靠字符串分支）。
2. 无法 auto-spawn 的环境**必然进入显式阻塞**，不允许 coordinator 本地代做。
3. 不能伪造 worker identity。

但前序 **U2 设计有意把** legacy 的 `spawn/ack/complete/recover` 五方法**坍缩成单一
`spawn_worker` 窄接缝**（YAGNI，显式延迟 ack/complete/recover）。两份文档直接冲突。

### 决定性证据（推翻"复活旧状态"的诱惑）

- `docs/analysis/e2e-dispatch-auto-spawn-root-cause.md`：legacy `manual` 命中
  `supports_subagent=False` → 返回 `waiting_dispatch` / `pause_for_manual_worker`、
  **永不产出 Task spawn** —— 被记为一桩**根因卡死 bug**。
- `docs/superpowers/specs/2026-06-07-e2e-dev-harness-redesign-design.md`：redesign 把旧的
  **"6+ 重叠状态（`awaiting_runtime_spawn`/`waiting_dispatch`/`worker_running`/…）"**
  明确列为问题（"多种表示，流程识别不出'已完成'，卡死"），**刻意坍缩**为
  `pending→dispatched→running→done→failed` 单枚举。

结论：`WAITING_DISPATCH` 不是"丢失的护栏"，而是 redesign **有意删除的状态沼泽**。
架构文档那句"必然进入 WAITING_DISPATCH"的措辞**早于**该 redesign，应服从更晚的结论。

## 2. 已实现逻辑的审计发现（本设计一并处置）

| # | 问题 | 证据 | 本设计处置 |
|---|---|---|---|
| P1 | runtime 默认值不一致：`dispatch.py:33` `getattr(args,"runtime","claude-code")` vs `main.py:40` argparse 默认 `"codex"`、seam 默认 `"codex"` | 三处默认值矛盾，"claude-code" 兜底是死分支 | **修**：收敛到单一默认 `"codex"`（与 seam/argparse 一致） |
| P2 | manual/未知 runtime 自欺：`dispatch` 无条件标 DISPATCHED + 发"自己跑"指令，即便无法 auto-spawn | `dispatch.py:16-20`；`DispatchStatus.DISPATCHED` 仅此处写入 | **修**：即 (c)——`can_auto_spawn=False` 时不标 DISPATCHED，返回显式 blocked |
| N1 | `submit_evidence` 对不存在的文件仍记 hashless evidence + 标 DONE | `engine.py:26-31` | **越界**（Gap 0 ④ 证据链），本次不动，仅记录 |

## 3. 范围决定

**实现 (a)+(b)+(c)，显式排除 (d)。**

- **(a)** 引入 `RuntimeAdapter` 协议 + 每 runtime 一个 adapter 对象 + registry；dispatcher 只调接口。
- **(b)** 跨 4 runtime（claude-code/codex/opencode/manual）统一契约测试。
- **(c)** `capabilities().can_auto_spawn=False` 时，`dispatch` 返回**显式 blocked（非零退出 + `dispatch_blocked` 字段）且不标 DISPATCHED**；达成保真意图（修 P2），但**不**新增任何 dispatch 状态。
- **(d) 不做**：不把 `WAITING_DISPATCH` 复活为 `DispatchStatus` 成员或生命周期状态（见 §1 证据）。
- **不做**：`ack`/`complete`/`recover` per-runtime 方法——无真实消费者，沿用 U2 的 YAGNI 延迟（`submit`+dispatch 枚举已承担完成/失败记录）。
- **worker identity（退出标准 #3）**：现有 `_prompt` 已强制 "fresh context, no inherited coordinator chat"，且 coordinator 仍执行真实工具调用（纯控制面）。本设计**保持不弱化**该约束；契约测试断言每个非 manual 描述符携带 fresh-context `context_policy`（可机器校验的具体不变式，见 §4.5），而非声明一条难以落地的"防冒充"断言。

## 4. 设计

### 4.1 能力（纯数据）

```python
@dataclass(frozen=True)
class RuntimeCapabilities:
    name: str            # 规范化 runtime 名
    can_auto_spawn: bool # claude-code/codex/opencode=True；manual/未知=False
    spawn_tool: str | None  # "Task" / "multi_agent_v1.spawn_agent" / "task" / None
```

不变式（契约测试强制）：`can_auto_spawn == (spawn_tool is not None)`。

### 4.2 适配器协议 + registry

```python
class RuntimeAdapter(Protocol):
    name: str
    def capabilities(self) -> RuntimeCapabilities: ...
    def spawn(self, packet: dict) -> dict: ...   # 返回 descriptor（沿用现有 _claude_code/_codex/... 逻辑）
```

- 具体：`ClaudeCodeAdapter` / `CodexAdapter` / `OpencodeAdapter` / `ManualAdapter`。
- `get_adapter(name) -> RuntimeAdapter`：规范化（`codex-app`→codex）；**未知名 → ManualAdapter**（描述符带 `warning`，保留现有 fallback 语义）。
- `spawn()` 输出 descriptor 与现状**逐字节一致**（schema、tool、arguments、context_policy、no-model-pin）。

### 4.3 向后兼容 shim

```python
def spawn_worker(packet: dict, runtime: str = "codex") -> dict:
    return get_adapter(runtime).spawn(packet)
```

- 签名、默认 `"codex"`、输出**完全不变** → `tests/test_runtime_spawn.py`（14 条）零改动。
- 未知 runtime 仍走 manual + `warning`（现有 `test_unknown_runtime_falls_back_to_manual_with_warning` 绿）。

### 4.4 dispatch 命令（(c) + P1/P2）

```python
runtime = getattr(args, "runtime", None) or "codex"   # P1：单一默认
adapter = runtime_mod.get_adapter(runtime)
caps = adapter.capabilities()
packet = dispatch.worker_packet(phase, str(args.state), extra_context=extra)
packet["worker_descriptor"] = adapter.spawn(packet)   # 仍发描述符（告知人/coordinator 该跑什么）
if not caps.can_auto_spawn:                            # P2/(c)：显式阻塞，phase 不标 DISPATCHED
    packet["dispatch_blocked"] = {
        "reason": "manual_runtime_requires_human_dispatch",
        "runtime": caps.name,
        "next_action": "human dispatches the worker, then `submit` its evidence",
    }
    return 3, packet
state = run_state.mutate(args.state, _mark_dispatched)  # 仅 auto-spawn 路径标 DISPATCHED
return 0, packet
```

- auto-spawn（codex/claude-code/opencode，含默认）路径行为不变（退出 0、标 DISPATCHED）。
- 阻塞路径退出码 3（与现有 "no dispatchable worker" 退出 2 同风格）；phase 留在隐式 `PENDING`，**不新增枚举**。

### 4.5 契约测试（(b)）

新增 `tests/test_runtime_adapter_contract.py`，对 `["claude-code","codex","opencode","manual"]` 逐一断言同一组不变式：

- `get_adapter(name).capabilities().name` 规范化正确；
- `spawn(packet)["schema"] == DESCRIPTOR_SCHEMA`；
- 描述符**任意层级无 `model` 键**（全 runtime 回归守卫）；
- `context_paths` / `expected_outputs` 透传不变；
- `caps.can_auto_spawn == (descriptor.get("tool") is not None)`；
- 非 manual：描述符含 fresh-context `context_policy` 且 prompt/message 提及 skill 与 expected_outputs；
- 未知 runtime → manual 能力（`can_auto_spawn=False`）+ `warning`，不抛异常。

## 5. 验收标准

- `adapters/runtime/__init__.py` 暴露 `RuntimeAdapter`、`RuntimeCapabilities`、`get_adapter`，并保留 `spawn_worker`、`DESCRIPTOR_SCHEMA`。
- `dispatch.py` 仅经 `get_adapter(...)` 接口取描述符与能力（不再字符串分支 spawn）。
- `can_auto_spawn=False` 时 `dispatch` 退出非零、含 `dispatch_blocked`、**不**将 phase 标 DISPATCHED。
- `DispatchStatus` 枚举**不变**（无 `WAITING_DISPATCH`）。
- P1 默认值收敛为 `"codex"`。
- 新契约测试覆盖 §4.5 全部不变式；`test_runtime_spawn.py` / `test_cli_e2e.py` / `test_dispatch.py` 全绿。
- 全套件随机种子稳定全绿；改动限于 `skills/e2e-dev-harness/`；不碰 Gap 0 保真链（acceptance/scope/test_substance/validate/gates/lifecycle）。

## 6. 副作用与风险（LOW）

- 不改 `DispatchStatus` 枚举 → 无 `test_dispatch.py:8` 破坏。
- `test_cli_e2e.py:131`（manual）只查描述符字段、`_run` 不断言退出码 → 退出 3 不破坏它。
- 仅 manual/未知路径行为变化（DISPATCHED→显式 blocked），无测试对该状态写入断言。
- `engine`/`navigation` 仅对 `FAILED` 分支判断 → 对"未派发"phase 天然按 blocked/PENDING 处理，不误判生命周期。
- 信任锚（gates/evidence/lifecycle 主干）零触碰。

## 7. 明确延后（非丢弃）

- (d) `WAITING_DISPATCH` 作为状态 —— 与 06-07 redesign 决策冲突，除非出现真实多服务并行消费者再单独立项。
- `ack`/`complete`/`recover` per-runtime 方法 —— 待真有 out-of-band 确认需求。
- `DispatchStatus.RUNNING` 的活体观测 —— 待 runtime 能观测在飞 worker。
- N1（证据文件存在性）—— 属 Gap 0 ④，独立处理。

## 8. 测试策略（TDD）

红先行：先写 §4.5 契约测试 + dispatch 阻塞测试（manual 退出非零含 `dispatch_blocked`、phase 未标 DISPATCHED）+ P1 默认收敛断言 → 确认红 → 再实现 §4 使其转绿 → `detect_changes` 复核范围。
