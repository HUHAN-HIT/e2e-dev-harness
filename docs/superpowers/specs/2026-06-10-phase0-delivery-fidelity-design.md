# Phase 0 — Delivery Fidelity Design

> Date: 2026-06-10
> Scope: `skills/e2e-dev-harness`
> Source of truth: `docs/enterprise-harness-target-architecture.md` (Gap 0 / Phase 0)
> Companion: `docs/2026-06-10-harness-delivery-fidelity-blueprint.md`
> Status: approved design, pending implementation plan

## Goal

让 harness 的「通过 gate」收敛于「符合设计文档」。当前 harness 优化的是“通过 gate”，
两者之间没有机制绑定（jeepay 实证：55 测试全绿 + `VERIFIED`，但风控/清结算/乐观锁一个未落地）。

Phase 0 补齐交付保真链的剩余环节，作为后续产品化（Phase 1–5）的可信地基。

## Current state (verified 2026-06-10)

| 环 | 状态 | 证据 |
| --- | --- | --- |
| ④ 证据保真 | ✅ 已闭合 | `validate.py`: `verification` 在 `COMMAND_KEYS`；`_is_genuine_command_evidence` 拒伪造（需 `environment`+64hex）；`verification` 走 replay 复算 |
| ⑤ 认证层自身保真 | ⚠️ 半成 | UTF-8 输入通道已加；但 `pytest-randomly` 已移除 → 随机顺序污染无法复现/防护；固定顺序 251 全绿 |
| ① 需求保真 | ❌ 未开始 | clarification 验收标准仍是 prose 勾选框，不绑定校验 |
| ③ 实现保真 | ❌ 未开始 | IMPLEMENTED 闸只看 exit_code==0，看不见空断言/未覆盖验收项 |
| ② 范围保真 | ❌ 未开始 | tier 可静默缩小范围；子集交付仍标 VERIFIED |

本设计覆盖剩余 4 环，按文档依赖次序：**⑤ → ① → ③ → ②**。

## Execution discipline (全程强制)

每一环独立推进，遵守项目 CLAUDE.md 与架构文档要求：

1. 编辑任一 symbol 前先 `gitnexus_impact(target, direction="upstream")`，HIGH/CRITICAL 必须先报告。
2. TDD：先写会失败的测试（红），最小实现转绿。
3. 提交前 `detect_changes(scope="all")`，确认改动范围与本环一致。
4. 每环单独提交。
5. 不用 e2e-dev-harness 自身驱动本次修复（被修对象的 gate 正是被质疑对象，避免自我认证回环）。

---

## ⑤ Auth-layer self-fidelity（地基）

**为什么先做**：一个负责认证别人“是否完成”的系统，自身测试基线必须可信；否则①②③的验证都不可信。

**Decision A（已批准）**：用**无第三方依赖**的可复现洗牌守卫，而非重新引入 `pytest-randomly`，保持项目“零运行时依赖”属性。

### 机制

1. **检测器**：新增 `skills/e2e-dev-harness/tests/conftest.py`，实现 `pytest_collection_modifyitems`：
   - 读 `E2E_TEST_SEED`（或 `PYTEST_SEED`）环境变量；存在时用该种子 `random.Random(seed).shuffle(items)` 重排收集顺序，并在 `pytest_report_header` 打印所用种子，使任何失败可被精确复现。
   - 不设种子时保持默认顺序（不影响既有 CI/本地默认行为）。
2. **定位泄漏**：用 systematic-debugging，在若干固定种子（如 1,2,3,42,1337）下运行全套，定位随种子变化而红的用例。常见泄漏源：
   - 模块级/类级可变全局未在测试间复位；
   - `os.chdir` 未还原（应改用 `monkeypatch.chdir`/`tmp_path`）；
   - 直接 `os.environ[...]=` 未还原（应改用 `monkeypatch.setenv`）；
   - 模块属性 monkeypatch 未隔离；
   - 跨用例复用同一固定临时路径。
3. **逐个修死**：每个泄漏点先用“该种子下复现失败”的测试钉住，再以正确的 fixture/teardown 修复（最小改动，不重写测试语义）。
4. **编码基线**：定位 `test_cli_request_file` 在 Windows GBK 控制台 `UnicodeDecodeError` 根因，固定子进程/读管道的 `encoding="utf-8"`（或 `PYTHONIOENCODING`），清零基线红。

### Exit criteria

- 在 ≥5 个不同 `E2E_TEST_SEED` 下连续运行全套，全部全绿、可重复。
- `conftest.py` 在失败时打印可复现的种子。
- 无被跳过/被注释的“长期红”用例残留。

### Touchpoints（预估，实际以 impact 为准）

- 新增 `skills/e2e-dev-harness/tests/conftest.py`
- 修改泄漏用例（按定位结果，预计少量 test 文件 + 个别被测模块的测试可控点）

---

## ① Requirements fidelity — acceptance contract（源头）

**Decision B（已批准）**：验收契约存为**独立** `acceptance-contract.json`（schema versioned），便于 gate 独立复算，而非内嵌 run-state。

### 机制

1. **领域模型**：新增 `core/acceptance.py`（纯逻辑，无 I/O），定义契约结构与校验：
   ```json
   {
     "schema": "e2e-dev-harness.acceptance-contract.v1",
     "items": [
       {"id": "AC-001", "criterion": "四条支付链路统一风控拦截",
        "observable_behavior": "对四种 channel 各发一笔超限交易，均返回风控拒绝码且不落账"}
     ]
   }
   ```
   - 校验：非空；`id` 唯一且匹配 `^AC-\d{3,}$`；每项 `criterion` 与 `observable_behavior` 均非空。
