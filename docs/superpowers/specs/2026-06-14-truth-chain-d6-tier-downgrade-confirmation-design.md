# Truth-chain D6 — tier 降级确认（机器强制不变量）设计 Spec

- **日期**: 2026-06-14
- **状态**: 已实现（回溯设计记录）—— A1 主体 `3a42c1c`，F1 同提交内，F2 `a147a8f`、F3 `c184e7c`、F4 `448db0e`
- **范围**: `skills/e2e-dev-harness` —— tier 推荐纯函数、`start` 命令、tier-preview 信号、run-state 审计锚
- **基线**: A1 落地时全量 784 passed；F2/F3/F4 各 +1 红测 → 当前 787 passed
- **家族**: 续 [`2026-06-14-truth-chain-contract-fixes-design.md`](2026-06-14-truth-chain-contract-fixes-design.md)（D1–D5）的第 6 修；并以 [`2026-06-13-tier-preview-confirmation-design.md`](2026-06-13-tier-preview-confirmation-design.md) 的 preview/确认契约为前置

## 1. 问题背景

tier-preview-confirmation（前置 spec）已让 `start --preview-tier` 把"选了低于推荐的 tier"作为**信号**吐给协调器，但"低于推荐 = 降级必须经用户确认"仍只是**文档约定**：没有任何机器不变量阻止协调器把一次历史偏好直接当成当前选择、在用户不知情下建一个降级 run。

这与 D1–D3 同源——**同一事实由两处独立判断会漂移**：是否构成降级、是否已确认，散落在协调器的解读里，而不在权威处落定一次。D6 把"降级需确认"从 prose 约定升级为**机器强制不变量**。

随附 4 条收尾（均为 review 逐行核出，非缺陷）：

| # | 严重度 | 位置 | 缺陷 |
|---|---|---|---|
| F1 | P1 | `cli/commands/start.py` `_preview_result` | preview 的硬信号原先盯 `requested_below`（是不是降级），而非 `blocked`（是否还需用户选）→ 降级已确认后仍喊 `must_ask_user`，诱导协调器重复追问 |
| F2 | P2（偏低） | `adapters/tier/recommend.py` `confirmed = requested_below and confirmation is not None` | 纯函数把任意非 None confirmation（含 `{}`、无 reason、空 reason）当已确认；"reason 即审计锚"只在 `start` CLI 层强制 → 未来别的 caller/verb 可绕过 |
| F3 | P2（偏低） | `cli/commands/start.py` `run()` | pipeline 校验排在降级阻断分支之前 → 非法 `--pipeline` + 降级时，"invalid pipeline"（exit 2）盖住 tier-downgrade-blocked（同 exit 2）信号 |
| F4 | P3 | `cli/commands/start.py` `run()` | `start` 两个错误返回不统一：tier-downgrade-blocked 带 `schema`，invalid pipeline 没有 → 消费方只能嗅 `error` 字符串而非 schema 路由 |

## 2. 设计原则

**单一真相源**：降级这一事实只落定一次——由一个**确认令牌**（confirmation token，其非空 reason 是审计锚）承载，下游只读不重算。`blocked` 是协调器面对的机器不变量，不再是文档里的劝告。auto 永不降级（requested == recommended），故永不 blocked。

preview 与 start 共用同一 `recommend_tier` 推荐，但分工严格：**preview 只出信号、永不阻断、永不 exit 2**；**start 是权威背板**——未确认降级则 exit 2、绝不建 run。

## 3. 目标 / 非目标

**目标**
- "低于推荐 = 降级需用户确认"成为机器不变量，不可被协调器解读绕过。
- 确认令牌的**非空 reason** 是唯一审计锚，且在纯函数层即被强制（F2），任何 caller 一致。
- 确认结果落 run-state `approvals.tier_downgrade`：可审计、带 reason/source，不可由对话重算。
- preview 的硬信号盯 `blocked`（是否还需用户选），不盯"是不是降级"（F1）。
- 降级阻断信号优先于 invalid-pipeline，不被同 exit 2 的兄弟错误盖住（F3）。
- `start` 错误返回统一 schema 信封（F4）。

**非目标**
- 不引入自动降级（降级仍是人类决定，与 D3 同立场）。
- 不改 tier 推荐/floor 逻辑、不动 `--impact-mode` 三态语义。
- 不把 preview 变成会 exit 2 的校验门（它是只读 dry-run）。
- 不统一 `main.py` 顶层异常信封（`{"error": str(exc)}`）—— 那是更大范围，超出 `start` 错误面。

