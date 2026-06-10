# E2E Dev Harness Risk Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the verified high-value risks from the code-quality audit: unsafe provider loading visibility, JSON settings protection, run-state lock recovery, worker-stall recovery, auto-tier risk detection, RED-phase write-policy consistency, and avoidable Java scan I/O.

**Architecture:** Keep changes narrow and compatible with the current Node wrapper plus Python core layout. Add observable warnings and recovery behavior without introducing new runtime dependencies. Use TDD for every behavior change and run GitNexus impact analysis before editing any function, class, or method.

**Tech Stack:** Node.js built-in test runner, Python 3.10+, pytest, GitNexus MCP impact/change detection.

---

## Scope

This plan covers seven independently testable fixes:

- Protect `.claude/settings.json` from silent overwrite when existing JSON is corrupt.
- Make dynamic provider loading auditable and clearly bounded to trusted repositories.
- Improve run-state lock recovery and temporary file uniqueness.
- Detect stale worker dispatches and give operators an explicit retry or failure path.
- Make `--tier auto` avoid silent risk under-classification when scanner evidence is unavailable.
- Reconcile RED-phase write permissions across lifecycle defaults, YAML pipeline overrides, and hook messages.
- Reduce repeated Java file reads in the GitNexus/Graphify refresh detector.

This plan does not perform a broad legacy refactor, replace the provider system, rewrite Graphify/GitNexus skills, or introduce third-party locking libraries.

## Files