2. **产出**：clarification worker 模板（`e2e-harness-clarification` skill / 对应 handoff 模板）新增“结构化验收契约”产出段，落盘 `acceptance-contract.json`。
3. **闸门**：在 CLARIFIED → 下一阶段的 handoff/clarification gate 增加契约良构校验（缺失或非法即阻断，给出 next command）。
4. **锚点**：契约 ID 作为后续 RED 测试与 ③ 实现闸的引用锚（把①连到③）。

### Exit criteria

- 缺失/空/ID 重复/缺可观察行为的契约无法通过 CLARIFIED 闸。
- 合法契约落盘并可被独立 gate 复算（不依赖 worker 自报）。
- 每条设计验收标准在契约中有唯一 ID。

### Touchpoints

- 新增 `core/acceptance.py` + `tests/test_acceptance.py`
- 修改 clarification 模板 / handoff 产物约定
- 修改对应 gate（`adapters/.../*_gate` 或 `core/gates.py` 声明）

---

## ③ Implementation fidelity — test-substance gate（实现闸，依赖①）

**Decision C（已批准）**：测试实质检测为**启发式**；策略为**默认阻断明显空壳（零断言 / 纯 `assertDoesNotThrow` 空体 / `assert True`），可疑项记 warning 不阻断**——宁可漏判不可误杀真实测试。

### 机制

1. **分析器**：新增 `core/test_substance.py`（或 `adapters/evidence/` 下分析器），输入测试文件/测试清单，输出每个测试节点的判定：`empty`（阻断）/ `suspicious`（warning）/ `ok`。
   - 语言感知启发式：
     - Python：函数体内无 `assert` 且无已知断言调用 → `empty`；仅 `assert True`/`pass` → `empty`。
     - Java：`assertDoesNotThrow` 包裹空 lambda / 方法体仅注释 → `empty`；无任何 `assert*`/`verify(` → `suspicious`。
   - 仅做静态文本/AST 级启发，不执行测试。
2. **同批校验**：IMPLEMENTED 闸消费 RED 测试清单与 GREEN 测试清单，要求二者为**同一批**测试节点（红→绿，而非各跑各的）；不一致即阻断。
3. **覆盖校验**：要求 GREEN 测试集覆盖①契约的全部 `AC-ID`（通过测试名/标记/映射文件引用 AC-ID）；未覆盖即阻断。
4. **闸门接入**：扩展 IMPLEMENTED gate，把上述三项纳入；任一 `empty`/集合不一致/未覆盖即 block，`suspicious` 仅汇报。

### Exit criteria

- 空方法 + `assertDoesNotThrow` 空断言无法通过 IMPLEMENTED 闸。
- RED 与 GREEN 测试集不一致被阻断。
- 未覆盖某条 AC-ID 被阻断；可疑测试只记 warning，不误杀。

### Touchpoints

- 新增 `core/test_substance.py` + `tests/test_test_substance.py`
- 修改 IMPLEMENTED gate 与其证据约定（RED/GREEN 测试清单产出）
- 可能扩展 RED/GREEN worker 模板以产出测试节点清单 + AC 映射

---

## ② Scope fidelity — PARTIAL vs VERIFIED（范围闸）

**Decision D（已批准）**：PARTIAL 用 run-state 上的**标志位 + 未交付项清单**表达（最小侵入），不引入新生命周期终态。

### 机制

1. **范围清单**：从需求/设计派生预期范围 `scope-manifest.json`：
   ```json
   {
     "schema": "e2e-dev-harness.scope-manifest.v1",
     "services": ["payment", "merchant", "manager"],
     "tables": ["t_risk_rule", "t_settlement_batch"],
     "phases": ["Phase1", "Phase2", "Phase3", "Phase4"]
   }
   ```
   - 由 clarification/planning 阶段产出（与①同源 worker，但独立文件）。
2. **按范围核完成度**：VERIFIED 闸比对“交付范围”（changed files / 新建 artifact / 建表 SQL 存在性）与 manifest；为真子集时：
   - run-state 写 `delivery: "PARTIAL"` + `undelivered: [...]`（未覆盖的 service/表/phase）。
   - 不得标 `VERIFIED`。
3. **tier 不静默缩范围**：当 tier（含 `--tier auto`）选择会裁掉 manifest 中范围时，记录 `scope_warnings` 并阻止把缩小后的子集判为 VERIFIED（衔接已有 `--tier auto` risk 工作）。

### Exit criteria

- 子集交付落 `PARTIAL` + 未交付清单，绝不标 `VERIFIED`。
- 范围 manifest 缺失时 VERIFIED 闸明确报缺，而非默认通过。
- tier 缩小范围被显式记录与拦截。

### Touchpoints

- 新增范围 manifest 模型 + 校验（`core/scope.py` + 测试）
- 修改 VERIFIED gate / completion 证据约定
- 衔接 `adapters/tier/classifier.py` 与 `cli/commands/start.py` 的范围告警

---

## Sequencing & commits

按依赖次序，每环一组提交：

1. ⑤ `fix(e2e-dev-harness): seedable test-isolation guard + encoding baseline`
2. ① `feat(e2e-dev-harness): structured acceptance contract + clarification gate`
3. ③ `feat(e2e-dev-harness): test-substance gate (empty-shell block, AC coverage, red/green same-batch)`
4. ② `feat(e2e-dev-harness): scope manifest + PARTIAL-vs-VERIFIED gate`

每组提交前 `detect_changes`，确认改动范围与本环一致。

## Out of scope (本次不做)

- Phase 1–5 产品化（控制面内核化、event log、runtime adapter、plugin registry、observability）。
- `risk-remediation` plan 中纯工程项（provider 审计、lock recovery、KG perf 等）——除非与某环直接耦合。
- 既有审计报告中的 legacy 重构、skill 描述治理等非保真项。