## 4. 逐修设计

### A1 — 降级确认作为机器不变量（主体）

**纯函数（`adapters/tier/recommend.py` `recommend_tier`）**：把降级事实落到返回的 `downgrade` 块，三字段一次定死：
```python
requested_below = _rank(requested) < _rank(recommended)
confirmed       = requested_below and _is_confirmed(confirmation)   # F2: 见下
blocked         = requested_below and not confirmed
```
- `requested_below_recommended` / `requires_provenance` / `confirmed` / `blocked` 全部进 `downgrade` 块，作为单一真相源。
- auto（`selected_tier == "auto"`）令 requested == recommended，故 requested_below 恒 False → 永不 blocked。

**CLI 背板（`cli/commands/start.py` `run()`）**：
- 从 `--confirm-downgrade` + `--downgrade-reason`（strip 后非空）+ `--downgrade-source`（默认 `user`）构造确认令牌；reason 空/缺则令牌为 None、降级保持 blocked。
- 非 preview 路径若 `downgrade["blocked"]` → 返回 `2, {schema: tier-downgrade-blocked.v1, ...}`，**绝不建 run**——协调器无法把历史偏好变成当前降级。
- 确认成立（`downgrade["confirmed"]`）则把审计锚写入 run-state：
  ```python
  st.setdefault("approvals", {})["tier_downgrade"] = {
      "confirmed_tier": tier, "recommended_tier": ...,
      "reason": confirmation["reason"], "source": confirmation["source"],
      "recorded_by": "coordinator",
  }
  ```
  与 `approvals.impact_degradation`（D3）对称：一个带 reason 的可审计锚，不可由对话重算。

**CLI 参数（`cli/main.py`）**：新增 `--confirm-downgrade` / `--downgrade-reason` / `--downgrade-source`。

**不变量**：`blocked` 只由 `recommend_tier` 写、`start`/`preview` 只读；它是 start 唯一的建 run 前置闸，也是 preview 唯一的"是否还需问用户"信号源。

### F1 — preview 硬信号盯 `blocked` 而非"是不是降级"

`_preview_result` 的 `confirmation_required` / `allowed_without_user_choice` / `must_ask_user` 全部由 `tier_recommendation["downgrade"]["blocked"]` 驱动：
```python
blocked = tier_recommendation["downgrade"]["blocked"]
"confirmation_required": blocked,
"allowed_without_user_choice": not blocked,
"must_ask_user": blocked,
```
确认令牌已让 blocked=False 时，preview 正确报 `must_ask_user=False`，不再因"这仍是一次降级"而重复追问。

### F2 — "reason 即审计锚"下沉到纯函数

**根因**：`confirmed = requested_below and confirmation is not None` 把任意非 None 令牌（含 `{}`、`{"source":"user"}`、`{"reason":""}`、`{"reason":"   "}`、`{"reason":None}`）都当已确认；reason 非空校验只在 `start`。

**改动**：纯函数新增 `_is_confirmed`，令牌必须携带**非空字符串 reason** 才算数：
```python
def _is_confirmed(confirmation: dict | None) -> bool:
    if not confirmation:
        return False
    reason = confirmation.get("reason")
    return isinstance(reason, str) and bool(reason.strip())

confirmed = requested_below and _is_confirmed(confirmation)
```

**不变量**：reason 是审计锚这一约束在纯函数层即成立，无论 caller 是 `start`、其他 verb 还是测试，皆一致；`start` 原有的 strip-非空判断保留为纵深防御。

### F3 — 降级背板优先于 invalid-pipeline（排序）

**根因**：`run()` 原序 pipeline load/validate → invalid pipeline 早退 → preview 返回 → blocked 背板。非法 `--pipeline` + 降级时，"invalid pipeline" 先 exit 2，盖住降级信号。

**约束**：blocked 背板**必须**排在 preview 返回之后（preview 永不阻断、要 exit 0 出信号），而 preview 又需要 pipeline 信息。

