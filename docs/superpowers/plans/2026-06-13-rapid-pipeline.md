# Rapid Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. If a coordinator executes any implementation inline, it still must dispatch a fresh reviewer subagent after each task; self-review by the same code-writing agent is not allowed. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit opt-in `rapid` pipeline that exposes only three user-facing steps: clarification, implementation, and verification.

**Architecture:** Reuse the existing declarative pipeline system instead of adding a new engine path. `CREATED` remains the internal run-state seed, while the active user journey is `CLARIFIED -> IMPLEMENTED -> VERIFIED`; dispatch auto-pairs `rapid` with a bundled `default-rapid` agent-team profile.

**Tech Stack:** Python harness core, YAML pipeline/profile specs, pytest, GitNexus MCP impact analysis.

---

## Scope And Constraints

The rapid flow is an explicit pipeline, not a tier:

```text
Internal spine: CREATED -> CLARIFIED -> IMPLEMENTED -> VERIFIED
User-facing steps: 澄清 -> 实施 -> 校验
CLI selection: e2e-harness start --pipeline rapid ...
```

Do not change `minimal`, `standard`, `critical`, `audited`, or `adversarial` behavior. Do not add `rapid` to tier recommendation options; `recommend_tier()` must continue to return only `minimal`, `standard`, `critical`, and `audited`.

`IMPLEMENTED` remains the only code-write phase. In rapid mode, the implementation worker is responsible for both implementation and test evidence in one worker packet. The existing `IMPLEMENTED` gate still requires `passing_tests` and `test_substance`.

All shell commands in this plan use bash/POSIX-style syntax. Use `\` for line continuation and `$(...)` for command substitution.

## Reviewer Independence Requirement

Reviewer and implementer must be different agents. The agent that writes a task's code, tests, YAML, or docs cannot be the reviewer for that same task.

Mandatory review rule:

```text
After each implementation task with a commit or source/doc change:
1. Capture BASE_SHA and HEAD_SHA.
2. Dispatch a fresh code-reviewer subagent using superpowers:requesting-code-review.
3. Give the reviewer only the plan path, the task number, BASE_SHA, HEAD_SHA, and explicit acceptance criteria.
4. Fix all Critical and Important findings before moving to the next task.
5. Record the reviewer result in the coordinator notes or task handoff.
```

Rapid pipeline skips the harness `REVIEWED` lifecycle phase by design, but that does not permit self-review of this implementation. The independent subagent review is an execution-control requirement for building the rapid pipeline itself.

## Task Classification

Not every task below is a TDD red-green cycle. Use `superpowers:test-driven-development` only for tasks marked `TDD red-green`.

| Task | Classification | Expected first test result |
|---|---|---|
| Task 1: Pipeline YAML | TDD red-green | FAIL before `rapid.yaml`, PASS after it |
| Task 2: Code-Write Guard Coverage | Regression/pinning | PASS after Task 1; pins the code-write contract |
| Task 3: Agent-Team Profile And Dispatch Pairing | TDD red-green | FAIL before `default-rapid`/dispatch pairing, PASS after it |
| Task 4: Tier Recommendation Isolation | Regression/pinning | PASS; pins that `rapid` remains outside tier auto-selection |
| Task 5: Worker Contract Documentation | Doc-only with existing doc tests | PASS; documents rapid evidence semantics |
| Task 6: Coordinator Documentation | Doc-only with doc test | PASS after docs are updated |
| Task 7: CLI Smoke Verification | Integration smoke | PASS after Tasks 1 and 3 |
| Task 8: Independent Reviewer Subagent Gate | Review gate | Reviewer must be a fresh subagent |
| Task 9: Regression Suite And GitNexus Change Check | Final verification | PASS after all previous tasks |

## Task Dependency Graph

Run task workers in this order unless the coordinator has merged the prerequisite commits first:

```text
Task 1 (rapid.yaml)
  ├─> Task 2 (code-write pinning tests)
  ├─> Task 3 (default-rapid dispatch pairing)
  │     └─> Task 7 (CLI smoke)
  └─> Task 4 (tier-isolation pinning test)

Task 5 (implementation worker docs) ─┐
Task 6 (coordinator docs) ───────────┼─> Task 8 (independent review)
Tasks 1-4,7 ─────────────────────────┘

