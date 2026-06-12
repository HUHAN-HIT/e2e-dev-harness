# E2E Dev Harness — 门禁/状态机审计与修复 · 交接文档

- 生成：2026-06-11
- 仓库：`C:\Users\14907\Documents\Codex\2026-05-23\skill-skill-superpowers-skill-tdd-graphify`
- 分支：`fix/harness-utf8-tier-verification-gate`
- 代码根：`skills/e2e-dev-harness/scripts/e2e_harness/`
- 测试：`cd skills/e2e-dev-harness && PYTHONUTF8=1 python -m pytest -q`

> 新 session：读完本文档可直接从第 4 节执行 Task 1–5。

---

## 0. 关键约束（必读）

### 环境/操作约束
- 本会话写文件用 Write/Edit 工具时**需要用户逐次审批**；批准后才真正落盘（之前一连串"写入失败"实为未批准的假象，与文件系统/GitNexus/heredoc 无关）。
- Bash 在自动允许列表里，可靠；但 **heredoc(`cat << EOF`) 在此 Bash 工具下失效**，写文件勿用 heredoc。
- 写完一个文件后，可用 Bash `cat`/`ls` 复核确已落盘。

### 项目约束（CLAUDE.md）
- 编辑符号前：`gitnexus_impact({target, direction:"upstream", repo:"e2e-dev-workflow"})`（多 repo，必须带 repo；MCP 超时则用静态调用图）。
- 提交前：`gitnexus_detect_changes()`；HIGH/CRITICAL 风险先告知。
- TDD：每个 Task 先写失败测试 → 跑红 → 最小实现 → 跑绿 → 全量回归 → 提交。

---

## 1. 工作树状态（已核查，未被污染）
- 真实改动（prior session 合法，保留）：`validate.py`(+16, test_substance 入 STRUCTURED_KEYS、validator 加 repo_root)、`lifecycle.py`(+2, IMPLEMENTED 增 test_substance)、`runtime/__init__.py`、`cli/commands/dispatch.py`。
- `gates.py`/`navigation.py`/`cli/main.py` 显示 M 但 `git diff` 为空（仅 stat-dirty，无需还原）。

---

## 2. 审计结论：7 个问题（均已运行时复现）
- G1【高】`adapters/hooks/phase_guard.py:21,25-54`：只识别 Edit/Write 的 file_path 和 shell 重定向；`sed -i`/`cp`/`mv`/`python -c …write`/`patch`/`git apply` 写代码不被拦 → 非 IMPLEMENTED 阶段绕过 phase-lock。
- G2【高】`phase_guard.py:70-98`：`cp forged docs/agent-runs/<id>/run-state.json` 不触发任何检查 → 可覆盖 SSOT。
- G3【高】`adapters/evidence/validate.py:33,92-98` 经 `navigation.py:36`/`status.py`：只读 status/navigation_map 会真实重跑 verification 命令（副作用、非幂等、任意命令执行面）。
- G4【中】`adapters/tier/classify.py:16-24`：缺安全域(auth/login/password/token/permission/oauth)与部分支付词(billing/invoice/transfer/withdraw) → 落 minimal(跳过审查)。
- G5【低】`cli/main.py:43`+`engine.py:30`：submit done 漏 --key 会以 None 为键写 evidence（本次不修，记录）。
- S1【中】`core/engine.py:15-32`：REVIEWED 多评审共享 phase record；failed 后他人 done 会 pop blocker + dispatch=done，失败信号被抹除。
- S2【中】`engine.py:17-22`+`gates.py:8-20`：failed 不清 evidence，gate_passes 不看 dispatch==FAILED → 越过失败阶段。
- S3【中】`run_state.py:33`(硬编码 CREATED)+`pipeline_validate.py`(未校验首阶段)：custom pipeline 无 CREATED → 首次 evaluate 抛 KeyError('CREATED')；`navigation.py:13` 又静默当 spine[0]。

---

## 3. 已批准设计决策
- G1/G2：白名单 + SSOT 硬拦；威胁模型=防无意绕过（注释写明）。
- G4：补词 + auto 基线 floor=standard（显式 --tier minimal 仍可选）。
- S1/S2：新增 per-key 失败字段，向后兼容 v1。

---

## 4. Task 1–5：精确改动（按序执行，TDD）