- Modify: `lib/hooks.js`
- Modify: `test/hooks.test.js`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/scanner/_legacy/plugin_registry.py`
- Test: `skills/e2e-dev-harness/tests/test_scanner.py` or create `skills/e2e-dev-harness/tests/test_plugin_registry.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/run_state.py`
- Test: `skills/e2e-dev-harness/tests/test_run_state.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/dispatch.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/navigation.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/status.py`
- Test: `skills/e2e-dev-harness/tests/test_dispatch.py`
- Test: `skills/e2e-dev-harness/tests/test_navigation.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/classifier.py`
- Test: `skills/e2e-dev-harness/tests/test_tier_classify.py`
- Test: `skills/e2e-dev-harness/tests/test_cli_e2e.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/lifecycle.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/phase_guard.py`
- Modify: `skills/e2e-dev-harness/pipelines/minimal.yaml`
- Modify: `skills/e2e-dev-harness/pipelines/standard.yaml`
- Modify: `skills/e2e-dev-harness/pipelines/audited.yaml`
- Modify: `skills/e2e-dev-harness/pipelines/critical.yaml`
- Test: `skills/e2e-dev-harness/tests/test_can_write_code.py`
- Test: `skills/e2e-dev-harness/tests/test_phase_guard.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/kg/_legacy/kg_refresh.py`
- Test: `skills/e2e-dev-harness/tests/test_kg_refresh.py`
- Optional docs: `README.md` or the relevant e2e-dev-harness skill documentation if command-path guidance is not already present.

## Pre-Implementation Checklist

- [ ] Run `git status` and note existing user changes.
- [ ] For each symbol before editing, run GitNexus upstream impact:

```text
impact(target="readJsonOrEmpty", direction="upstream", repo="e2e-dev-workflow")
impact(target="materializeHooks", direction="upstream", repo="e2e-dev-workflow")
impact(target="load_provider", direction="upstream", repo="e2e-dev-workflow")
impact(target="load_providers", direction="upstream", repo="e2e-dev-workflow")
impact(target="_lock", direction="upstream", repo="e2e-dev-workflow")
impact(target="save", direction="upstream", repo="e2e-dev-workflow")
impact(target="mark_dispatched", direction="upstream", repo="e2e-dev-workflow")
impact(target="navigation_map", direction="upstream", repo="e2e-dev-workflow")
impact(target="run", file_path="skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py", direction="upstream", repo="e2e-dev-workflow")
impact(target="classify_auto", direction="upstream", repo="e2e-dev-workflow")
impact(target="can_write_code", direction="upstream", repo="e2e-dev-workflow")
impact(target="detect", direction="upstream", repo="e2e-dev-workflow")
```

- [ ] If any impact result is HIGH or CRITICAL, report the blast radius before editing.

---

### Task 1: Protect Existing Hook Settings JSON

**Files:**
- Modify: `lib/hooks.js`
- Modify: `test/hooks.test.js`

- [ ] **Step 1: Write the failing test for corrupt settings**

Add a Node test that creates an existing `.claude/settings.json` with invalid JSON and verifies `materializeHooks()` refuses to overwrite it.

```javascript
test('materializeHooks refuses to overwrite corrupt settings JSON', () => {
  const root = tmpdir();
  const skillHome = path.join(root, 'skill');
  const projectRoot = path.join(root, 'project');
  fs.mkdirSync(path.join(skillHome, 'hooks'), { recursive: true });
  fs.mkdirSync(path.join(projectRoot, '.claude'), { recursive: true });
  fs.writeFileSync(
    path.join(skillHome, 'hooks', 'claude-code-settings.example.json'),
    JSON.stringify({ hooks: { Stop: [{ hooks: [{ command: 'echo ok' }] }] } })
  );
  const settingsPath = path.join(projectRoot, '.claude', 'settings.json');
  fs.writeFileSync(settingsPath, '{ broken json');

  assert.throws(
    () => materializeHooks({ skillHome, projectRoot }),
    /Could not parse existing Claude settings JSON/
  );
  assert.equal(fs.readFileSync(settingsPath, 'utf8'), '{ broken json');
});
```

- [ ] **Step 2: Run the failing Node test**

Run:

```powershell
node --test test\hooks.test.js
```

Expected: the new test fails because corrupt JSON is currently treated as `{}`.

- [ ] **Step 3: Implement a typed parse failure**

Update `readJsonOrEmpty()` so parse failures preserve the original file and make the caller stop.

```javascript
function readJsonOrEmpty(fs, file) {
  if (!fs.existsSync(file)) return { value: {}, existed: false, warning: null };
  try {
    return { value: JSON.parse(fs.readFileSync(file, 'utf8')), existed: true, warning: null };
  } catch (err) {
    const message = `Could not parse existing Claude settings JSON: ${file}. Original file was not modified.`;
    const error = new Error(message);
    error.cause = err;
    error.code = 'E_SETTINGS_JSON_PARSE';
    throw error;
  }
}
```

- [ ] **Step 4: Harden rollback failure reporting**

Wrap rollback in its own `try/catch` in `materializeHooks()` so a failed restore is visible.

```javascript
  } catch (err) {
    try {
      if (backup) {
        fs.copyFileSync(backup, settingsPath);
      } else if (fs.existsSync(settingsPath)) {
        fs.rmSync(settingsPath, { force: true });
      }
    } catch (rollbackErr) {
      err.message = `${err.message}; rollback also failed: ${rollbackErr.message}`;
    }
    throw err;
  }
```

- [ ] **Step 5: Verify**

Run:

```powershell
node --test test\hooks.test.js
```

Expected: all hook tests pass.

---

### Task 2: Make Provider Loading Auditable

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/scanner/_legacy/plugin_registry.py`
- Create or modify: `skills/e2e-dev-harness/tests/test_plugin_registry.py`

- [ ] **Step 1: Write the failing test for load warnings**

Create `test_plugin_registry.py` if a focused file does not exist. The test should prove loaded providers report module origin.

```python
from pathlib import Path

from e2e_harness.adapters.scanner._legacy import plugin_registry


def test_load_providers_reports_provider_origin(tmp_path):
    provider_dir = tmp_path / ".e2e" / "providers"
    provider_dir.mkdir(parents=True)
    (provider_dir / "custom_provider.py").write_text(
        "scanner = {'name': 'custom', 'languages': ['java']}\n",
        encoding="utf-8",
    )
    registry = {
        "schema": plugin_registry.SCHEMA,
        "scanners": ["custom_provider:scanner"],
        "custom_gates": [],
        "policy_packs": [],
        "warnings": [],
    }

    loaded = plugin_registry.load_providers(tmp_path, "scanners", registry)

    assert loaded["providers"][0]["name"] == "custom"
    assert any("custom_provider" in warning for warning in loaded["warnings"])
    assert any(".e2e/providers" in warning.replace("\\", "/") for warning in loaded["warnings"])
```