Task 9 must run last.
```

`Task 5` and `Task 6` can run in parallel with `Task 1-4` only if their workers touch disjoint files. `Task 2`, `Task 3`, and `Task 4` must not start before `Task 1` is merged, because they import/load the `rapid` pipeline.

## Files

- Create: `skills/e2e-dev-harness/pipelines/rapid.yaml`
  - Responsibility: Declare the rapid spine and code-write authority.
- Create: `skills/e2e-dev-harness/agent-teams/default-rapid.yaml`
  - Responsibility: Provide the default single-worker role profile for `rapid`.
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py`
  - Responsibility: Auto-select `default-rapid` when `state["pipeline"] == "rapid"`.
- Modify: `skills/e2e-harness-implementation/SKILL.md`
  - Responsibility: Explain the rapid-specific implementation evidence contract.
- Modify: `README.md`
  - Responsibility: Document the rapid pipeline and its opt-in CLI usage.
- Modify: `skills/e2e-dev-harness/SKILL.md`
  - Responsibility: Document rapid in the coordinator-facing canonical skill.
- Modify: `skills/e2e-dev-harness/tests/test_pipeline_validate.py`
  - Responsibility: Prove `rapid` is a valid bundled pipeline.
- Modify: `skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py`
  - Responsibility: Prove `rapid` loads with the intended spine and gate inheritance.
- Modify: `skills/e2e-dev-harness/tests/test_pipeline_tiers.py`
  - Responsibility: Prove `rapid` is isolated from tier behavior.
- Modify: `skills/e2e-dev-harness/tests/test_can_write_code.py`
  - Responsibility: Prove only `IMPLEMENTED` allows code writes in rapid.
- Modify: `skills/e2e-dev-harness/tests/test_agent_team_dispatch.py`
  - Responsibility: Prove dispatch auto-selects `default-rapid`.
- Modify: `skills/e2e-dev-harness/tests/test_tier_recommend.py`
  - Responsibility: Prove tier recommendation options do not include `rapid`.

## Pre-Flight

- [ ] **Step 1: Confirm worktree state**

Run:

```bash
git status --short
```

Expected: note existing user changes and do not revert them.

- [ ] **Step 2: Run required GitNexus impact before editing `_default_profile`**

Run:

```text
gitnexus_impact({
  "repo": "e2e-dev-workflow",
  "target": "_default_profile",
  "file_path": "skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py",
  "kind": "Function",
  "direction": "upstream",
  "maxDepth": 3,
  "includeTests": true
})
```

Expected: LOW risk. Current known blast radius is one direct caller, `_phase_request`, and the `dispatch.run` flow. If GitNexus reports HIGH or CRITICAL, stop and warn the user before editing.

---

### Task 1: Pipeline YAML

**Classification:** TDD red-green.

**Files:**
- Create: `skills/e2e-dev-harness/pipelines/rapid.yaml`
- Test: `skills/e2e-dev-harness/tests/test_pipeline_validate.py`
- Test: `skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py`
- Test: `skills/e2e-dev-harness/tests/test_pipeline_tiers.py`

- [ ] **Step 1: Write failing validation test**

Append this test to `skills/e2e-dev-harness/tests/test_pipeline_validate.py`:

```python
def test_rapid_builtin_spec_is_valid():
    from e2e_harness import pipeline

    ok, errors = pv.validate_spec(pipeline.load_spec("rapid"))

    assert ok is True, errors
```

- [ ] **Step 2: Write failing spine-load test**

Append this test to `skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py`:

```python
def test_rapid_loads_three_user_facing_steps():
    spine = pipeline.build_spine("rapid")

    assert [p.name for p in spine] == ["CREATED", "CLARIFIED", "IMPLEMENTED", "VERIFIED"]
    implemented = next(p for p in spine if p.name == "IMPLEMENTED")
    assert implemented.allows_code_write is True
    assert implemented.exit_gate == ("passing_tests", "test_substance")
    assert implemented.worker_skill == "e2e-harness-implementation"
```

- [ ] **Step 3: Write failing tier-isolation test**

Append this test to `skills/e2e-dev-harness/tests/test_pipeline_tiers.py`:

```python
def test_rapid_is_pipeline_not_tier():
    names = pipeline.active_phase_names("rapid")

    assert names == ["CREATED", "CLARIFIED", "IMPLEMENTED", "VERIFIED"]
    assert "RED" not in names
    assert "PLANNED" not in names
    assert "REVIEWED" not in names
```

`build_spine("rapid")` and `active_phase_names("rapid")` are intentionally both tested. They are separate APIs in `pipeline.py`, so these tests cross-check that the built spine and phase-name view stay consistent.

- [ ] **Step 4: Run tests and confirm they fail because `rapid` is unknown**

Run:

```bash
python -m pytest \
  skills/e2e-dev-harness/tests/test_pipeline_validate.py::test_rapid_builtin_spec_is_valid \
  skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py::test_rapid_loads_three_user_facing_steps \
  skills/e2e-dev-harness/tests/test_pipeline_tiers.py::test_rapid_is_pipeline_not_tier \
  -q
```

Expected: FAIL with an error mentioning `rapid` is unknown.

- [ ] **Step 5: Create rapid pipeline spec**

Create `skills/e2e-dev-harness/pipelines/rapid.yaml`:

```yaml
name: rapid
phases:
  - CREATED
  - CLARIFIED
  - phase: IMPLEMENTED
    allows_code_write: true
  - VERIFIED
```

- [ ] **Step 6: Run pipeline tests and confirm they pass**

Run:

```bash
python -m pytest \
  skills/e2e-dev-harness/tests/test_pipeline_validate.py::test_rapid_builtin_spec_is_valid \
  skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py::test_rapid_loads_three_user_facing_steps \
  skills/e2e-dev-harness/tests/test_pipeline_tiers.py::test_rapid_is_pipeline_not_tier \
  -q
```

Expected: all selected tests PASS.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add \
  skills/e2e-dev-harness/pipelines/rapid.yaml \
  skills/e2e-dev-harness/tests/test_pipeline_validate.py \
  skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py \
  skills/e2e-dev-harness/tests/test_pipeline_tiers.py
git commit -F - <<'EOF'
feat(e2e-dev-harness): add rapid pipeline spec
EOF
```

---

### Task 2: Code-Write Guard Coverage

**Classification:** Regression/pinning test. This task is expected to pass after Task 1 because it pins the `allows_code_write` contract introduced by `rapid.yaml`; do not force an artificial RED state.

**Files:**
- Modify: `skills/e2e-dev-harness/tests/test_can_write_code.py`

- [ ] **Step 1: Write rapid code-write tests**

Append these tests to `skills/e2e-dev-harness/tests/test_can_write_code.py`:

```python
def test_rapid_implemented_allows_code_write():
    state = {"current_phase": "IMPLEMENTED", "pipeline": "rapid"}

    assert pipeline.can_write_code(state) is True


def test_rapid_nonimplemented_phases_deny_code_write():
    spine = pipeline.build_spine("rapid")

    for phase in spine:
        if phase.name == "IMPLEMENTED":
            continue
        state = {"current_phase": phase.name, "pipeline": "rapid"}
        assert pipeline.can_write_code(state) is False, f"rapid:{phase.name}"
```

- [ ] **Step 2: Run the focused tests**

Run:

```bash
python -m pytest \
  skills/e2e-dev-harness/tests/test_can_write_code.py::test_rapid_implemented_allows_code_write \
  skills/e2e-dev-harness/tests/test_can_write_code.py::test_rapid_nonimplemented_phases_deny_code_write \
  -q
```

Expected: PASS. If this fails, inspect `skills/e2e-dev-harness/pipelines/rapid.yaml` and ensure the `IMPLEMENTED` entry is a mapping with `allows_code_write: true`.

- [ ] **Step 3: Commit Task 2**

Run:

```bash
git add skills/e2e-dev-harness/tests/test_can_write_code.py
git commit -F - <<'EOF'
test(e2e-dev-harness): cover rapid code-write guard
EOF
```

---

### Task 3: Agent-Team Profile And Dispatch Pairing

**Classification:** TDD red-green.

**Files:**
- Create: `skills/e2e-dev-harness/agent-teams/default-rapid.yaml`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py`
- Modify: `skills/e2e-dev-harness/tests/test_agent_team_dispatch.py`

- [ ] **Step 1: Write failing dispatch profile test**

Append this test to `skills/e2e-dev-harness/tests/test_agent_team_dispatch.py`:

```python
def test_rapid_pipeline_dispatch_auto_selects_rapid_profile(tmp_path):
    state = run_state.new_run_state(
        "r1", "feature", "request", tier="standard", pipeline="rapid")
    state["current_phase"] = "IMPLEMENTED"
    path = tmp_path / "docs" / "agent-runs" / "r1" / "run-state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state), encoding="utf-8")

    code, result = dispatch_cmd.run(Args(path, runtime="codex"))

    assert code == 0
    assert result["agent_team_plan"]["profile"] == "default-rapid"
    assert result["role"] == "code-developer"
    assert result["skill"] == "e2e-harness-implementation"
    assert result["expected_outputs"] == ["passing_tests", "test_substance"]
    assert result["runtime_subagent_type"] == "code-developer"
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
python -m pytest \
  skills/e2e-dev-harness/tests/test_agent_team_dispatch.py::test_rapid_pipeline_dispatch_auto_selects_rapid_profile \
  -q
```

