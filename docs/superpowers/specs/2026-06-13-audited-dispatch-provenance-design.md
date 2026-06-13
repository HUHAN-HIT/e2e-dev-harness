# audited `agent_team_dispatch` 身份对账（dispatch-invocation provenance）

- 日期：2026-06-13
- 分支：chore/f4-f6-followups
- 范围：仅 audited tier 的 `agent_team_dispatch` gate key（选项 1）
- 状态：设计待评审

## 1. 背景与缺陷

e2e-dev-harness 是纯控制面：gate 只看声明式 `exit_gate` 的证据 key 是否存在且通过校验
（[gates.py:8-37](../../../skills/e2e-dev-harness/scripts/e2e_harness/core/gates.py:8)）。`dispatch` 命令是发射器，
不是 gate 前置；这是 [SKILL.md:48,109](../../../skills/e2e-dev-harness/SKILL.md:109) 明写的设计——对 standard/minimal/critical 成立且正确。

唯一例外是 **audited** tier：它把 `agent_team_dispatch` 列为 VERIFIED 的 gate key
（[audited.yaml:13-14](../../../skills/e2e-dev-harness/pipelines/audited.yaml:13)），本意是把"经控制面真实派发"当成反伪造证据，
对标 F5 `audit_replay`（claim 必须由真实命令证据背书）。

但现状只做了**形状校验**：`validate_dispatch_invocation` 仅检查 schema / phase /
descriptors-or-block / team_plan_path 指向一个有非空 workers 的文件
（[dispatch_invocation.py:20-45](../../../skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/dispatch_invocation.py:20)）。
它**不验证该 artifact 是否真由 `dispatch` 命令产出**。证据因此可手搓——
测试 `_make_artifact` 当场伪造 team-plan + invocation 两个文件即可过 gate
（[test_cli_e2e.py:54-70](../../../skills/e2e-dev-harness/tests/test_cli_e2e.py:54)），主 E2E 流程全程不调 `dispatch`
（[test_cli_e2e.py:324-333](../../../skills/e2e-dev-harness/tests/test_cli_e2e.py:324)），漏洞因此不被任何测试拦截。

## 2. 目标（要新增的完整性属性）

audited 的 `agent_team_dispatch` 从「**形状对 = 过**」收紧为「**字节就是控制面 `dispatch` 产出的那一份才过**」：
worker 提交的 dispatch-invocation 的 sha256，必须命中 `dispatch` 命令在 run-state 里留下的溯源记录，否则拒。
手搓同形状 JSON 不再能过 audited VERIFIED。

**锚点选择**：身份对账（path + sha256 匹配 dispatch 产物），而非"仅 DISPATCHED 标记"或"仅位置"。
理由：只有字节身份对账能做到与 F5 同级的"手搓不过"。

## 3. 非目标（显式排除）

- 不把 `dispatch` 升成全 tier 硬前置；不改 standard/critical 的 next→submit 协议。
- 不改 `submit_evidence` 直接置 `dispatch=DONE` 的既有行为（对非 audited 是设计行为，无完整性损失）。
- 不为 module-band 的 base phase 引入 `agent_team_dispatch` gate key（当前无此需求）；但 provenance 记录
  的写法须为未来 fanout 留一致性（见 §4.1 约束 A）。

## 4. 设计

### 4.1 改动一：dispatch 时落溯源（[dispatch.py](../../../skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py)）

phase record 新增**持久字段** `dispatch_invocations: list[{path, sha256}]`。
`submit_evidence` 只做单字段读写、从不整体重置 record（[engine.py:15-59](../../../skills/e2e-dev-harness/scripts/e2e_harness/core/engine.py:15)），
故该字段不会被后续 submit 清掉。

**写入点**：在写完**最终** invocation 文件之后计算 `sha256_file(invocation_path)`，
然后把 `{path, sha256}` **折进现有 `_mark_dispatched` 的同一个循环**
（[dispatch.py:142-156](../../../skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py:142)）：

- **约束 A（采纳）**：`_mark_dispatched` 的 band 分支按 `frontier_phase_names` 给**整批** phase record
  标 dispatched；provenance 必须 append 到**同一批** record，而不是 `current_phase`
  （band 模式下它只是派生领头游标，[engine.py:270-271](../../../skills/e2e-dev-harness/scripts/e2e_harness/core/engine.py:270)）。
  把"标记态"和"溯源"在同一循环里同生同灭，永不漂移。audited VERIFIED 走 else 单 phase 分支，自然只写一条。
- **auto-spawn 分支**：invocation 在 [dispatch.py:116](../../../skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py:116) 写定；
  在 `_mark_dispatched` 的 mutate 内 append provenance（同一次 `run_state.mutate`）。
- **manual 分支（exit 3）**：当前在 [dispatch.py:129-137](../../../skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py:129)
  追加 block 后重写 invocation 并直接 `return 3`，**不碰 run-state**。新增一次 `run_state.mutate` 把含 block 的
  invocation 的 `{path, sha256}` 落进当前阶段记录，但**不**标记 DISPATCHED——与"manual block 容忍、但不自封派发成功"的既有语义一致。
  sha 在 block 重写之后计算。

### 4.2 改动二：身份对账校验（[validate.py](../../../skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/validate.py) + [gates.py](../../../skills/e2e-dev-harness/scripts/e2e_harness/core/gates.py)）

- `validate_evidence(repo_root, key, entry, *, skip_replay=False, phase_record=None)` 新增可选 kwarg；
  现有位置调用与单测（不传 `phase_record`）字节兼容。