- [ ] **Step 2: Run the failing provider test**

Run:

```powershell
python -m pytest skills\e2e-dev-harness\tests\test_plugin_registry.py -q
```

Expected: failure because successful provider loads do not currently add origin warnings.

- [ ] **Step 3: Return provider metadata from `load_provider()`**

Keep compatibility by returning provider dicts, but add reserved metadata keys.

```python
        module = importlib.import_module(module_name)
        provider = getattr(module, attr_name)
        origin = str(Path(getattr(module, "__file__", "") or "").resolve())
        if callable(provider) and not inspect.signature(provider).parameters:
            provider = provider()
        if isinstance(provider, dict):
            loaded = dict(provider)
        else:
            loaded = {"name": attr_name, "provider": provider}
        loaded.setdefault("warnings", [])
        loaded["_provider_module"] = module_name
        loaded["_provider_origin"] = origin
        return loaded
```

- [ ] **Step 4: Surface trust-boundary warnings in `load_providers()`**

Append a warning for successful dynamic loads.

```python
            provider = load_provider(repo, str(spec))
            origin = str(provider.get("_provider_origin") or "")
            if origin:
                result["warnings"].append(
                    f"Loaded dynamic provider {spec} from {origin}. Only scan trusted repositories."
                )
            result["providers"].append(provider)
```

- [ ] **Step 5: Verify scanner tests**

Run:

```powershell
python -m pytest skills\e2e-dev-harness\tests\test_plugin_registry.py skills\e2e-dev-harness\tests\test_scanner.py -q
```

Expected: provider registry and scanner tests pass.

---

### Task 3: Improve Run-State Lock Recovery

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/run_state.py`
- Modify: `skills/e2e-dev-harness/tests/test_run_state.py`

- [ ] **Step 1: Write the stale lock test**

Add a test that writes an old lock file for a non-current PID and confirms `mutate()` proceeds.

```python
def test_mutate_clears_stale_lock_file(tmp_path):
    p = tmp_path / "run-state.json"
    run_state.save(p, run_state.new_run_state("r1", "feat", "req"))
    lock = tmp_path / "run-state.json.lock"
    lock.write_text('{"pid": 999999, "created_at": 0}', encoding="utf-8")

    run_state.mutate(p, lambda s: s.__setitem__("feature", "updated"))

    assert run_state.load(p)["feature"] == "updated"
    assert not lock.exists()
```

- [ ] **Step 2: Write the unique temporary file test**

Add a test that direct concurrent `save()` calls do not leave predictable PID-only temp files.

```python
def test_save_leaves_no_pid_temp_file(tmp_path):
    p = tmp_path / "run-state.json"
    run_state.save(p, run_state.new_run_state("r1", "feat", "req"))
    leftovers = [path.name for path in tmp_path.iterdir() if path.name.endswith(".tmp")]
    assert leftovers == []
```

- [ ] **Step 3: Run failing run-state tests**

Run:

```powershell
python -m pytest skills\e2e-dev-harness\tests\test_run_state.py -q
```

Expected: stale lock test fails because stale lock cleanup is not implemented.

- [ ] **Step 4: Implement unique temp files**

Use `tempfile.mkstemp()` inside `save()` and clean up on failure.

```python
import tempfile


def save(path: str | Path, state: dict, now: str | None = None) -> None:
    state = dict(state)
    state["updated_at"] = _stamp(now)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, indent=2, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{p.name}.", suffix=".tmp", dir=str(p.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, p)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
```

- [ ] **Step 5: Implement stale lock cleanup**

Write lock metadata and clear obviously stale lock files when the PID is not alive.

```python
def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _lock_is_stale(lock: Path) -> bool:
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    pid = int(data.get("pid") or 0)
    return bool(pid and not _pid_exists(pid))