Expected: FAIL. The likely failure is `unknown agent team profile: default-rapid` or `default-standard != default-rapid`.

- [ ] **Step 3: Create bundled rapid agent-team profile**

Create `skills/e2e-dev-harness/agent-teams/default-rapid.yaml`:

```yaml
schema: e2e-dev-harness.agent-team-profile.v1
name: default-rapid
description: Rapid pipeline with clarification, implementation, and verification only.
roles:
  requirements-clarifier:
    skill: e2e-harness-clarification
    runtime_subagent_type: requirements-clarifier
    max_workers: 1
  code-developer:
    skill: e2e-harness-implementation
    runtime_subagent_type: code-developer
    max_workers: 1
  coverage-reviewer:
    skill: e2e-harness-completion
    runtime_subagent_type: coverage-reviewer
    max_workers: 1
```

The profile intentionally omits a `phases:` block because `agent-team-profile.v1` treats missing phases as an empty mapping for single-worker profiles.

- [ ] **Step 4: Validate the rapid profile schema**

Run:

```bash
python - <<'PY'
from e2e_harness.adapters.agent_team import schema

profile = schema.load_profile_file(
    "skills/e2e-dev-harness/agent-teams/default-rapid.yaml")
assert profile["name"] == "default-rapid"
assert "phases" not in profile
PY
```

Expected: PASS with exit code 0. This confirms that omitting `phases:` is valid for a single-worker profile.

- [ ] **Step 5: Update dispatch default profile selection**

In `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py`, change `_default_profile` so the built-in pipeline set includes `rapid`:

```python
def _default_profile(state: dict) -> str:
    # A built-in pipeline auto-pairs its `default-<name>` team profile so its
    # phase fan-out (e.g. critical's r1/r2/r3, adversarial's code/design/tests)
    # happens without an explicit --team-profile. `adversarial` is opt-in via
    # --pipeline (not a --tier choice), so it pairs by pipeline name only.
    pipeline_name = str(state.get("pipeline", "") or "")
    if pipeline_name in {"minimal", "standard", "critical", "audited", "adversarial", "rapid"}:
        return f"default-{pipeline_name}"
    tier = str(state.get("tier", "") or "")
    if tier in {"minimal", "standard", "critical", "audited"}:
        return f"default-{tier}"
    return "default-standard"
```

- [ ] **Step 6: Run focused dispatch test**

Run:

```bash
python -m pytest \
  skills/e2e-dev-harness/tests/test_agent_team_dispatch.py::test_rapid_pipeline_dispatch_auto_selects_rapid_profile \
  -q
```

Expected: PASS.

- [ ] **Step 7: Run existing custom and adversarial profile tests**

Run:

```bash
python -m pytest \
  skills/e2e-dev-harness/tests/test_agent_team_dispatch.py::test_custom_pipeline_dispatch_falls_back_to_tier_profile \
  skills/e2e-dev-harness/tests/test_agent_team_dispatch.py::test_adversarial_pipeline_dispatch_auto_selects_adversarial_profile \
  -q
```

Expected: PASS. This protects the custom-pipeline fallback and adversarial opt-in pairing.

- [ ] **Step 8: Commit Task 3**

Run:

```bash
git add \
  skills/e2e-dev-harness/agent-teams/default-rapid.yaml \
  skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py \
  skills/e2e-dev-harness/tests/test_agent_team_dispatch.py
git commit -F - <<'EOF'
feat(e2e-dev-harness): pair rapid pipeline with default team profile
EOF
```

---

### Task 4: Tier Recommendation Isolation

**Classification:** Regression/pinning test. This task is not a TDD red-green loop; it protects the boundary that `rapid` is an opt-in pipeline, not a tier recommendation option.

**Files:**
- Modify: `skills/e2e-dev-harness/tests/test_tier_recommend.py`

- [ ] **Step 1: Write tier-isolation test**

Append this regression pinning test to `skills/e2e-dev-harness/tests/test_tier_recommend.py`. It intentionally overlaps the existing adversarial advisory test so future changes cannot accidentally promote `rapid` into tier auto-selection:

```python
def test_rapid_is_not_a_tier_recommendation_option():
    """Regression pin: rapid is an opt-in pipeline, not an auto tier option."""
    result = recommend.recommend_tier(
        "make a small copy change", scope=None, selected_tier="auto")

    assert [option["tier"] for option in result["options"]] == [
        "minimal",
        "standard",
        "critical",
        "audited",
    ]
    assert "rapid" not in [option["tier"] for option in result["options"]]
    assert result["selected_tier"] in ("minimal", "standard", "critical", "audited")
```

