# Phase 0 交付保真 —— 实证核验报告（Delivery Fidelity Verification）

> 日期：2026-06-10
> 范围：`skills/e2e-dev-harness`
> 依据：`docs/enterprise-harness-target-architecture.md`（Gap 0 / Phase 0）+ `docs/2026-06-10-harness-delivery-fidelity-blueprint.md`
> 方法：逐条**实证核验**（读源码确认接线 + 实跑测试套件），不信任提交信息或历史摘要——遵循文档元教训"别信'看起来完成'"。

---

## 1. 结论

文档（2026-06-03 + 2026-06-10 补遗）描述的 gap 在撰写时**确曾属实**。但本分支
`fix/harness-utf8-tier-verification-gate` 上的前序工作，已将**最高优先级的 Gap 0
交付保真链（①-⑤）全部落地、接入生命周期闸门、并由对抗性测试守护**；工程形态
Gap 1-2 也基本解决。对已完成部分再"修复"等于文档自身警告的"自动自欺"，故不做重复修改。

剩余仍属实者为 Gap 3-5——文档明确排在 Phase 0 之后、并告诫"不要大爆炸重构"的
**产品化演进**，属可选前向路线，非待修缺陷。

## 2. 实证基线（本次实跑）

- Python：`pytest tests` **299 passed**（默认顺序）。
- 隔离扫描：`E2E_TEST_SEED ∈ {1,2,3,42,1337,2026,7,99,31415}` 共 **9 个随机种子全部 299 passed**。
- Node：`node --test` **51 passed / 0 failed / 0 skipped**。
- 测试套件无 `@pytest.mark.skip|xfail`、无生产 `TODO/FIXME` 掩盖未完成。

## 3. 保真链逐环核验（Gap 0）

| 环 | 应保证 | 落地点（源码） | 闸门接线（`core/lifecycle.py`） | 对抗性测试 | 判定 |
|---|---|---|---|---|---|
| ① 需求保真 | 验收标准→可机器校验契约 | `core/acceptance.py` `validate_contract` | `CLARIFIED.exit_gate = (clarification, acceptance_contract)` | `test_acceptance.py` | ✅ 已修 |
| ② 范围保真 | 设计范围=交付范围，子集记 PARTIAL | `adapters/evidence/scope.py`：`_ddl_present` 实查 `CREATE TABLE`，overclaim-COMPLETE 被拒 | `VERIFIED.exit_gate = (verification, scope_manifest)` | `test_scope_evidence.py` `test_substance_manifest.py` | ✅ 已修 |
| ③ 实现保真 | 测试派生验收项、断言真实行为 | `core/test_substance.py` 实质清单校验 | `IMPLEMENTED.exit_gate = (passing_tests, test_substance)` | `test_test_substance.py` | ✅ 已修 |
| ④ 证据保真 | "完成"可被独立复算，拒自报 | `adapters/evidence/validate.py`：`verification ∈ COMMAND_KEYS ∩ REPLAY_KEYS`（重跑复算）；`_is_genuine_command_evidence` 拒缺 environment / 非 64hex 哈希 | 经 `gates.gate_passes(repo_root=…)` | `test_gate_artifact_validation.py`：拒占位符 sha256、拒缺 environment、replay 抓手改 exit_code、真证据放行 | ✅ 已修 |
| ⑤ 认证层自保真 | 认证系统自身测试/基线可信 | `tests/conftest.py` 种子守卫 `_seeded_order`；UTF-8 stdout+input | —（套件层） | `test_conftest_shuffle.py` + 9 种子全绿 | ✅ 已修 |

**④ 的关键反制**：jeepay 原版伪造 `stdout_sha256="verification_stdout"` 现被
`test_validate_rejects_placeholder_sha256` 直接拒绝；手改 exit_code 被
`test_validate_verification_rejects_tampered_exit_code`（replay 重跑）抓住。

## 4. 工程形态核验（Gap 1-5）

| Gap | 文档主张 | 当前真实状态 | 判定 |
|---|---|---|---|
| 1 控制面脚本巨石 | `e2e_dev_harness.py` 承担大量路由/模板 | 该文件仅 **11 行** shim；已是 `core/adapters/cli` 分层包，`cli/main.py` 83 行薄路由 | ✅ 基本已解 |
| 2 状态分散 7 文件 | 真相散落 run-state/agent-schedule/.phase-lock/… | 代码仅引用单一 `run-state.json` SSOT + `.phase-lock`；审计报告亦称"单一 run-state JSON" | ✅ 基本已解（以 SSOT 收敛，非 event-log） |
| 3 扩展点硬编码 | gate/scanner/policy/template 需改源码 | 有 4 档 YAML pipelines + `adapters/domain` `adapters/scanner` registry；**缺** `.e2e/config.yaml` 团队级自定义 gate 注册 | 🟡 部分 |
| 4 runtime adapter 薄 | runtime 差异未成正式抽象 | `adapters/runtime/__init__.py` 已抽出接缝（claude-code/codex/opencode/manual + 版本化 descriptor + manual 兜底）；**缺**完整 `RuntimeAdapter` 接口与统一契约测试 | 🟡 部分 |
| 5 可观测性非产品级 | 缺 structured logs/trace/timeline/taxonomy/replay | 未实现 | 🔴 仍属实 |

## 5. Phase 0 Exit Criteria 对照

| Exit criterion（文档） | 核验结果 |
|---|---|
| 伪造/手写 evidence 无法通过任何 gate（含 verification） | ✅ `test_gate_artifact_validation.py` 4 条对抗测试全绿 |
| harness 自测随机顺序稳定全绿，基线无长期红 | ✅ 默认 + 9 种子均 299 passed；UTF-8 基线干净 |
| 每条验收标准可追溯到会失败的测试，VERIFIED 要求全部为真 | ✅ ①acceptance_contract→③test_substance 接线 + REPLAY 复算 |
| 子集交付不会被标记为 VERIFIED | ✅ `scope.py` overclaim-COMPLETE 被拒→强制 PARTIAL |

## 6. 处置

- **不做重复修复**：Gap 0 与 Gap 1-2 已达成，再改即自欺。
- **Gap 3-5** 为可选前向产品化，建议各自独立立项（TDD + `gitnexus_impact` + `detect_changes`），不并入本次收尾。
- 本报告即"落实验证"的交付物，与 Phase 0 各 ring 的实现提交一并构成可审计记录。