```

Inside `_lock()` after `FileExistsError` / `PermissionError`, check and unlink stale locks before sleeping.

```python
            if _lock_is_stale(lock):
                with contextlib.suppress(FileNotFoundError, PermissionError):
                    lock.unlink()
                continue
```

After acquiring the lock fd, write metadata.

```python
            os.write(fd, json.dumps({"pid": os.getpid(), "created_at": time.time()}).encode("utf-8"))
```

- [ ] **Step 6: Verify run-state tests**

Run:

```powershell
python -m pytest skills\e2e-dev-harness\tests\test_run_state.py skills\e2e-dev-harness\tests\test_concurrency.py -q
```

Expected: all selected tests pass.

---

### Task 4: Detect Stale Worker Dispatches

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/dispatch.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/dispatch.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/navigation.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/status.py`
- Modify: `skills/e2e-dev-harness/tests/test_dispatch.py`
- Modify: `skills/e2e-dev-harness/tests/test_navigation.py`

- [ ] **Step 1: Write the failing test for stale dispatched workers**

Add a test proving an old `DISPATCHED` record is surfaced as stale and includes operator actions.

```python
def test_navigation_reports_stale_dispatched_worker(tmp_path):
    from e2e_harness.core import navigation, run_state

    p = tmp_path / "run-state.json"
    st = run_state.new_run_state("r1", "feat", "req")
    st["current_phase"] = "RED"
    st["phases"] = {
        "RED": {
            "dispatch": "dispatched",
            "dispatched_at": "20260101T000000Z",
        }
    }
    run_state.save(p, st, now="20260609T000000Z")

    nav = navigation.build_navigation_map(run_state.load(p), now="20260609T000000Z")

    assert nav["current"]["phase"] == "RED"
    assert nav["current"]["dispatch_stale"] is True
    assert "dispatch --retry" in nav["current"]["next_actions"]
    assert "submit --status failed" in nav["current"]["next_actions"]
```

- [ ] **Step 2: Run the failing navigation test**

Run:

```powershell
python -m pytest skills\e2e-dev-harness\tests\test_navigation.py -q
```

Expected: failure because stale dispatched workers are not currently represented.

- [ ] **Step 3: Add dispatch timestamp metadata**

In `cli/commands/dispatch.py`, record `dispatched_at` when setting `dispatch`.

```python
from e2e_harness.core.run_state import _stamp


rec["dispatch"] = dispatch.DispatchStatus.DISPATCHED.value
rec["dispatched_at"] = _stamp()
```

- [ ] **Step 4: Add stale detection helper**

In `core/dispatch.py`, add a small pure helper.

```python
STALE_DISPATCH_AFTER_SECONDS = 60 * 60


def is_stale_dispatched(record: dict, now_ts: str, max_age_seconds: int = STALE_DISPATCH_AFTER_SECONDS) -> bool:
    if record.get("dispatch") != DispatchStatus.DISPATCHED.value:
        return False
    dispatched_at = str(record.get("dispatched_at") or "")
    if not dispatched_at:
        return True
    try:
        started = time.strptime(dispatched_at, "%Y%m%dT%H%M%SZ")
        now = time.strptime(now_ts, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return True
    return time.mktime(now) - time.mktime(started) >= max_age_seconds
```

- [ ] **Step 5: Surface stale state in navigation/status**

Add `dispatch_stale` and `next_actions` to the current phase block when stale.

```python
if dispatch.is_stale_dispatched(phase_record, now_ts):
    current["dispatch_stale"] = True
    current["next_actions"] = [
        f"dispatch --retry --phase {current_phase}",
        f"submit --phase {current_phase} --status failed --reason <reason>",
    ]
```

- [ ] **Step 6: Verify dispatch/navigation tests**

Run:

```powershell
python -m pytest skills\e2e-dev-harness\tests\test_dispatch.py skills\e2e-dev-harness\tests\test_navigation.py -q
```

Expected: selected dispatch and navigation tests pass.

---

