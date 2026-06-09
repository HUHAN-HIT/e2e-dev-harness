# Harness e2e-dev-harness �?M2 计划输入 (Planning Input)

- **状�?*: 计划输入 (Planning Input) �?待新 session �?`superpowers:writing-plans` �?M2 实现计划
- **日期**: 2026-06-07
- **来源**: M1 端到端独立审�?代码 + 测试复跑 25 passed)
- **关联**:
  - 设计: [2026-06-07-e2e-dev-harness-redesign-design.md](2026-06-07-e2e-dev-harness-redesign-design.md)(§14 M2 条目、�? 门禁、�?1 裁剪、�? port 清单)
  - 交接: [../HANDOFF-e2e-dev-harness.md](../HANDOFF-e2e-dev-harness.md)(R1/R2/L1-L8 自评)
  - M1 计划: [../plans/2026-06-07-e2e-dev-harness-m1-walking-skeleton.md](../plans/2026-06-07-e2e-dev-harness-m1-walking-skeleton.md)

> 本文件不�?M2 计划本身,�?*计划输入**:把审计确认的问题翻译成可�?writing-plans 直接消费的需求条�?目标 / 验收标准 / 受影响文�?/ 不变�?。M2 计划应据�?TDD 落地�?
---

## 0. 范围界定

- **M2 = "后端完整"**(设计 §14):standard/critical/audited tier、结构化阶段裁剪(§11)、r1/r2/r3 review fan-out、把干净叶子 port �?e2e-dev-harness 窄接�?§5)�?- 本输入在 M2 范围�?*追加两条出口硬标�?*(R1、R1'=L4)与三类捎带项(L1/L2 + 廉价健壮�?L5-L7)�?- **不属 M2**:M3 配置�?`pipelines/*.yaml` + `validate-pipeline`)、M4 前端 adapter、M5 切换。R2 的运行时强制�?M3,但其测试种子可在 M2 预埋(�?§4)�?
---

## 1. 出口硬标�?(M2 不达不算完成)

### R1 �?门禁校验真实产物,不再只查键存�?【最高优先级�?
- **现状**: `core/gates.py:gate_passes` �?`key not in evidence`;`core/engine.py:submit_evidence` 只把 path 字符串塞进字典。e2e 用不存在的假路径 `f"{phase}-{key}.md"` 即可推到 VERIFIED�?- **目标**: 门禁校验证据**产物本身**——文件存�?+ 内容非空 + 哈希 + 命令证据(测试/构建实际跑过)�?- **port 来源**(设计 §5,逻辑不动只包窄接�?: `skills/e2e-dev-harness/scripts/` 下的 `hash_artifacts`、`command_evidence`(连同其测试一�?port)�?- **验收标准**:
  1. 提交指向**不存在文�?*的证�?�?`gate` / `next` 判定门禁**未过**(当前会误�?�?  2. 提交指向**空文�?*的证�?�?门禁未过�?  3. 测试类证�?`failing_tests`/`passing_tests`)须携带命令证�?命令 + 退出码 + 哈希),伪造无法通过�?  4. **改写 M1 �?e2e 测试**:不能再用假路径跑�?VERIFIED;必须落真�?artifact。这�?R1 是否落地的判据�?  5. `gate` 动词获得 e2e 覆盖(当前�?unit �?`gate_passes`,�?L8)�?- **受影响文�?*: `core/gates.py`、`core/engine.py`(submit_evidence)、新 `adapters/evidence/`(port)、`tests/test_cli_e2e.py`(改写)、新 `tests/test_gate_artifact_validation.py`�?
### R1' �?改�?PLANNED / REVIEWED 两个 worker skill (= L4)

- **现状**: `e2e-harness-planning`、`e2e-harness-review` 仍引�?*�?CLI** `skills/e2e-dev-harness/scripts/e2e_dev_harness.py`、未委派 Superpowers。仅 4 �?minimal-path skill 已改造�?- **目标**: 二者瘦身为委派�?设计 §9 �?:planning �?`superpowers:writing-plans`;review �?`superpowers:requesting-code-review` / `receiving-code-review`。引�?e2e-dev-harness CLI,声明 `expected_outputs`�?- **验收标准**: 扩展 `tests/test_worker_skills_delegate.py` �?MAP/OUTPUTS 覆盖 planning(`plan`)�?review(`review`);断言不再出现�?CLI 路径�?- **受影响文�?*: `skills/e2e-harness-planning/SKILL.md`、`skills/e2e-harness-review/SKILL.md`、`tests/test_worker_skills_delegate.py`�?
---

## 2. M2 功能�?(设计 §14 本体)

| �?| 目标 | 验收标准 |
|---|---|---|
| **tier 缩放** | standard/critical/audited 的门禁集�?tier 增减(设计 §4) | golden tier fixtures 行为对齐;�?tier �?exit_gate 集合可断言 |
| **结构化阶段裁�?* | tier 决定**哪些阶段运行**(§11),被跳阶段从计算出�?spine 移除,`next` 越过、导航渲�?`�?skipped` | minimal �?PLANNED/REVIEWED 已验;新增 standard 全主干、critical �?review fan-out 的裁剪测�?**裁剪�?spine 仍过 I1/I2** |
| **r1/r2/r3 review fan-out** | critical tier �?REVIEWED 阶段�?3 个独�?reviewer,互不 review 自己实现 | 三份独立 review 证据;门禁要求 ≥N �?reviewer 隔离上下�?|
| **port 叶子到窄接口** | scanner / KG 证据 / `task_tier.py` / hashing / memory / runtime-adapter 收敛�?`spawn_worker(packet)->handle` 等窄接口(§5) | 各叶�?*连同其旧测试一�?port**;�?1266 套件不回�?|

---

## 3. 捎带�?(M2 内顺手做)

### L1 �?导航地图补齐 (设计 §10 富信�?
- **�?*: (a) blocked `✗` 独立�?现被阻阶段渲染成 `current`);(b) 每阶段门禁证据摘�?"gate: X �?�?");(c) 距目标门�?"�?N �?);(d) next 动作框在地图�?现为 sibling 字段)�?- **受影响文�?*: `core/navigation.py`、`tests/test_navigation.py`�?
### L2 �?DispatchStatus 失败路径
- **现状**: 5 值死 3(�?DISPATCHED/DONE 被写),�?worker 失败表示�?- **目标**: �?`FAILED` + 重试/blocker 语义;worker 失败�?coordinator 能从导航地图看到阻塞并重派�?- **受影响文�?*: `core/dispatch.py`、`core/engine.py`、新 `submit`/`next` 失败分支、对应测试�?
### 廉价健壮�?(L5-L7,保护 SSOT,建议 M2 第一�?PR 顺手)
- **L5** `run_state.load` �?schema 版本校验:`state["schema"] == SCHEMA` 否则清晰报错(现裸 `json.loads` �?下游莫名 KeyError)�?- **L6** `run_state.save` �?*原子�?*(temp + `os.replace`),避免崩在写一半截断唯一 SSOT(现直�?`write_text`)�?- **L7** `cli/main.py:main()` �?try/except,非法 pipeline/phase 等错误也**�?JSON**(�?`pipeline.active_phase_names` 抛裸 KeyError �?未捕�?traceback + �?JSON stdout,破坏"每命令出 JSON"契约)�?- **受影响文�?*: `core/run_state.py`、`cli/main.py`、`tests/test_run_state.py`�?
---

