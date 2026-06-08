# U7 — v2 Hook 强制层 (Hook Enforcement) 设计

**Date:** 2026-06-08
**Status:** Approved (brainstorm)
**Design source:** [2026-06-07-harness-v2-redesign-design.md](2026-06-07-harness-v2-redesign-design.md) (§2 编排核心, §4 声明式门禁, §5 取舍表, §15 不变量)
**Roadmap:** [2026-06-07-harness-v2-remaining-work-roadmap.md](../plans/2026-06-07-harness-v2-remaining-work-roadmap.md)

---

## 0. 缘起 — 为什么新增 U7

U6 (M5 switchover) 的 parity 审计发现一处 **design 真空**:

- legacy `skills/e2e-dev-harness/` 通过 `install_hooks.py` 安装 **`phase_guard.py` (PreToolUse hook)** 与 **`harness_stop_guard.py` (Stop hook)** 到 `.claude/settings.json`(及 codex/gemini/opencode 对应)。
- `phase_guard.py` 在**工具调用层硬阻止**越界:拦截不符合 phase lock 的 code write(注释明确 "PostToolUse is audit-only and cannot block writes" — 必须 PreToolUse 才能 block),并强制 `--require-active-run-for-read` / `--require-session-checkpoint`。
- **legacy 的 TDD / phase 纪律是靠这些 hook 在工具层强制的,不是靠 skill 文本自觉。**
- redesign design doc 对此**完全沉默**:§0.1 决策 (D1–D8) 无一涉及;§5 取舍表未 port/drop;§16 YAGNI 未记录。
- v2 当前**没有 hook 实现**,只有 CLI 状态机 (`start/next/gate`)。走神的 worker 可越过 RED 直接写实现,CLI 无法在工具层拦截。

结论:工具层 hook 强制是 harness 的核心能力,**不是 v1 遗留垃圾**。直接砸掉 = 真实功能回归,违反 roadmap "old harness retired with no functional regression"。因此:

- **新增 U7** = 给 v2 造对应的 hook 强制层 (net-new build)。
- **U6 删 legacy gated on U7**(v2 有 hook 才能删带 hook 的 legacy)。

重排后的单元依赖:

```
U1–U5  done
U7  v2 hook 强制层 (本设计)  ← net-new,brainstorm→plan→TDD
U6  cutover:入口切换 + parity 审计 + 三件文档 + 删 legacy
     └─ 删 legacy:gated on U7
```

---

## 1. 目标

给 v2 一个工具层 **PreToolUse 强制**:非 implementation phase 阻止 code write,补回 legacy `phase_guard` 的核心纪律,使 U6 删 legacy 不丢能力。

**范围(已与用户确认):**
- 实现路线:**混合** — 复用 legacy phase_guard 的路径无关逻辑,状态判定改为薄壳读 v2 run-state。
- runtime:**claude + opencode** 两种。
- 强制粒度:**核心 phase lock 优先** + Stop guard;`require-active-run` / `session-checkpoint` 显式 deferred。

---

## 2. 架构原则

- **薄壳 + 复用**:不内嵌状态机镜像。状态判定委托 v2 lifecycle/run-state (D1 重建核心 + 薄适配)。legacy `phase_guard.py` 2288 行里有一份完整的 lifecycle 状态机镜像 (`guidance_for_lifecycle` 硬编码各 phase allowed_actions) — v2 **不重复**它,因为 v2 lifecycle 已是单一真相源。
- **声明式**:phase 的 code-write 权限在 pipeline spec 声明,hook 只读(呼应 §4 声明式门禁)。
- **backend-first + YAGNI**:只装 claude + opencode;只做核心 phase lock + Stop。
- **单一真相源**:`can_write_code` 判定同时被 hook 与 CLI 复用,不产生第二份 phase 知识。

---

## 3. 组件

### 3.1 `can_write_code(state) -> bool` — 声明式判定 (v2 `core/lifecycle`)

读 `run-state.current_phase` + `pipeline_spec`,判断当前 phase 是否允许 code write。

**设计决策:pipeline spec 的 phase entry 新增显式字段 `allows_code_write` (bool)**,而非靠 `produces` 内容脆弱推断。

- 显式声明符合 §4(门禁声明式 + 随 tier 缩放),且与 U5 已建立的 phase-entry 字段模式 (`worker_role/worker_skill/produces/exit_gate`) 一致。
- 内建 pipeline (minimal/standard/critical/audited):实现 (GREEN/IMPLEMENT 类) phase 标 `allows_code_write: true`,其余 phase 缺省 false。
- 字段为**可选**:缺省 false(保守 — 未声明的 phase 不允许写)。这保证向后兼容:既有 run-state 无此字段时,只有显式标注的 phase 放行。
- bare-string phase 视为 `allows_code_write: false`(与 §U5 merge_overrides 的 bare-string 提升语义一致)。

判定:`current_phase` 对应的 phase entry 的 `allows_code_write` 为 true → 允许。

### 3.2 `phase_guard_v2.py` — 薄 PreToolUse hook

输入:Claude Code hook 协议的 `--hook-input`(工具名 + 参数:文件路径 / Bash 命令)。