### Task 5: Make `--tier auto` Risk-Aware

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/start.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/tier/classifier.py`
- Modify: `skills/e2e-dev-harness/tests/test_tier_classify.py`
- Modify: `skills/e2e-dev-harness/tests/test_cli_e2e.py`

- [ ] **Step 1: Write failing tests for high-risk auto classification**

Add tests that prove public API, schema, cross-service, and security language do not remain minimal under `--tier auto`.

```python
def test_auto_tier_classifies_public_api_as_standard_or_higher():
    from e2e_harness.adapters.tier.classifier import classify_auto

    result = classify_auto("Change public API response schema for payment service")

    assert result["tier"] in {"standard", "critical", "audited"}
    assert any("api" in reason.lower() or "schema" in reason.lower() for reason in result["risk_reasons"])
```

- [ ] **Step 2: Add a test for unavailable scan evidence**

```python
def test_auto_tier_records_scan_degradation_when_scanner_unavailable(monkeypatch, tmp_path):
    from e2e_harness.cli.commands import start

    args = SimpleNamespace(
        state=str(tmp_path / "run-state.json"),
        feature="api-change",
        request="Change public API response schema",
        tier="auto",
        pipeline="minimal",
        repo=str(tmp_path),
    )

    code, result = start.run(args)

    assert code == 0
    assert result["tier"] != "minimal"
    assert result.get("tier_reasons")
```

- [ ] **Step 3: Run failing auto-tier tests**

Run:

```powershell
python -m pytest skills\e2e-dev-harness\tests\test_tier_classify.py skills\e2e-dev-harness\tests\test_cli_e2e.py -q
```

Expected: tests fail where `auto` can silently choose minimal or lacks degradation reasons.

- [ ] **Step 4: Strengthen classifier output**

Return structured classification data from `classify_auto()`.

```python
return {
    "tier": tier,
    "risk_reasons": risk_reasons,
    "scan_status": scan_status,
    "scan_warnings": scan_warnings,
}
```

- [ ] **Step 5: Persist tier reasons into run-state**

In `start.py`, when `tier == "auto"`, persist both chosen tier and reasons.

```python
classification = classify_auto(args.request, repo=repo)
tier = classification["tier"]
state["tier_reasons"] = classification.get("risk_reasons", [])
state["tier_scan_status"] = classification.get("scan_status", "not-run")
state["tier_scan_warnings"] = classification.get("scan_warnings", [])
```

- [ ] **Step 6: Verify tier tests**

Run:

```powershell
python -m pytest skills\e2e-dev-harness\tests\test_tier_classify.py skills\e2e-dev-harness\tests\test_cli_e2e.py -q
```

Expected: auto-tier tests pass and state records reasons.

---

### Task 6: Reconcile RED-Phase Write Permissions

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/lifecycle.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/hooks/phase_guard.py`
- Modify: `skills/e2e-dev-harness/pipelines/minimal.yaml`
- Modify: `skills/e2e-dev-harness/pipelines/standard.yaml`
- Modify: `skills/e2e-dev-harness/pipelines/audited.yaml`
- Modify: `skills/e2e-dev-harness/pipelines/critical.yaml`
- Modify: `skills/e2e-dev-harness/tests/test_can_write_code.py`
- Modify: `skills/e2e-dev-harness/tests/test_phase_guard.py`

- [ ] **Step 1: Write the policy test**

Add a test proving RED allows test-file writes but blocks implementation writes.

```python
def test_red_phase_allows_test_writes_but_blocks_source_writes(tmp_path):
    state_path = _write_state(tmp_path, "RED")

    allowed = phase_guard.check_write_allowed(
        repo=tmp_path,
        state_path=state_path,
        command="Set-Content tests/test_example.py 'def test_x(): assert True'",
    )
    blocked = phase_guard.check_write_allowed(
        repo=tmp_path,
        state_path=state_path,
        command="Set-Content src/app.py 'print(1)'",
    )

    assert allowed["allow"] is True
    assert blocked["allow"] is False
```

- [ ] **Step 2: Run failing phase guard tests**

Run:

