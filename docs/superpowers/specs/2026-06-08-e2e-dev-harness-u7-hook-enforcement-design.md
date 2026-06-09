# U7 �?e2e-dev-harness Hook 强制�?(Hook Enforcement) 设计

**Date:** 2026-06-08
**Status:** Approved (brainstorm)
**Design source:** [2026-06-07-e2e-dev-harness-redesign-design.md](2026-06-07-e2e-dev-harness-redesign-design.md) (§2 编排核心, §4 声明式门�? §5 取舍�? §15 不变�?
**Roadmap:** [2026-06-07-e2e-dev-harness-remaining-work-roadmap.md](../plans/2026-06-07-e2e-dev-harness-remaining-work-roadmap.md)

---

## 0. 缘起 �?为什么新�?U7

U6 (M5 switchover) �?parity 审计发现一�?**design 真空**:

- legacy `skills/e2e-dev-harness/` 通过 `install_hooks.py` 安装 **`phase_guard.py` (PreToolUse hook)** �?**`harness_stop_guard.py` (Stop hook)** �?`.claude/settings.json`(�?codex/gemini/opencode 对应)�?- `phase_guard.py` �?*工具调用层硬阻止**越界:拦截不符�?phase lock �?code write(注释明确 "PostToolUse is audit-only and cannot block writes" �?必须 PreToolUse 才能 block),并强�?`--require-active-run-for-read` / `--require-session-checkpoint`�?- **legacy �?TDD / phase 纪律是靠这些 hook 在工具层强制�?不是�?skill 文本自觉�?*
- redesign design doc 对此**完全沉默**:§0.1 决策 (D1–D8) 无一涉及;§5 取舍表未 port/drop;§16 YAGNI 未记录�?- e2e-dev-harness 当前**没有 hook 实现**,只有 CLI 状态机 (`start/next/gate`)。走神的 worker 可越�?RED 直接写实�?CLI 无法在工具层拦截�?
结论:工具�?hook 强制�?harness 的核心能�?**不是 v1 遗留垃圾**。直接砸�?= 真实功能回归,违反 roadmap "old harness retired with no functional regression"。因�?

- **新增 U7** = �?e2e-dev-harness 造对应的 hook 强制�?(net-new build)�?- **U6 �?legacy gated on U7**(e2e-dev-harness �?hook 才能删带 hook �?legacy)�?
重排后的单元依赖:

```
U1–U5  done
U7  e2e-dev-harness hook 强制�?(本设�?  �?net-new,brainstorm→plan→TDD
U6  cutover:入口切换 + parity 审计 + 三件文档 + �?legacy
     └─ �?legacy:gated on U7
```

---

## 1. 目标

�?e2e-dev-harness 一个工具层 **PreToolUse 强制**:�?implementation phase 阻止 code write,补回 legacy `phase_guard` 的核心纪�?�?U6 �?legacy 不丢能力�?
**范围(已与用户确认):**
- 实现路线:**混合** �?复用 legacy phase_guard 的路径无关逻辑,状态判定改为薄壳读 e2e-dev-harness run-state�?- runtime:**claude + opencode** 两种�?- 强制粒度:**核心 phase lock 优先** + Stop guard;`require-active-run` / `session-checkpoint` 显式 deferred�?
---

## 2. 架构原则

- **薄壳 + 复用**:不内嵌状态机镜像。状态判定委�?e2e-dev-harness lifecycle/run-state (D1 重建核心 + 薄适配)。legacy `phase_guard.py` 2288 行里有一份完整的 lifecycle 状态机镜像 (`guidance_for_lifecycle` 硬编码各 phase allowed_actions) �?e2e-dev-harness **不重�?*�?因为 e2e-dev-harness lifecycle 已是单一真相源�?- **声明�?*:phase �?code-write 权限�?pipeline spec 声明,hook 只读(呼应 §4 声明式门�?�?- **backend-first + YAGNI**:只装 claude + opencode;只做核心 phase lock + Stop�?- **单一真相�?*:`can_write_code` 判定同时�?hook �?CLI 复用,不产生第二份 phase 知识�?
---

## 3. 组件

### 3.1 `can_write_code(state) -> bool` �?声明式判�?(e2e-dev-harness `core/lifecycle`)

�?`run-state.current_phase` + `pipeline_spec`,判断当前 phase 是否允许 code write�?
**设计决策:pipeline spec �?phase entry 新增显式字段 `allows_code_write` (bool)**,而非�?`produces` 内容脆弱推断�?
- 显式声明符合 §4(门禁声明�?+ �?tier 缩放),且与 U5 已建立的 phase-entry 字段模式 (`worker_role/worker_skill/produces/exit_gate`) 一致�?- 内建 pipeline (minimal/standard/critical/audited):实现 (GREEN/IMPLEMENT �? phase �?`allows_code_write: true`,其余 phase 缺省 false�?- 字段�?*可�?*:缺省 false(保守 �?未声明的 phase 不允许写)。这保证向后兼容:既有 run-state 无此字段�?只有显式标注�?phase 放行�?- bare-string phase 视为 `allows_code_write: false`(�?§U5 merge_overrides �?bare-string 提升语义一�?�?
判定:`current_phase` 对应�?phase entry �?`allows_code_write` �?true �?允许�?
### 3.2 `phase_guard.py` �?�?PreToolUse hook

输入:Claude Code hook 协议�?`--hook-input`(工具�?+ 参数:文件路径 / Bash 命令)�?
流程:
1. 解析工具调用,提取目标路径 / 命令�?2. **复用 legacy 路径逻辑**(�?`phase_guard.py` port 路径无关部分):
   - `is_code_path` �?识别 code 文件(源码扩展�?排除 docs/控制文件)�?   - 控制文件直写检�?�?阻止 Edit/Write/Bash-重定向直�?`run-state.json`(防绕过状态机)。注�?e2e-dev-harness �?`.phase-lock` 文件,控制文件集收敛为 `run-state.json`�?   - hook-config 路径校验 �?阻止直改 `.claude/settings.json` 绕过 hook�?3. �?code 路径 �?allow(放行 Read/Grep/docs �?�?4. code 路径 �?�?run-state �?`can_write_code`:
   - true �?allow�?   - false �?**deny**(hook 协议�?block 输出)+ e2e-dev-harness guidance(当前 phase、下一步该跑哪�?verb,�?`next` / `gate`)�?
输出:遵循 Claude Code PreToolUse hook �?deny 协议(阻止工具执行 + 返回理由)�?
### 3.3 `stop_guard.py` �?Stop hook

�?active run �?`current_phase != VERIFIED` �?Stop 返回提示(继续推进而非中断)。薄�?`harness_stop_guard`,不内嵌复杂状态判�?�?仅读 run-state.current_phase�?
### 3.4 hook 安装 (installer)

�?U6 Stage 2 �?U6 �?installer **不再�?hook**,改为安装 e2e-dev-harness hook:
- **claude**:`.claude/settings.json` 注册 PreToolUse(`phase_guard`)+ Stop(`stop_guard`),使用安装后脚本的**绝对路径**(不用 repo-relative)�?- **opencode**:`plugin.js` �?`phase_guard --hook-input`�?- example config 模板�?e2e-dev-harness skill 提供(`hooks/` 目录)�?
---

## 4. 复用 vs 新建(�?§5 取舍精神)

**复用**(�?`phase_guard.py` port 路径无关逻辑,逻辑不动只包薄接�?:
- code-path 识别正则 / 扩展名集�?- 控制文件直写检�?收敛�?`run-state.json`)�?- hook-config 路径校验�?
**新建 (TDD)**:
- `can_write_code` + pipeline spec `allows_code_write` 字段�?- `phase_guard.py` 薄壳�?- `stop_guard.py`�?- e2e-dev-harness hook example configs (claude settings + opencode plugin)�?- installer �?e2e-dev-harness hook(落地�?U6 Stage 2)�?
**不搬**:2288 行的 lifecycle 状态机镜像(`guidance_for_lifecycle` �?�?e2e-dev-harness lifecycle 已有�?
---

## 5. 测试策略

因子 agent dispatch 在本环境损坏(派发解析到不可访问的 glm-4.7),U7 �?*内联落地 + 事后 `/code-review`**,�?TDD 红→�?+ 全套测试 + e2e 为证据�?
- `can_write_code`:�?phase �?绿用�?CREATED/RED/clarify 类拒;GREEN/IMPLEMENT �?缺字段保守拒;bare-string �?�?- `phase_guard`:�?phase �?code write �?deny;�?phase allow;�?code 路径(Read/docs)放行;直写 `run-state.json` �?deny;直改 `.claude/settings.json` �?deny;deny 输出�?e2e-dev-harness guidance�?- `stop_guard`:�?VERIFIED + active run 阻止;�?VERIFIED 放行;�?active run 放行�?- installer:claude settings 注册正确(PreToolUse+Stop,绝对路径);opencode plugin 正确调用�?- e2e:`start �?越界 code write �?hook �?�?�?gate �?�?GREEN �?同一写放行`�?
---

## 6. �?U6 的衔�?
- U7 完成�?
  - U6 Stage 2:installer �?e2e-dev-harness hook(取代�?�?hook"决策)�?  - U6 Stage 4:�?legacy 解锁�?  - U6 parity 审计:hook 能力�?"deferred to U7" 改为 "covered by U7"�?- roadmap 需补一�?U7,并把 U6 �?�?legacy"标注 gated on U7�?
---

## 7. YAGNI(本轮 deferred)

- `--require-active-run-for-read`(探索须在 active run 内开�?�?- `--require-session-checkpoint`(resumed session 写码�?reload run-state)�?- codex / gemini runtime hook�?- 冲突事实强制 (`conflicting_fact_force_hook`) �?legacy 高级 guard�?
记录于此,真实流程证明需要时再加�?�?§16 YAGNI 精神:显式延后,非静默删�?�?
---

## 8. 受影响文�?预估,plan 期细�?

**新建:**
- `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/phase_guard.py`(薄壳;路径逻辑可单列模块复�?
- `.../adapters/hooks/stop_guard.py`
- `.../adapters/hooks/paths.py`(�?legacy port 的路径无关逻辑)
- `skills/e2e-dev-harness/hooks/claude-code-settings.example.json`
- `skills/e2e-dev-harness/hooks/opencode-plugin.example.js`
- 对应 `tests/test_*.py`

**修改:**
- `.../core/lifecycle.py`(�?`can_write_code`)
- pipeline spec 内建文件(�?`allows_code_write` 标注)
- `.../core/pipeline_validate.py`(接受新可选字�?
- U6 �?installer (`lib/*` / `tools/install-e2e-dev-harness.mjs`) �?e2e-dev-harness hook

**验证:** 改动限于 `skills/e2e-dev-harness/`(installer 部分�?U6);e2e-dev-harness 全套测试绿�?