流程:
1. 解析工具调用,提取目标路径 / 命令。
2. **复用 legacy 路径逻辑**(从 `phase_guard.py` port 路径无关部分):
   - `is_code_path` — 识别 code 文件(源码扩展名,排除 docs/控制文件)。
   - 控制文件直写检测 — 阻止 Edit/Write/Bash-重定向直改 `run-state.json`(防绕过状态机)。注意 v2 无 `.phase-lock` 文件,控制文件集收敛为 `run-state.json`。
   - hook-config 路径校验 — 阻止直改 `.claude/settings.json` 绕过 hook。
3. 非 code 路径 → allow(放行 Read/Grep/docs 等)。
4. code 路径 → 读 run-state → `can_write_code`:
   - true → allow。
   - false → **deny**(hook 协议的 block 输出)+ v2 guidance(当前 phase、下一步该跑哪个 verb,如 `next` / `gate`)。

输出:遵循 Claude Code PreToolUse hook 的 deny 协议(阻止工具执行 + 返回理由)。

### 3.3 `stop_guard_v2.py` — Stop hook

有 active run 且 `current_phase != VERIFIED` 时,Stop 返回提示(继续推进而非中断)。薄版 `harness_stop_guard`,不内嵌复杂状态判断 — 仅读 run-state.current_phase。

### 3.4 hook 安装 (installer)

接 U6 Stage 2 — U6 的 installer **不再砸 hook**,改为安装 v2 hook:
- **claude**:`.claude/settings.json` 注册 PreToolUse(`phase_guard_v2`)+ Stop(`stop_guard_v2`),使用安装后脚本的**绝对路径**(不用 repo-relative)。
- **opencode**:`plugin.js` 调 `phase_guard_v2 --hook-input`。
- example config 模板随 v2 skill 提供(`hooks/` 目录)。

---

## 4. 复用 vs 新建(承 §5 取舍精神)

**复用**(从 `phase_guard.py` port 路径无关逻辑,逻辑不动只包薄接口):
- code-path 识别正则 / 扩展名集。
- 控制文件直写检测(收敛到 `run-state.json`)。
- hook-config 路径校验。

**新建 (TDD)**:
- `can_write_code` + pipeline spec `allows_code_write` 字段。
- `phase_guard_v2.py` 薄壳。
- `stop_guard_v2.py`。
- v2 hook example configs (claude settings + opencode plugin)。
- installer 装 v2 hook(落地在 U6 Stage 2)。

**不搬**:2288 行的 lifecycle 状态机镜像(`guidance_for_lifecycle` 等)— v2 lifecycle 已有。

---

## 5. 测试策略

因子 agent dispatch 在本环境损坏(派发解析到不可访问的 glm-4.7),U7 走**内联落地 + 事后 `/code-review`**,以 TDD 红→绿 + 全套测试 + e2e 为证据。

- `can_write_code`:各 phase 红/绿用例(CREATED/RED/clarify 类拒;GREEN/IMPLEMENT 准;缺字段保守拒;bare-string 拒)。
- `phase_guard_v2`:错 phase 的 code write 被 deny;对 phase allow;非 code 路径(Read/docs)放行;直写 `run-state.json` 被 deny;直改 `.claude/settings.json` 被 deny;deny 输出含 v2 guidance。
- `stop_guard_v2`:未 VERIFIED + active run 阻止;已 VERIFIED 放行;无 active run 放行。
- installer:claude settings 注册正确(PreToolUse+Stop,绝对路径);opencode plugin 正确调用。
- e2e:`start → 越界 code write 被 hook 拦 → 走 gate → 进 GREEN → 同一写放行`。

---

## 6. 与 U6 的衔接

- U7 完成后:
  - U6 Stage 2:installer 装 v2 hook(取代原"砸 hook"决策)。
  - U6 Stage 4:删 legacy 解锁。
  - U6 parity 审计:hook 能力从 "deferred to U7" 改为 "covered by U7"。
- roadmap 需补一行 U7,并把 U6 的"删 legacy"标注 gated on U7。

---

## 7. YAGNI(本轮 deferred)

- `--require-active-run-for-read`(探索须在 active run 内开始)。
- `--require-session-checkpoint`(resumed session 写码前 reload run-state)。
- codex / gemini runtime hook。
- 冲突事实强制 (`conflicting_fact_force_hook`) 等 legacy 高级 guard。

记录于此,真实流程证明需要时再加回(承 §16 YAGNI 精神:显式延后,非静默删除)。

---

## 8. 受影响文件(预估,plan 期细化)

**新建:**
- `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/hooks/phase_guard_v2.py`(薄壳;路径逻辑可单列模块复用)
- `.../adapters/hooks/stop_guard_v2.py`
- `.../adapters/hooks/paths.py`(从 legacy port 的路径无关逻辑)
- `skills/e2e-dev-harness-v2/hooks/claude-code-settings.example.json`
- `skills/e2e-dev-harness-v2/hooks/opencode-plugin.example.js`
- 对应 `tests/test_*.py`

**修改:**
- `.../core/lifecycle.py`(加 `can_write_code`)
- pipeline spec 内建文件(加 `allows_code_write` 标注)
- `.../core/pipeline_validate.py`(接受新可选字段)
- U6 期:installer (`lib/*` / `tools/install-e2e-dev-harness.mjs`) 装 v2 hook

**验证:** 改动限于 `skills/e2e-dev-harness-v2/`(installer 部分在 U6);v2 全套测试绿。