```powershell
python -m pytest skills\e2e-dev-harness\tests\test_can_write_code.py skills\e2e-dev-harness\tests\test_phase_guard.py -q
```

Expected: failure if RED is treated as all-or-nothing for code writes.

- [ ] **Step 3: Document phase policy in lifecycle or guard constants**

Represent RED as test-write-only and IMPLEMENTED as implementation-write-enabled.

```python
TEST_WRITE_PHASES = {"RED"}
IMPLEMENTATION_WRITE_PHASES = {"IMPLEMENTED"}
```

- [ ] **Step 4: Update hook decision logic**

Allow RED writes only for paths that are clearly tests.

```python
def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return normalized.startswith("test/") or "/tests/" in normalized or normalized.startswith("tests/")
```

Use this check before rejecting writes in RED.

- [ ] **Step 5: Update rejection copy**

Change hook text so it no longer implies only IMPLEMENTED can write.

```python
"test writes are permitted in RED; implementation writes are permitted only in phases declared for implementation."
```

- [ ] **Step 6: Verify phase guard tests**

Run:

```powershell
python -m pytest skills\e2e-dev-harness\tests\test_can_write_code.py skills\e2e-dev-harness\tests\test_phase_guard.py -q
```

Expected: RED test-write behavior is explicit and passing.

---

### Task 7: Reduce Repeated Java Reads in KG Refresh

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/kg/_legacy/kg_refresh.py`
- Modify: `skills/e2e-dev-harness/tests/test_kg_refresh.py`

- [ ] **Step 1: Add a helper test for multi-pattern matching**

Add a focused test for a new helper that reads file text once and checks all Spring markers.

```python
from e2e_harness.adapters.kg._legacy import kg_refresh


def test_is_spring_entrypoint_detects_configuration(tmp_path):
    java_file = tmp_path / "App.java"
    java_file.write_text("@Configuration\nclass App {}", encoding="utf-8")

    assert kg_refresh.is_spring_entrypoint(java_file)
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m pytest skills\e2e-dev-harness\tests\test_kg_refresh.py -q
```

Expected: failure because `is_spring_entrypoint()` does not exist.

- [ ] **Step 3: Implement the helper**

Add constants and a helper in `kg_refresh.py`.

```python
SPRING_ENTRYPOINT_MARKERS = (
    "@Configuration",
    "@EnableWebMvc",
    "WebApplicationInitializer",
)


def is_spring_entrypoint(path: Path) -> bool:
    if path.suffix != ".java":
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    return any(marker in text for marker in SPRING_ENTRYPOINT_MARKERS)
```

- [ ] **Step 4: Update `detect()` to use the helper**

Replace the repeated `contains_text()` calls in `spring_entrypoints` with:

```python
    spring_entrypoints = sorted(
        posix(path.relative_to(repo))
        for path in files
        if is_spring_entrypoint(path)
    )