### Task 1 — G3：门禁评估只读路径无副作用
- `adapters/evidence/validate.py`：`def validate_evidence(repo_root, key, entry):` → `(..., *, replay: bool = True):`；replay 段 `if key in REPLAY_KEYS:` → `if key in REPLAY_KEYS and replay:`；段内局部变量 `replay` 改名 `replayed`，`actual = replayed.get("exit_code")`。
- `core/gates.py`：`def gate_passes(phase, phase_record, repo_root=None):` → `(..., *, replay: bool = True):`；调用 `validate.validate_evidence(repo_root, k, evidence[k])` → `(..., replay=replay)`。
- `core/navigation.py`：`_phase_status` 与 `navigation_map` 两处 `gates.gate_passes(...)` 加 `, replay=False`。
- `core/engine.py`：`evaluate` 内 `gates.gate_passes(phase, rec, repo_root)` 加 `, replay=True`。
- `cli/commands/gate.py`：不改（默认 True）。
- 测试 `tests/test_gate_replay_isolation.py`：genuine exit-0 command-evidence(命令写 sentinel)，记录后清 sentinel；replay=False 通过且不重建；replay=True 通过且重建；navigation_map(spine,state,repo) 不重建。

### Task 2 — G1/G2：phase_guard 写入识别 + SSOT 硬拦
- `adapters/hooks/phase_guard.py`：① 命令含 `run-state.json` token 即无条件 deny；② 写入命令白名单 cp/mv/sed -i/tee/dd of=/install/patch/git apply/python -c(写)，提取路径命中 is_code_path 即 phase-lock；无法解析的写入命令在非 code-write 阶段保守 deny；注释写明威胁模型。
- 测试 扩展 `tests/test_phase_guard.py`：RED 下 sed -i/cp/mv/python -c 写 .py → deny；cp 到 run-state.json → deny；保留既有绿用例。

### Task 3 — G4：tier 补词 + 基线 floor
- `adapters/tier/classify.py`：新增 `_SECURITY`(auth/login/password/token/credential/permission/oauth/session/鉴权/认证/权限/密码/凭证/登录)→critical；扩展 `_PAYMENT`(billing/invoice/charge/transfer/withdraw/deposit/wire)。`classify_tier`：auto 且文本为 minimal 时提升 standard。
- 测试 更新 `tests/test_tier_classify.py`：原 minimal 用例改 standard；login/password、oauth token、wire transfer/billing invoice → critical。

### Task 4 — S1/S2：per-key 失败 + failed 门禁
- `core/engine.py` submit_evidence：failed → `rec.setdefault("failures", {})[key or "_phase"] = reason`（不覆盖 dispatch/blocker）；done → 记录 evidence 后 `rec.get("failures", {}).pop(key, None)`。
- `cli/main.py`+`cli/commands/submit.py`：允许 `--status failed` 带 `--key`。
- `core/gates.py` gate_passes：通过前查 `failures` 非空则不过，missing 加 `failed:<key>`。
- 测试 新建 `tests/test_review_failure_isolation.py`：critical REVIEWED done(r1_review)→failed --key r2_review→done(r3_review)；断言 r2 failure 仍在、gate_passes False(含 failed:r2_review)。

### Task 5 — S3：pipeline 强制以 CREATED 开头
- `core/pipeline_validate.py` validate_spec：增加 `spine[0].name == "CREATED"` 校验，否则 errors 加 "spine must start at CREATED phase"。
- 测试 扩展 `tests/test_pipeline_validate.py`：无 CREATED 的 spec → validate_spec 返回 (False, 含该错误)。

---

## 5. 复现要点（验证修复前后）
独立 Python 脚本(Write 工具写仓库根)import 真实模块逐项断言：
- G1：`phase_guard.decide(hook("Bash", command="sed -i ... x.py"), repo, sp)` RED 阶段 → 修前 allow / 修后 deny。
- G2：`cp ... run-state.json` → 修前 allow / 修后 deny。
- G3：构造 verification 证据，`navigation.navigation_map(..., repo)` → 修前 sentinel 重建 / 修后不重建。
- G4：`classify.classify_tier("add user login with password")` → 修前 minimal / 修后 standard|critical。
- S1：`submit_evidence` done→failed→done → 修前 blocker 被抹除 / 修后保留。
- S2：done(写evidence)→failed，`gates.gate_passes` → 修前 True / 修后 False。
- S3：custom pipeline 无 CREATED → `pipeline_validate.validate_spec` → 修前 (True) / 修后 (False, 含错误)。

---

## 6. 完成标准
- Task 1–5 各自红→绿；全量 `pytest` 通过、无回归；
- 每改动用 `gitnexus_detect_changes()` 确认范围；
- 全部完成后整体 diff 自审，在 `fix/harness-utf8-tier-verification-gate`（或新分支）提交。
</parameter>
</invoke>