## 4. M2 内为 M3/R2 预埋的种�?(不实�?只留测试钩子)

- **R2(I2 运行时强�?正式�?M3**(`validate-pipeline` 命令 + start/next 早期守卫)。但 M2 引入�?tier/裁剪�?spine 不再唯一,**裁剪后流水线�?I2 校验**应在 M2 就有单测覆盖(对每个内�?tier �?`gate_closure_ok`),避免 M3 才发现某 tier 跳了仍被后续门禁需要的阶段�?- 验收: 新增 `test_all_builtin_tiers_gate_closed`,�?standard/critical/audited 各断言 `gate_closure_ok` 为真�?
---

## 5. 已确认无需返工的点 (审计正面结论,勿重�?

- M1 终止�?I1)是结构性的、真实成�?e2e �? 步终止�?- `status` �?`next` 已同源渲�?�?`navigation.navigation_map`),设计 §10 "机读/人读同源"已兑现�?- 指针�?packet(`{role, skill, context_paths[], expected_outputs[]}`)与设�?§9 完全一致�?- SSOT �?run-state 已落�?�?facade-over-legacy�?
---

## 6. 续接指引

�?session:读设�?§14/§4/§5/§11 + 本输�?+ HANDOFF "M1 端到端复核结�?。早期跑 `npx gitnexus analyze`(索引未覆�?e2e-dev-harness)。port 叶子改旧 symbol 前按 CLAUDE.md �?`gitnexus_impact`。然后进 `superpowers:writing-plans` �?M2 计划,**R1 �?R1'(L4)为出口硬标准**,先写红测(R1 �?假路径不能过�?即第一�?。成�?实现�?subagent 批量派发、测试做门禁、最后一次性总评�?上轮每任务两阶段独立 review �?$170+)�?