- [ ] **Step 2: Run focused test**

Run:

```bash
python -m pytest \
  skills/e2e-dev-harness/tests/test_tier_recommend.py::test_rapid_is_not_a_tier_recommendation_option \
  -q
```

Expected: PASS. No implementation change should be required; this test pins the design boundary.

- [ ] **Step 3: Commit Task 4**

Run:

```bash
git add skills/e2e-dev-harness/tests/test_tier_recommend.py
git commit -F - <<'EOF'
test(e2e-dev-harness): keep rapid outside tier recommendation
EOF
```

---

### Task 5: Worker Contract Documentation

**Classification:** Doc-only with existing doc tests.

**Files:**
- Modify: `skills/e2e-harness-implementation/SKILL.md`

- [ ] **Step 1: Update implementation worker contract**

In `skills/e2e-harness-implementation/SKILL.md`, after the `test-substance.json` shape block and before the `多轨/按模块作业` section, add:

```markdown
- **rapid pipeline**: 当 packet 的 pipeline/上下文显示当前 run 使用 `rapid` 流水线时,没有独立 RED worker,也不会调用 `e2e-harness-tdd-red` skill。你仍然必须保留 RED 的 evidence 语言并提交同一批 `red_tests` / `green_tests`: 在实施 worker 内先用变更前代码或等价的失败命令证据确认目标测试会失败,再实现并用同一批测试转绿。rapid 模式下 `test_substance.red_tests` 与 `green_tests` 的字段格式和普通 RED→IMPLEMENTED 流程一致,但 producer 是 `code-developer` 而不是 `test-case-developer`。当前 `test_substance` validator 只校验 manifest 字段、验收覆盖和测试实质,不检查 producer_id;如果实现时发现提交授权层额外检查 producer,必须同步放宽 rapid 的 producer 规则或回到计划修订。`test_substance` 的 `red_tests` 与 `green_tests` 仍必须是同一批节点;不能把未执行的测试名写进 manifest。
```

- [ ] **Step 2: Run worker skill documentation test**

Run:

```bash
python -m pytest skills/e2e-dev-harness/tests/test_worker_skills_delegate.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit Task 5**

Run:

```bash
git add skills/e2e-harness-implementation/SKILL.md
git commit -F - <<'EOF'
docs(e2e-dev-harness): clarify rapid implementation evidence contract
EOF
```

---

### Task 6: Coordinator Documentation

**Classification:** Doc-only with doc tests. Documentation tests may pass directly after the doc edit; do not treat that as a TDD violation.

**Files:**
- Modify: `README.md`
- Modify: `skills/e2e-dev-harness/SKILL.md`

- [ ] **Step 1: Update README tier/pipeline table**

In `README.md`, locate the `## tier 与流水线` heading and the table row whose current text is:

```markdown
| `minimal` | `CREATED → CLARIFIED → RED → IMPLEMENTED → VERIFIED` | 跳过 `PLANNED` / `REVIEWED` |
```

Add this row immediately after it:

```markdown
| `rapid` *(pipeline opt-in)* | `CREATED → CLARIFIED → IMPLEMENTED → VERIFIED` | 三步快速实施: 澄清、实施、校验; 跳过 `PLANNED` / `RED` / `REVIEWED`,用 `--pipeline rapid` 显式选择 |
```

Then locate this existing bullet:

```markdown
- `--pipeline <名|路径>`：覆盖 `--tier` 推出的 spine，可指向内建名或自定义 yaml。
```

Add this paragraph immediately after that bullet:

```markdown
`rapid` 不是 tier recommendation 的候选项,不会被 `--tier auto` 自动选择。它是显式 opt-in 的快速流水线:当需求足够小、用户接受跳过独立计划/红测/审查时,用 `start --pipeline rapid` 选择。
```

- [ ] **Step 2: Update canonical skill pipeline table**

In `skills/e2e-dev-harness/SKILL.md`, locate the `## tier 与流水线 (M2)` heading and the table row whose current text is:

```markdown
| `minimal` | CREATED→CLARIFIED→RED→IMPLEMENTED→VERIFIED | 跳过 PLANNED/REVIEWED |
```

Add this row immediately after it:

```markdown
| `rapid` *(pipeline opt-in)* | CREATED→CLARIFIED→IMPLEMENTED→VERIFIED | 三步快速实施:澄清、实施、校验;跳过 PLANNED/RED/REVIEWED,用 `start --pipeline rapid` 显式选择 |
```

