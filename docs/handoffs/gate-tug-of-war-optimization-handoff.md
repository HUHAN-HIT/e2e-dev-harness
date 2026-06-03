# Handoff: 门禁/agent 拉扯优化（P2/P0 已做，P1/P0-扩展待续）

> 会话日期 2026-06-03。主题：减少"门禁与 agent 反复拉扯导致效率降低、占用上下文"。
> 注：与 `harness-context-optimization.md`（coordinator slice 爆炸）是不同工作线。

## 已完成（保留生效，未提交）

### P2 — GitNexus hook 会话级去重 ✅
- 文件：`~/.claude/hooks/gitnexus/gitnexus-hook.cjs`（全局 hook，影响所有项目）
- 改动：新增 `os` require + `augmentDedupState()` + `tersePointer()`，接入 `handlePreToolUse`。
- 效果：每 (会话,仓库) 首次 grep/rg 给完整 MCP 指引，之后只给一行。已活体验证。
- 回退：撤销该文件 3 处编辑（逻辑全在两个新函数内）。

### P0 — harness 单次预检聚合器 ✅
- 文件：`skills/e2e-dev-harness/scripts/e2e_dev_harness.py`
  - `_preflight_checks()`（~:984）：lifecycle→门禁映射，复用现有纯 blocker 函数。
  - `aggregate_preflight_blockers(repo, run_state_path)`（~:1007）：一次跑完所有适用门禁，返回有序 `blockers[]` + `next_single_action`。
  - `preflight(args)` 命令 + argparse 注册（`preflight` 子命令）+ main 分发。
- 测试：`tests/test_preflight_aggregator.py`（3 用例，全绿）。
- 验证：全量 887 测试通过；CLI 冒烟 `preflight --state <CREATED-state>` → exit 2 / gate=clarification。
- 当前仅覆盖 2 门禁：clarification、service_design。

## 待续

### 任务 #3 — P0 扩展（低风险，建议先做）
把 `_preflight_checks()` 从 2 个门禁扩到更多 lifecycle 门禁。
- 复用：`agent_scheduler.dispatch_completion_blockers_for_phases`（`agent_scheduler.py:179`）等现成纯函数。
- 聚合器主循环无需改；每加一门禁加一红测（参照 `tests/test_preflight_aggregator.py`）。
- 注意：blocker 函数需 `(repo, run_state_path)->list[str]` 形态，否则在 `_preflight_checks` 里包一层适配。

### 任务 #4 — P1 harness 指引去重（中风险）
`phase_guard.py:guidance_for_lifecycle()`（~:422）每次 block 全量重发 forbidden_actions/exploration_policy/clarification_interaction，无去重。
- 方案：run-state 记 `acknowledged_guidance` 集合，重复 block 只发短码+引用。
- 必须 TDD + 全量回归（phase_guard 是 1715 行 hook 关键文件）。

### 任务 #5 — ECC fact-force 粒度调优（需用户拍板）
fact-force 按 (工具×文件) 触发，单会话被拦 5+ 次，是上下文/成本最大干扰源（非本仓库代码，属 ECC 插件全局门禁）。
- 选项：`ECC_DISABLED_HOOKS=pre:edit-write:gateguard-fact-force` 等，或对只读/可逆操作豁免。
- 改它会全局削弱一个安全 guard，需用户决定。

## 恢复步骤
1. `cd` 到本仓库；`git status` 确认 P0 改动仍在工作树（e2e_dev_harness.py + tests/test_preflight_aggregator.py）。P2 在 `~/.claude/hooks/gitnexus/gitnexus-hook.cjs`。
2. 跑 `python -m pytest tests/test_preflight_aggregator.py -q` 确认绿。
3. 从任务 #3 起按 TDD 继续。
4. 动 harness 符号前按 CLAUDE.md 跑 `gitnexus_impact`；提交前跑 `gitnexus_detect_changes`。

## 成本备注
本会话结束于 ~$61.84，大量消耗在 fact-force 反复打断——即本次要优化的问题本身。