```

- [ ] **Step 5: Verify KG refresh tests**

Run:

```powershell
python -m pytest skills\e2e-dev-harness\tests\test_kg_refresh.py -q
```

Expected: all KG refresh tests pass.

---

### Task 8: Document Windows Command Path Guidance

**Files:**
- Modify: relevant command-evidence docs or README section that describes evidence commands.

- [ ] **Step 1: Locate command-evidence documentation**

Run:

```powershell
rg "command evidence|record_command|evidence command|command_evidence|evidence" README.md docs skills\e2e-dev-harness -n
```

Expected: identify the smallest existing documentation section that explains evidence commands.

- [ ] **Step 2: Add the guidance**

Add this exact guidance near command-evidence usage:

```markdown
On Windows, command evidence strings are parsed with POSIX shell-style quoting for cross-platform consistency. Prefer forward slashes in paths, for example `C:/repo/project`, or quote and escape backslashes deliberately.
```

- [ ] **Step 3: Verify docs only changed as intended**

Run:

```powershell
git diff -- README.md docs skills\e2e-dev-harness
```

Expected: only the command-path guidance and planned code/test changes appear.

---

## Final Verification

- [ ] Run Node tests:

```powershell
node --test
```

- [ ] Run Python tests:

```powershell
python -m pytest skills\e2e-dev-harness\tests -q
python -m pytest tests -q
```

- [ ] Run GitNexus change detection before commit:

```text
detect_changes(scope="all", repo="e2e-dev-workflow")
```

- [ ] Confirm changed symbols and execution flows match this plan:
  - hook materialization
  - provider registry loading
  - run-state save/mutate locking
  - stale worker dispatch recovery
  - auto-tier classification
  - RED-phase write policy
  - KG refresh detection

## Deferred Follow-Up Plans

Create separate implementation plans for these audit findings instead of mixing them into this risk-remediation batch:

- Graphify/GitNexus skill governance: Graphify naming consistency, trigger narrowing, progressive disclosure split, GitNexus schema completion, and local `gitnexus-pr-review` availability.
- Legacy import cleanup: consolidate duplicated `_legacy/common.py`, remove scattered `sys.path.insert(...)`, and standardize package imports.
- Observability hardening: introduce a repository-level warnings/logging pattern and replace broad silent `except Exception` blocks in scanner, memory, and KG adapters.
- Large scanner performance: collapse repeated `cross_service_dependency_scan.py` full-tree walks into a single indexed file pass with tests.
- Audit-report calibration: correct inaccurate claims such as "core layer has zero unit tests" and replace them with precise coverage gaps for `engine.py`, `gates.py`, and dispatch edge cases.

## Commit Plan

Commit each task separately if practical:

```powershell
git add lib\hooks.js test\hooks.test.js
git commit -m "fix: protect hook settings from corrupt JSON"

git add skills\e2e-dev-harness\scripts\e2e_harness\adapters\scanner\_legacy\plugin_registry.py skills\e2e-dev-harness\tests\test_plugin_registry.py
git commit -m "fix: report dynamic provider origins"

git add skills\e2e-dev-harness\scripts\e2e_harness\core\run_state.py skills\e2e-dev-harness\tests\test_run_state.py
git commit -m "fix: recover stale run-state locks"

git add skills\e2e-dev-harness\scripts\e2e_harness\core\dispatch.py skills\e2e-dev-harness\scripts\e2e_harness\core\navigation.py skills\e2e-dev-harness\scripts\e2e_harness\cli\commands\dispatch.py skills\e2e-dev-harness\scripts\e2e_harness\cli\commands\status.py skills\e2e-dev-harness\tests\test_dispatch.py skills\e2e-dev-harness\tests\test_navigation.py
git commit -m "fix: surface stale worker dispatches"

git add skills\e2e-dev-harness\scripts\e2e_harness\cli\commands\start.py skills\e2e-dev-harness\scripts\e2e_harness\adapters\tier\classifier.py skills\e2e-dev-harness\tests\test_tier_classify.py skills\e2e-dev-harness\tests\test_cli_e2e.py
git commit -m "fix: make auto tier risk-aware"

git add skills\e2e-dev-harness\scripts\e2e_harness\core\lifecycle.py skills\e2e-dev-harness\scripts\e2e_harness\adapters\hooks\phase_guard.py skills\e2e-dev-harness\pipelines skills\e2e-dev-harness\tests\test_can_write_code.py skills\e2e-dev-harness\tests\test_phase_guard.py
git commit -m "fix: clarify red phase write policy"

git add skills\e2e-dev-harness\scripts\e2e_harness\adapters\kg\_legacy\kg_refresh.py skills\e2e-dev-harness\tests\test_kg_refresh.py
git commit -m "perf: avoid repeated Java entrypoint reads"
```

If the documentation change is made, include it with the smallest related commit or create:

```powershell
git add README.md docs skills\e2e-dev-harness
git commit -m "docs: clarify Windows command evidence paths"
```

## Self-Review

- Spec coverage: The plan maps verified P0/P1 audit findings to tasks and intentionally moves broad skill, legacy, and observability work into deferred plans.
- Placeholder scan: No task depends on unspecified future work.
- Type consistency: Function names match current code or are introduced in the task where first used.