**改动**：降级判定只依赖 `tier_recommendation`（与 pipeline 无关），故把 **preview 返回**与 **blocked 背板**双双前移到 load/validate 之前：
```python
pipeline_ref = ... ; custom = pipeline.is_path(pipeline_ref)   # 廉价，无 load
if preview_tier:        return 0, _preview_result(...)          # 只需 pipeline_ref + custom
if downgrade["blocked"]: return 2, {tier-downgrade-blocked.v1} # 出兄弟错误之前
spec = load_spec(...) ; merged = merge(...) ; ok, errors = validate(...)
if not ok:              return 2, {invalid-pipeline.v1}
```
副产物：preview 不再依赖 `merged`，故非法 `--pipeline` 也不再把 preview 变成错误——契合其"只读 dry-run、永不 exit 2"契约（此前 preview+非法 pipeline 无测试覆盖，属隐性不一致，今对齐）。

### F4 — `start` 错误返回统一 schema 信封

invalid-pipeline 错误补 `schema`，与 tier-downgrade-blocked 兄弟一致：
```python
return 2, {"schema": "e2e-dev-harness.invalid-pipeline.v1",
           "error": "invalid pipeline", "pipeline": pipeline_ref, "errors": errors}
```
诊断字段（error/pipeline/errors）不变；消费方可按 schema 路由而非嗅 `error` 字符串。命名遵循仓库 `e2e-dev-harness.<thing>.v1` 约定。

## 5. 测试策略（TDD：先红后绿）

| 修 | 红测要点 | 文件 |
|---|---|---|
| A1 | explicit 低 tier 未确认 → blocked=True 且 `tier-downgrade-blocked.v1` exit 2、不建 run；确认（带 reason）→ 建 run 且 run-state 落 `approvals.tier_downgrade`；above-recommended 不 blocked；auto 永不 blocked | `tests/test_tier_recommend.py`、`tests/test_cli_e2e.py` |
| F1 | preview+已确认降级 → `must_ask_user=False` / `confirmation_required=False` / `allowed_without_user_choice=True`，且不建 run | `tests/test_cli_e2e.py` |
| F2 | 令牌为 `{}` / 无 reason / 空 reason / 纯空格 reason / `reason=None` → confirmed=False 且 blocked=True | `tests/test_tier_recommend.py` |
| F3 | 降级未确认 + 非法 `--pipeline` → `tier-downgrade-blocked.v1`（非 invalid pipeline）、exit 2、不建 run | `tests/test_cli_e2e.py` |
| F4 | invalid-pipeline 错误带 `schema == e2e-dev-harness.invalid-pipeline.v1`，且 error/pipeline/errors 保留 | `tests/test_cli_custom_pipeline_e2e.py` |

每条改前按 `CLAUDE.md` 跑 `gitnexus_impact`（报 blast radius），改后跑 `gitnexus_detect_changes` + 全量测试，守住基线（A1 时 784 → 当前 787 passed）。

## 6. 实现顺序（实际）

1. **A1 + F1**（同提交 `3a42c1c`）：纯函数三字段 + start 背板 + run-state 锚 + preview 硬信号盯 blocked。
2. **F2**（`a147a8f`）：`_is_confirmed` 下沉，最简最干净，先拿下。
3. **F3**（`c184e7c`）：preview/blocked 双前移，谨慎——须保住 preview 既有契约与 invalid-pipeline 既有行为。
4. **F4**（`448db0e`）：纯整洁度，invalid-pipeline 补 schema。

> F3/F4 同改 `start.run()` 且都涉 invalid-pipeline 返回，但拆成两个原子提交（F3 重排序、F4 补字段），各自焦点单一、便于回溯。

## 7. 风险

- **F3 行为变更（已知、可接受）**：preview+非法 pipeline 由"exit 2 报错"改为"exit 0 出 preview"。此前无测试覆盖该组合，且新行为契合 preview "永不 exit 2" 契约，属对齐而非回归。
- **F2 收缩面**：`confirmed` 判定收紧（拒空 reason 令牌）。唯一真实 caller `start` 本就只在 reason 非空时构造令牌，故对现有路径与全部确认测试无影响；纯属堵未来 caller 的绕过缝隙。
- **迁移代价**：A1 是新建闸，不改既有 run-state 读路径；在途 run 不含 `approvals.tier_downgrade` 时下游按"无确认"处理，与设计一致。

## 8. 范围外

- 自动降级 / 由对话重算降级事实。
- `main.py` 顶层异常信封统一（更大范围）。
- tier 推荐 floor / `--impact-mode` 三态语义变更。
- preview 升级为会阻断的校验门。