- `gate_passes` 在 [gates.py:27](../../../skills/e2e-dev-harness/scripts/e2e_harness/core/gates.py:27) 把已在手的 `rec`
  作为 `phase_record=rec` 传下去；其它 key 完全无感。
- `validate_dispatch_invocation` **保持纯形状校验不动**；身份检查放在 `validate_evidence`——`entry` 的 sha256
  就在这一层（[validate.py:135](../../../skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/validate.py:135)）。
- 仅当 `base_key(key) == "agent_team_dispatch"`：形状校验通过后，再要求
  `entry["sha256"] ∈ {p["sha256"] for p in (phase_record or {}).get("dispatch_invocations", [])}`：
  - 无 `phase_record` / 无溯源记录 → 拒，reason `dispatch-provenance-missing`（**strict**：没真跑过 dispatch 不过）。
  - sha 不命中 → 拒，reason `dispatch-provenance-mismatch`。
- 只按 **sha256** 对账（path 仅作诊断），故 worker 复制同字节文件到别处再提交也能过——它仍是控制面产物，无安全损失。
- navigation 走同一条 `all_gates_pass`→`gate_passes`，读同一份 run-state，显示与门禁一致；
  provenance 是纯文件/状态读，无 replay 式 side-effect，故 `skip_replay` 两路一致、无分歧。

### 4.3 改动三（可选，约束 B）：把具体 reason 透到 CLI

> 本节是整份设计中**唯一可选**项。砍掉它不影响堵洞，只影响可观测性；评审时若不要，删本节即可。

现状 `gate_passes` 丢弃 `_reason`、只把 key 塞进 `missing`（[gates.py:27](../../../skills/e2e-dev-harness/scripts/e2e_harness/core/gates.py:27)），
所以 CLI `gate`/`next` 的 `missing_evidence` 永远只显示 `["agent_team_dispatch"]`，看不出是 missing 还是 mismatch。
本修复的意义就是逼出真实 dispatch；artifact 在场却只报"缺 key"会把运维误导成"文件没了"。

**附加、不破坏既有形状**的做法：
- `gate_passes` 返回值 `(ok, missing)` → `(ok, missing, detail)`，`detail: dict[str, str]` 为 `{key: reason}`。
- `missing` 仍是纯 key 列表，故 [test_cli_e2e.py:350](../../../skills/e2e-dev-harness/tests/test_cli_e2e.py:350) 等
  `missing_evidence == [...]` 断言不动。
- `all_gates_pass` / `navigation` / `gate.py` 透传 `detail` 为输出里**新增**的 `missing_detail` 字段。
- 直接调用方（仅 `all_gates_pass` 一处，impact=LOW）随签名同步。

## 5. 测试计划（TDD，先红）

1. **red-lock（补上原分析说缺的那道防线）**：audited 跑到 VERIFIED 时提交一份**手搓**（未经 dispatch）的
   `agent_team_dispatch` artifact，断言 run **到不了** VERIFIED（`you_are_here != "VERIFIED"` 且 `gate` 不过）。
   这条专门钉死本缺陷，是首要红测。
2. **改 `test_cli_e2e.py` audited drive**（[test_cli_e2e.py:307-350](../../../skills/e2e-dev-harness/tests/test_cli_e2e.py:307)）：
   循环里到 VERIFIED 时先调 `dispatch`，取返回包的 `dispatch_invocation_path` 作为 `agent_team_dispatch` 证据提交；
   `verification`/`audit_replay` 仍走 `_make_artifact`。`_make_artifact` 删除手搓 `agent_team_dispatch` 分支。
3. **改 `test_agent_team_dispatch_evidence.py`**（[test_agent_team_dispatch_evidence.py](../../../skills/e2e-dev-harness/tests/test_agent_team_dispatch_evidence.py)）：
   表达新契约——传匹配 `phase_record` 溯源→过；无溯源→`dispatch-provenance-missing`；sha 不符→`dispatch-provenance-mismatch`；
   manual block + 匹配溯源→过。
4. **新增 dispatch 单测**：auto-spawn 后被标 dispatched 的每个 phase record 都含正确 sha 的 `dispatch_invocations`；
   manual runtime 同样落溯源（带 block）且**不**标 DISPATCHED。
5.（若纳入 §4.3）**gate detail 单测**：provenance 失败时 `missing_detail["agent_team_dispatch"]` 为对应 reason，
   而 `missing_evidence` 仍为 `["agent_team_dispatch"]`。

## 6. Blast radius / 风险：LOW

- `gate_passes` 上游仅 `all_gates_pass`（GitNexus impact：direct=1, risk=LOW）。
- `validate_evidence` 无破坏性下游（impact：risk=LOW）。
- 非 audited tier 不含 `agent_team_dispatch` gate key，零影响。
- 无 HIGH/CRITICAL。落地后提交前跑 `detect_changes` 复核仅触及预期符号。

## 7. 已核实前提

- audited 的 **VERIFIED 可派发**：`worker_skill="e2e-harness-completion"`
  （[lifecycle.py:25](../../../skills/e2e-dev-harness/scripts/e2e_harness/core/lifecycle.py:25)）；audited.yaml 只覆盖
  produces/exit_gate，未覆盖 worker_skill，故 `dispatch` 在 audited VERIFIED 返回 0，"VERIFIED 前先 dispatch"成立。
- `submit_evidence` 不整体重置 phase record，故 sibling `dispatch_invocations` 不被清。

## 8. 开放问题

- 无（§4.3 是显式可选项，不是开放问题）。