Then locate the existing adversarial note that begins with:

```markdown
> `adversarial` 是 opt-in 流水线
```

Add this note before the adversarial note:

```markdown
`rapid` 不属于 `--tier auto` 候选集合,也不是风险降级;它是用户显式选择的快速流水线。实施 worker 必须在 IMPLEMENTED 内提交 `passing_tests` 与 `test_substance`,并在 rapid 模式下自行提供同批次失败/转绿测试证据。
```

- [ ] **Step 3: Add skill documentation test for rapid**

Append this test to `skills/e2e-dev-harness/tests/test_skill_md.py`:

```python
def test_skill_md_documents_rapid_optin_pipeline():
    text = SKILL.read_text(encoding="utf-8")

    assert "`rapid`" in text
    assert "start --pipeline rapid" in text
    assert "CREATED→CLARIFIED→IMPLEMENTED→VERIFIED" in text
```

- [ ] **Step 4: Run documentation tests**

Run:

```bash
python -m pytest \
  skills/e2e-dev-harness/tests/test_skill_md.py::test_skill_md_documents_rapid_optin_pipeline \
  skills/e2e-dev-harness/tests/test_skill_md.py::test_skill_md_has_frontmatter_and_verbs \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add README.md skills/e2e-dev-harness/SKILL.md skills/e2e-dev-harness/tests/test_skill_md.py
git commit -F - <<'EOF'
docs(e2e-dev-harness): document rapid pipeline
EOF
```

---

### Task 7: CLI Smoke Verification

**Files:**
- No source files expected.
- Runtime artifacts may be created under a temporary directory.

- [ ] **Step 1: Validate the new pipeline**

Run:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py validate-pipeline --pipeline rapid
```

Expected: exit code 0 and validation success JSON.

- [ ] **Step 2: Start a rapid run in a temporary repo**

Run:

```bash
tmp="$(mktemp -d "${TMPDIR:-/tmp}/e2e-rapid-smoke.XXXXXX")"
(
  cd "$tmp"
  git init >/dev/null
  printf '%s\n' "# smoke" > README.md
  git add README.md
  git -c user.name="Rapid Smoke" -c user.email="rapid-smoke@example.invalid" \
    commit -m "init" >/dev/null
)
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py start \
  --repo "$tmp" \
  --feature rapid-smoke \
  --request "tiny smoke change" \
  --pipeline rapid
```

Expected: output JSON contains `"pipeline": "rapid"` and a `run_state` path.

- [ ] **Step 3: Inspect navigation map for rapid phases**

Run:

```bash
state="$(find "$tmp/docs/agent-runs" -name run-state.json -print -quit)"
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py status \
  --state "$state" \
  --repo "$tmp"
```

Expected: navigation contains `CREATED`, `CLARIFIED`, `IMPLEMENTED`, and `VERIFIED`; it does not contain `PLANNED`, `RED`, or `REVIEWED`.

- [ ] **Step 4: Confirm CLARIFIED navigation without dispatching**

Run:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py next \
  --state "$state" \
  --repo "$tmp"
```

Expected: `next` reports the first blocker at `CLARIFIED`. Do not dispatch here; Task 3 already covers `default-rapid` dispatch pairing.

- [ ] **Step 5: Commit no files for smoke**

Do not commit temporary smoke artifacts. If any smoke artifacts were created inside the real repo by mistake, remove only those generated files after verifying they are under `docs/agent-runs/<rapid-smoke-run-id>`.

---

### Task 8: Independent Reviewer Subagent Gate

**Files:**
- No source files expected.
- Review result should be recorded in the coordinator notes or the task handoff for the implementation run.

- [ ] **Step 1: Capture review SHAs**

Run:

```bash
BASE_SHA="$(git rev-parse HEAD~1)"
HEAD_SHA="$(git rev-parse HEAD)"
printf 'BASE_SHA=%s\nHEAD_SHA=%s\n' "$BASE_SHA" "$HEAD_SHA"
```

Expected: two commit SHAs print. If implementation used multiple commits, set `BASE_SHA` to the commit before the first rapid-pipeline implementation commit and `HEAD_SHA` to the latest implementation commit.

- [ ] **Step 2: Dispatch a fresh reviewer subagent**

Use `superpowers:requesting-code-review` and dispatch a new code-reviewer subagent. The reviewer must not be the agent that wrote the implementation. Use this review prompt:

```text
DESCRIPTION:
Review the rapid pipeline implementation. The implementation adds an explicit opt-in rapid pipeline with user-facing phases 澄清 -> 实施 -> 校验, backed by internal spine CREATED -> CLARIFIED -> IMPLEMENTED -> VERIFIED.

PLAN_OR_REQUIREMENTS:
Use docs/superpowers/plans/2026-06-13-rapid-pipeline.md. Check especially:
- rapid is a pipeline, not a tier option
- rapid dispatch uses default-rapid
- implementation worker expected_outputs are passing_tests and test_substance
- reviewer/implementer independence is preserved
- commands and docs use bash/POSIX syntax
- no self-review is used as completion evidence

BASE_SHA:
{BASE_SHA}

HEAD_SHA:
{HEAD_SHA}

REVIEW RULE:
You are an independent reviewer subagent. Do not modify files. Report Critical, Important, and Minor findings with file/line references.
```

Expected: a reviewer subagent report. It must identify itself as a separate review worker and must not contain any file modifications.

- [ ] **Step 3: Act on reviewer findings**

If the reviewer reports Critical or Important findings, fix them before continuing. For every fix, rerun the focused test that covers the changed behavior.

Expected: no unfixed Critical or Important findings remain.

- [ ] **Step 4: Record the independent review result**

Record the reviewer result in the implementation handoff or coordinator notes with:

```text
reviewer: independent subagent
base_sha: <BASE_SHA>
head_sha: <HEAD_SHA>
critical_findings_open: 0
important_findings_open: 0
minor_findings_open: <count>
```

Expected: the run has explicit evidence that review was performed by a fresh subagent, not by the implementation worker.

---

### Task 9: Regression Suite And GitNexus Change Check

**Files:**
- No new source edits expected.

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
python -m pytest \
  skills/e2e-dev-harness/tests/test_pipeline_validate.py \
  skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py \
  skills/e2e-dev-harness/tests/test_pipeline_tiers.py \
  skills/e2e-dev-harness/tests/test_can_write_code.py \
  skills/e2e-dev-harness/tests/test_agent_team_dispatch.py \
  skills/e2e-dev-harness/tests/test_tier_recommend.py \
  skills/e2e-dev-harness/tests/test_skill_md.py \
  skills/e2e-dev-harness/tests/test_worker_skills_delegate.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run formatting/whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 3: Run GitNexus change detection before final commit**

Run:

```text
gitnexus_detect_changes({
  "repo": "e2e-dev-workflow",
  "scope": "all"
})
```

Expected: changed symbols and affected flows are limited to dispatch profile selection, tests, docs, and new YAML specs. If unexpected core engine, gate, lifecycle, or evidence-validator flows appear, stop and inspect the diff.

- [ ] **Step 4: Final commit if previous tasks were not committed separately**

Run only if Tasks 1-6 were not already committed:

```bash
git add \
  skills/e2e-dev-harness/pipelines/rapid.yaml \
  skills/e2e-dev-harness/agent-teams/default-rapid.yaml \
  skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py \
  skills/e2e-harness-implementation/SKILL.md \
  README.md \
  skills/e2e-dev-harness/SKILL.md \
  skills/e2e-dev-harness/tests/test_pipeline_validate.py \
  skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py \
  skills/e2e-dev-harness/tests/test_pipeline_tiers.py \
  skills/e2e-dev-harness/tests/test_can_write_code.py \
  skills/e2e-dev-harness/tests/test_agent_team_dispatch.py \
  skills/e2e-dev-harness/tests/test_tier_recommend.py \
  skills/e2e-dev-harness/tests/test_skill_md.py
git commit -F - <<'EOF'
feat(e2e-dev-harness): add rapid implementation pipeline
EOF
```

- [ ] **Step 5: Verify acceptance criteria evidence mapping**

Run this checklist manually and record the evidence paths/commands in the implementation handoff:

```text
AC1 active_phase_names("rapid") returns CREATED, CLARIFIED, IMPLEMENTED, VERIFIED:
  evidence: test_pipeline_tiers.py::test_rapid_is_pipeline_not_tier
AC2 build_spine("rapid") returns the same phase names and IMPLEMENTED inherits the correct gate:
  evidence: test_pipeline_yaml_load.py::test_rapid_loads_three_user_facing_steps
AC3 rapid IMPLEMENTED allows code writes and other rapid phases deny:
  evidence: test_can_write_code.py::test_rapid_implemented_allows_code_write
  evidence: test_can_write_code.py::test_rapid_nonimplemented_phases_deny_code_write
AC4 rapid dispatch uses default-rapid and expected_outputs from produces:
  evidence: test_agent_team_dispatch.py::test_rapid_pipeline_dispatch_auto_selects_rapid_profile
AC5 rapid is not a tier option:
  evidence: test_tier_recommend.py::test_rapid_is_not_a_tier_recommendation_option
AC6 validate-pipeline succeeds:
  evidence: Task 7 Step 1 command output
AC7 docs explain start --pipeline rapid:
  evidence: test_skill_md.py::test_skill_md_documents_rapid_optin_pipeline
AC8 independent reviewer subagent completed:
  evidence: Task 8 review record
AC9 GitNexus scope is expected:
  evidence: Task 9 Step 3 detect_changes output
```

Expected: every acceptance criterion has at least one concrete test, command, or review evidence item.

---

## Acceptance Criteria

- `pipeline.active_phase_names("rapid")` returns `["CREATED", "CLARIFIED", "IMPLEMENTED", "VERIFIED"]`.
- `pipeline.can_write_code({"current_phase": "IMPLEMENTED", "pipeline": "rapid"})` returns `True`.
- Rapid non-implementation phases deny code writes.
- `dispatch` for a rapid run uses `agent_team_plan.profile == "default-rapid"`.
- Rapid implementation dispatch exposes `expected_outputs == ["passing_tests", "test_substance"]` from the phase `produces` contract.
- `recommend_tier(..., selected_tier="auto")` does not include `rapid` in `options`.
- `validate-pipeline --pipeline rapid` succeeds.
- README and canonical skill docs explain `start --pipeline rapid` as explicit opt-in.
- Independent reviewer subagent review is recorded, and no Critical or Important review findings remain open.
- GitNexus change detection before commit shows only the expected dispatch/docs/tests/spec scope.

## Self-Review Notes

Verified evidence:
- Command shell: this plan now uses bash code blocks and POSIX syntax; the legacy Windows-only command forms called out in review should not appear in executable command blocks.
- TDD discipline: `Task Classification` separates true TDD cycles from regression/pinning and doc-only tasks, so Task 2, Task 4, and Task 6 are not mislabeled as red-green work.
- Subagent scheduling: `Task Dependency Graph` states Task 1 must precede Task 2/3/4, Task 7 must follow Task 3, and Task 9 must run last.
- Commit convention: current recent history includes scoped messages such as `25ac090 feat(e2e-dev-harness): close the loop-engineering truth chain`; all plan commit commands now use `git commit -F - <<'EOF'` with scoped subjects.
- Pipeline inheritance: `skills/e2e-dev-harness/scripts/e2e_harness/core/lifecycle.py:23` defines `IMPLEMENTED` with `worker_skill == "e2e-harness-implementation"`, `produces == ("passing_tests", "test_substance")`, and matching `exit_gate`.
- Code-write authority: `skills/e2e-dev-harness/scripts/e2e_harness/pipeline.py:21` allows pipeline YAML to override `allows_code_write`; `pipeline.py:126` reads that flag through `can_write_code`.
- Pipeline API consistency: `skills/e2e-dev-harness/scripts/e2e_harness/pipeline.py:79` defines `active_phase_names`, while `pipeline.py:83` defines `build_spine`; Task 1 tests both APIs for `rapid`.
- Agent-team schema: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/agent_team/schema.py:52` defaults missing `phases` to `{}` and `schema.py:53` only requires a mapping when `phases` is present, so `default-rapid.yaml` can omit `phases`.
- Test-substance producer semantics: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/substance.py:33` starts `validate_substance_manifest`, and `substance.py:53-57` checks `red_tests`/`green_tests` presence and same-batch equality without inspecting producer_id or worker role.
- README insertion anchors were verified with `Select-String`: `README.md:305` for `## tier 与流水线`, `README.md:312` for the `minimal` table row, and `README.md:322` for the `--pipeline <名|路径>` bullet.
- Canonical skill insertion anchors were verified with `Select-String`: `skills/e2e-dev-harness/SKILL.md:58` for `## tier 与流水线 (M2)`, `SKILL.md:64` for the `minimal` row, and `SKILL.md:70` for the adversarial note.
- Reviewer independence is explicitly represented as a hard execution gate in Task 8; completion cannot rely on self-review by the code-writing agent.
- Acceptance criteria now have a dedicated evidence-mapping step in Task 9 Step 5.

Not verified during plan writing:
- The new `rapid` files do not exist yet, so `validate-pipeline --pipeline rapid`, `schema.load_profile_file(".../default-rapid.yaml")`, and the rapid smoke run are verification steps for implementation time.
- The GitNexus impact result for `_default_profile` was previously observed as LOW, but implementers must rerun the Pre-Flight impact check immediately before editing that function.
