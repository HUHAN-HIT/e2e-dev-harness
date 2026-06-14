# Language Profile Test Runner Freshness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the proposed test-runner profile and evidence freshness design into the existing language-profile, evidence, and gate systems without creating a second profile source of truth or breaking active runs.

**Architecture:** `language-profile.json` remains the run-level profile artifact. Test-runner style, command templates, generated-runner policy, and suite policy are added as a `test` sub-block under each language profile. RED failure manifests become the RED-phase counterpart of `test_substance`: they share acceptance-contract parsing and AC id semantics, while command evidence gains optional v2 snapshot metadata for freshness checks.

**Tech Stack:** Python 3, pytest, existing `e2e_harness` CLI/core/adapters modules, JSON evidence artifacts, Git best-effort command metadata.

---

## Current Decisions

- Do not create a standalone `test-profile.json` as the primary contract.
- Add test-runner fields to `language-profile.json` under `profiles[].test`.
- Keep command evidence v1 valid.
- Add command evidence v2 fields additively.
- Add `red_failure_manifest` as optional in pipeline v1 and mandatory only in a new strict pipeline/version.
- Rename evidence suite scope to `suite.span` to avoid collision with delivery `scope_manifest`.
- Do not backfill existing command evidence; old runs remain v1/historical/unknown.

## Files

- Modify: `docs/superpowers/specs/2026-06-14-evidence-freshness-test-runner-design.md`
  - Align design with existing language profile and migration policy.
- Modify: `docs/superpowers/specs/2026-06-14-multilanguage-adaptation-design.md`
  - Remove stale statements about JS/TS test-substance support and cross-link runner/freshness ownership.
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/language/profile.py`
  - Extend generated and explicit language profiles with `profiles[].test`.
- Modify: `skills/e2e-dev-harness/tests/test_language_profile.py`
  - Cover default test-runner sub-profile, self-executing Python detection, and explicit-profile compatibility.
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/red_failure.py`
  - Validate RED failure manifests with shared acceptance-contract semantics.
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/validate.py`
  - Register `red_failure_manifest` as a structured key.
- Create: `skills/e2e-dev-harness/tests/test_red_failure_manifest.py`
  - Cover contract ids, signature matching, infrastructure failures, and right-reason blocking.
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/command_evidence.py`
  - Add optional v2 snapshot metadata and suite metadata.
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/freshness.py`
  - Compare command evidence snapshot metadata to the current repo state.
- Modify: `skills/e2e-dev-harness/tests/test_evidence_validation.py`
  - Cover command evidence v1 compatibility and v2 suite metadata validation.
- Create: `skills/e2e-dev-harness/tests/test_evidence_freshness.py`
  - Cover fresh, stale, historical, and unknown freshness outcomes.
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/core/lifecycle.py`
  - Keep v1 RED unchanged; do not make `red_failure_manifest` globally mandatory here.
- Create: `skills/e2e-dev-harness/pipelines/standard-v2.yaml`
  - Strict pipeline variant requiring RED `red_failure_manifest`.
- Modify: `skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py`
  - Cover the new v2 pipeline.
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/doctor.py`
  - Surface language profile test style and freshness status.
- Modify: `skills/e2e-dev-harness/tests/test_cli_doctor.py`
  - Cover freshness/status output.
- Modify: `skills/e2e-harness-tdd-red/SKILL.md`
  - Tell RED workers to use `profiles[].test`, write generated runners under run artifacts, and optionally submit RED manifests.
- Modify: `skills/e2e-harness-implementation/SKILL.md`
  - Tell implementation workers to preserve RED selected-test identity and produce `test_substance`.
- Modify: `skills/e2e-harness-completion/SKILL.md`
  - Tell completion workers to prefer current/fresh verification evidence.

---

### Task 1: Align Design Documents Before Code

**Files:**
- Modify: `docs/superpowers/specs/2026-06-14-evidence-freshness-test-runner-design.md`
- Modify: `docs/superpowers/specs/2026-06-14-multilanguage-adaptation-design.md`

- [ ] **Step 1: Add the ownership section to the freshness/test-runner design**

Insert after `## Design Overview`:

```markdown
## Relationship To Existing Language Profile

This design does not introduce a second run-level profile source of truth.
`language-profile.json` remains the authoritative profile artifact created at
run start and bound through `run-state.language.profile_path`.

The former `test-profile.json` concept is folded into each
`language-profile.json` profile entry under `profiles[].test`:

```json
{
  "language": "python",
  "roots": ["."],
  "test_runners": ["pytest", "unittest", "self-executing-python"],
  "package_managers": [],
  "capabilities": {
    "command_replay": true,
    "test_substance": true,
    "scope_scan": "module",
    "dependency_graph": false,
    "browser_evidence": "none"
  },
  "test": {
    "runner_styles": ["self-executing-python"],
    "command_templates": {
      "single_test": "python {path}",
      "feature_suite": "python docs/agent-runs/{run_id}/generated-runners/run_feature.py",
      "full_suite": "python docs/agent-runs/{run_id}/generated-runners/run_full.py"
    },
    "generated_runner": {
      "allowed": true,
      "preferred_directory": "docs/agent-runs/{run_id}/generated-runners",
      "may_write_to_tests": false
    },
    "suite_policy": {
      "red_required_span": "feature",
      "verified_required_span": "feature",
      "high_tier_verified_required_span": "full"
    }
  }
}
```

If a future implementation emits a separate test-profile artifact for operator
readability, it must be a derived view with a `language_profile_path` backpointer,
not an independent contract.
```

- [ ] **Step 2: Rename suite scope terminology in the design**

Replace each design use of `suite.scope` with `suite.span`.

Use this terminology section:

```markdown
## Terminology: Suite Span Versus Delivery Scope

`scope_manifest` is already a VERIFIED-phase delivery artifact. It describes
delivered product scope across services, tables, and phases.

Command evidence uses `suite.span` for test-suite breadth:

- `feature`: tests selected for the current acceptance slice.
- `full`: all known project tests for the active profile root.
- `smoke`: intentionally shallow confidence check.
- `manual-e2e`: externally executed evidence with explicit justification.

The harness must not call this field `suite.scope`, because it is unrelated to
delivery `scope_manifest`.
```

- [ ] **Step 3: Define RED manifest as test-substance counterpart**

Replace the first paragraph of `## RED Failure Manifest` with:

```markdown
`red_failure_manifest` is the RED-phase counterpart of `test_substance`.
Both artifacts share the same acceptance contract and the same AC id namespace.
The RED manifest proves that the failing command failed for acceptance-relevant
reasons; `test_substance` later proves that the same behavioral tests became
green and are non-empty.
```

Add validation notes:

```markdown
Validation reuses `acceptance.validate_contract(...)` and `acceptance.ids(...)`.
`items[].acceptance_id` must be one of the ids from the referenced contract.
`items[].test` must identify a test file or test name from the RED selected-test
set. RED does not require `green_tests`; batch parity remains owned by
`test_substance` at IMPLEMENTED.
```

- [ ] **Step 4: Write the migration policy**

Replace the migration plan with:

```markdown
## Migration Plan

1. Extend `language-profile.json` with `profiles[].test`; keep older profiles
   valid by treating a missing `test` block as conservative defaults.
2. Extend command evidence to v2 metadata while accepting v1 unchanged.
3. Add `red_failure_manifest` validation as an optional structured key.
4. Add a strict pipeline version, for example `standard-v2`, whose RED gate
   requires both `failing_tests` and `red_failure_manifest`.
5. Keep existing lifecycle RED gate as `failing_tests` only so active and legacy
   runs continue to pass under their stamped contracts.
6. Add doctor warnings for v1/unknown freshness and stale current evidence.
7. After one release, decide whether to move v2 behavior into default pipelines.
```

- [ ] **Step 5: Fix stale multilanguage text**

In `docs/superpowers/specs/2026-06-14-multilanguage-adaptation-design.md`,
replace the checkout fact that says `test_substance` accepts only Python and
Java with:

```markdown
- `test_substance` is the strongest current language-specific gate. Current
  implementation supports Python, Java, JavaScript, and TypeScript, with Python
  using AST analysis, Java using text heuristics, and JS/TS using the current
  JavaScript-like analyzer.
```

- [ ] **Step 6: Verify doc-only changes**

Run:

```bash
rg -n "test-profile.json|suite\.scope|only `python` and `java`|red_required_scope|verified_required_scope" docs/superpowers/specs/2026-06-14-*.md
git diff --check
```

Expected:

```text
No remaining primary-contract references to test-profile.json.
No suite.scope field names remain.
git diff --check exits 0.
```

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-06-14-evidence-freshness-test-runner-design.md docs/superpowers/specs/2026-06-14-multilanguage-adaptation-design.md
git commit -m "docs: align runner freshness design with language profile"
```

---

### Task 2: Extend Language Profile With Test Runner Policy

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/language/profile.py`
- Modify: `skills/e2e-dev-harness/tests/test_language_profile.py`

- [ ] **Step 1: Run required GitNexus impact check**

Run before editing:

```bash
npx gitnexus impact --target resolve_language_profile --direction upstream
```

Expected: review risk. If HIGH or CRITICAL, stop and warn before editing.

- [ ] **Step 2: Write failing tests for test sub-profile defaults**

Append to `skills/e2e-dev-harness/tests/test_language_profile.py`:

```python
def test_python_profile_includes_test_runner_policy(tmp_path):
    _write(tmp_path / "pyproject.toml", "[project]\nname='demo'\n")
    _write(tmp_path / "tests" / "test_cli.py", "def test_cli(): assert True\n")

    prof = lp.resolve_language_profile(tmp_path, domain_hint="backend")

    py = prof["profiles"][0]
    assert py["language"] == "python"
    assert "pytest" in py["test_runners"]
    assert py["test"]["runner_styles"] == ["pytest", "unittest"]
    assert py["test"]["command_templates"]["single_test"] == "python -m pytest {path}"
    assert py["test"]["generated_runner"]["preferred_directory"] == (
        "docs/agent-runs/{run_id}/generated-runners"
    )
    assert py["test"]["suite_policy"]["red_required_span"] == "feature"


def test_self_executing_python_profile_detects_script_style(tmp_path):
    _write(tmp_path / "pyproject.toml", "[project]\nname='demo'\n")
    _write(
        tmp_path / "tests" / "test_cache_stats.py",
        "import sys\n"
        "def main():\n"
        "    return 1\n"
        "if __name__ == '__main__':\n"
        "    sys.exit(main())\n",
    )

    prof = lp.resolve_language_profile(tmp_path, domain_hint="backend")

    py = prof["profiles"][0]
    assert "self-executing-python" in py["test_runners"]
    assert py["test"]["runner_styles"][0] == "self-executing-python"
    assert py["test"]["command_templates"]["single_test"] == "python {path}"
    assert py["test"]["generated_runner"]["may_write_to_tests"] is False
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest skills/e2e-dev-harness/tests/test_language_profile.py -q
```

Expected:

```text
FAILED test_python_profile_includes_test_runner_policy
FAILED test_self_executing_python_profile_detects_script_style
```

- [ ] **Step 4: Add test policy helpers**

In `profile.py`, add helper functions after `_domain_matches`:

```python
def _test_policy(repo: Path, language: str, runners: list[str], roots: list[str]) -> dict:
    runner_styles = list(runners)
    if language == "python" and _has_self_executing_python_tests(repo, roots):
        runner_styles = ["self-executing-python", *[r for r in runner_styles if r != "self-executing-python"]]
    templates = _command_templates(language, runner_styles)
    return {
        "runner_styles": runner_styles,
        "command_templates": templates,
        "generated_runner": {
            "allowed": language in {"python", "javascript", "typescript"},
            "preferred_directory": "docs/agent-runs/{run_id}/generated-runners",
            "may_write_to_tests": False,
        },
        "suite_policy": {
            "red_required_span": "feature",
            "verified_required_span": "feature",
            "high_tier_verified_required_span": "full",
        },
    }


def _command_templates(language: str, runner_styles: list[str]) -> dict:
    primary = runner_styles[0] if runner_styles else "custom"
    if language == "python" and primary == "self-executing-python":
        single = "python {path}"
    elif language == "python":
        single = "python -m pytest {path}"
    elif language in {"javascript", "typescript"}:
        single = "npm test -- {path}"
    elif language == "java":
        single = "mvn test -Dtest={test_name}"
    else:
        single = "{command}"
    return {
        "single_test": single,
        "feature_suite": "python docs/agent-runs/{run_id}/generated-runners/run_feature.py",
        "full_suite": "python docs/agent-runs/{run_id}/generated-runners/run_full.py",
    }


def _has_self_executing_python_tests(repo: Path, roots: list[str]) -> bool:
    for root in roots:
        base = repo / root if root != "." else repo
        if not base.exists():
            continue
        for path in base.rglob("test*.py"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "if __name__" in text and "sys.exit" in text:
                return True
    return False
```

- [ ] **Step 5: Wire helper into `_profile`**

Change `_profile` signature:

```python
def _profile(language: str, roots: list[str], *, test_substance: bool = True,
             scope_scan: str | None = None, repo: Path | None = None) -> dict:
```

Inside `_profile`, after `runners` is initialized:

```python
    if language == "python" and repo is not None and _has_self_executing_python_tests(repo, roots):
        runners = ["self-executing-python", *runners]
```

Return object should include:

```python
        "test": _test_policy(repo or Path("."), language, runners, roots),
```

Update calls in `resolve_language_profile` to pass `repo=repo`:

```python
generic = _profile("unknown", ["."], test_substance=False, scope_scan="none", repo=repo)
```

and in `_detect_candidate` where `_profile(...)` is called:

```python
profile = _profile(language, roots, repo=repo)
```

- [ ] **Step 6: Keep explicit profiles compatible**

Add this normalization in `_read_profile` after loading JSON:

```python
    for profile in doc.get("profiles", []) if isinstance(doc.get("profiles"), list) else []:
        if isinstance(profile, dict) and "test" not in profile:
            runners = profile.get("test_runners") if isinstance(profile.get("test_runners"), list) else []
            roots = profile.get("roots") if isinstance(profile.get("roots"), list) else ["."]
            profile["test"] = _test_policy(path.parent, profile.get("language", "unknown"), runners, roots)
```

- [ ] **Step 7: Run tests**

Run:

```bash
pytest skills/e2e-dev-harness/tests/test_language_profile.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 8: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/adapters/language/profile.py skills/e2e-dev-harness/tests/test_language_profile.py
git commit -m "feat: add test runner policy to language profiles"
```

---

### Task 3: Add RED Failure Manifest Validation

**Files:**
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/red_failure.py`
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/validate.py`
- Create: `skills/e2e-dev-harness/tests/test_red_failure_manifest.py`

- [ ] **Step 1: Run required GitNexus impact check**

Run before editing:

```bash
npx gitnexus impact --target validate_evidence --direction upstream
```

Expected: review risk. If HIGH or CRITICAL, stop and warn before editing.

- [ ] **Step 2: Write failing tests**

Create `skills/e2e-dev-harness/tests/test_red_failure_manifest.py`:

```python
import json

from e2e_harness.adapters.evidence import red_failure


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _contract(repo):
    path = repo / "docs" / "agent-runs" / "r" / "CLARIFIED-acceptance_contract.json"
    _write(path, {
        "schema": "e2e-dev-harness.acceptance-contract.v1",
        "items": [{"id": "AC-001", "text": "emits cache stats", "status": "accepted"}],
        "questions": [],
    })
    return path.relative_to(repo).as_posix()


def _command(repo):
    path = repo / "docs" / "agent-runs" / "r" / "red" / "failing_tests.json"
    _write(path, {
        "schema": "e2e-dev-harness.command-evidence.v1",
        "command": "python tests/test_cache_stats.py",
        "argv": ["python", "tests/test_cache_stats.py"],
        "cwd": str(repo),
        "started_at": "2026-06-14T00:00:00Z",
        "finished_at": "2026-06-14T00:00:01Z",
        "elapsed_ms": 1000,
        "exit_code": 1,
        "stdout_tail": "cache stats emitted: 0",
        "stderr_tail": "",
        "stdout_sha256": "0" * 64,
        "stderr_sha256": "1" * 64,
        "environment": {"python": "3.12", "platform": "win32"},
    })
    return path.relative_to(repo).as_posix()


def test_red_failure_manifest_accepts_contract_id_and_signature(tmp_path):
    contract = _contract(tmp_path)
    command = _command(tmp_path)
    manifest = {
        "schema": red_failure.SCHEMA,
        "acceptance_contract_path": contract,
        "command_evidence": command,
        "items": [{
            "acceptance_id": "AC-001",
            "test": "tests/test_cache_stats.py",
            "expected_failure_kind": "missing_observability_event",
            "observed_failure_signature": "cache stats emitted: 0",
            "right_reason": True,
        }],
        "infrastructure_failures": [],
    }

    ok, reason = red_failure.validate_red_failure_manifest(manifest, tmp_path)

    assert ok is True
    assert reason is None


def test_red_failure_manifest_rejects_unknown_acceptance_id(tmp_path):
    contract = _contract(tmp_path)
    command = _command(tmp_path)
    manifest = {
        "schema": red_failure.SCHEMA,
        "acceptance_contract_path": contract,
        "command_evidence": command,
        "items": [{
            "acceptance_id": "AC-999",
            "test": "tests/test_cache_stats.py",
            "expected_failure_kind": "missing_observability_event",
            "observed_failure_signature": "cache stats emitted: 0",
            "right_reason": True,
        }],
        "infrastructure_failures": [],
    }

    ok, reason = red_failure.validate_red_failure_manifest(manifest, tmp_path)

    assert ok is False
    assert reason == "unknown-acceptance-id:AC-999"


def test_red_failure_manifest_rejects_wrong_reason(tmp_path):
    contract = _contract(tmp_path)
    command = _command(tmp_path)
    manifest = {
        "schema": red_failure.SCHEMA,
        "acceptance_contract_path": contract,
        "command_evidence": command,
        "items": [{
            "acceptance_id": "AC-001",
            "test": "tests/test_cache_stats.py",
            "expected_failure_kind": "missing_observability_event",
            "observed_failure_signature": "cache stats emitted: 0",
            "right_reason": False,
        }],
        "infrastructure_failures": [],
    }

    ok, reason = red_failure.validate_red_failure_manifest(manifest, tmp_path)

    assert ok is False
    assert reason == "wrong-reason:AC-001"
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest skills/e2e-dev-harness/tests/test_red_failure_manifest.py -q
```

Expected:

```text
ImportError or ModuleNotFoundError for red_failure
```

- [ ] **Step 4: Implement validator**

Create `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/red_failure.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from e2e_harness.core import acceptance

SCHEMA = "e2e-dev-harness.red-failure-manifest.v1"


def _read_json(repo_root, rel: str):
    full = Path(rel)
    if not full.is_absolute():
        full = Path(repo_root) / rel
    if not full.is_file():
        return None, full
    try:
        return json.loads(full.read_text(encoding="utf-8")), full
    except ValueError:
        return False, full


def validate_red_failure_manifest(obj, repo_root) -> tuple[bool, str | None]:
    if not isinstance(obj, dict):
        return False, "not-object"
    if obj.get("schema") != SCHEMA:
        return False, "bad-schema"
    contract_path = obj.get("acceptance_contract_path")
    if not contract_path:
        return False, "no-contract-path"
    contract, _full = _read_json(repo_root, contract_path)
    if contract is None:
        return False, "contract-not-found"
    if contract is False:
        return False, "contract-not-json"
    ok, reason = acceptance.validate_contract(contract)
    if not ok:
        return False, f"bad-contract:{reason}"
    ids = set(acceptance.ids(contract))

    command_path = obj.get("command_evidence")
    if not command_path:
        return False, "no-command-evidence"
    command, _cmd_full = _read_json(repo_root, command_path)
    if command is None:
        return False, "command-evidence-not-found"
    if command is False:
        return False, "command-evidence-not-json"
    combined_output = f"{command.get('stdout_tail', '')}\n{command.get('stderr_tail', '')}"

    infra = obj.get("infrastructure_failures")
    if not isinstance(infra, list):
        return False, "bad-infrastructure-failures"
    if infra:
        return False, "infrastructure-failures"

    items = obj.get("items")
    if not isinstance(items, list) or not items:
        return False, "no-items"
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            return False, "bad-item"
        ac_id = item.get("acceptance_id")
        if ac_id not in ids:
            return False, f"unknown-acceptance-id:{ac_id}"
        seen.add(ac_id)
        if item.get("right_reason") is not True:
            return False, f"wrong-reason:{ac_id}"
        test = item.get("test")
        if not isinstance(test, str) or not test:
            return False, f"bad-test:{ac_id}"
        signature = item.get("observed_failure_signature")
        if not isinstance(signature, str) or not signature:
            return False, f"bad-signature:{ac_id}"
        if signature not in combined_output:
            return False, f"signature-not-found:{ac_id}"
    for ac_id in ids:
        if ac_id not in seen:
            return False, f"uncovered:{ac_id}"
    return True, None
```

- [ ] **Step 5: Register structured key**

Modify imports in `validate.py`:

```python
from e2e_harness.adapters.evidence import (
    adversarial, audit_replay, command_evidence, dispatch_invocation, hashing,
    red_failure, substance,
)
```

Add to `STRUCTURED_KEYS`:

```python
    "red_failure_manifest": red_failure.validate_red_failure_manifest,
```

- [ ] **Step 6: Run tests**

Run:

```bash
pytest skills/e2e-dev-harness/tests/test_red_failure_manifest.py skills/e2e-dev-harness/tests/test_evidence_validation.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 7: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/red_failure.py skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/validate.py skills/e2e-dev-harness/tests/test_red_failure_manifest.py
git commit -m "feat: validate red failure manifests"
```

---

### Task 4: Add Command Evidence v2 Snapshot Metadata

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/command_evidence.py`
- Create: `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/freshness.py`
- Create: `skills/e2e-dev-harness/tests/test_evidence_freshness.py`
- Modify: `skills/e2e-dev-harness/tests/test_evidence_validation.py`

- [ ] **Step 1: Run required GitNexus impact check**

Run before editing:

```bash
npx gitnexus impact --target record_command --direction upstream
```

Expected: review risk. If HIGH or CRITICAL, stop and warn before editing.

- [ ] **Step 2: Write freshness tests**

Create `skills/e2e-dev-harness/tests/test_evidence_freshness.py`:

```python
from e2e_harness.adapters.evidence import freshness


def test_freshness_unknown_when_git_unavailable(tmp_path):
    evidence = {
        "schema": "e2e-dev-harness.command-evidence.v2",
        "git": {"available": False},
    }

    result = freshness.evaluate_freshness(tmp_path, evidence)

    assert result["status"] == "unknown"
    assert result["reason"] == "git-unavailable"


def test_freshness_historical_is_respected(tmp_path):
    evidence = {
        "schema": "e2e-dev-harness.command-evidence.v2",
        "historical": True,
        "git": {"available": False},
    }

    result = freshness.evaluate_freshness(tmp_path, evidence)

    assert result["status"] == "historical"


def test_input_hash_change_is_stale(tmp_path):
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("print('v1')\n", encoding="utf-8")
    old_hash = freshness.sha256_file(target)
    target.write_text("print('v2')\n", encoding="utf-8")
    evidence = {
        "schema": "e2e-dev-harness.command-evidence.v2",
        "git": {"available": False},
        "inputs": [{"path": "src/app.py", "sha256": old_hash}],
    }

    result = freshness.evaluate_freshness(tmp_path, evidence)

    assert result["status"] == "stale"
    assert result["reason"] == "input-hash-mismatch:src/app.py"
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest skills/e2e-dev-harness/tests/test_evidence_freshness.py -q
```

Expected:

```text
ImportError or ModuleNotFoundError for freshness
```

- [ ] **Step 4: Implement freshness module**

Create `skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/freshness.py`:

```python
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def git_snapshot(repo: str | Path) -> dict:
    repo = Path(repo)
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
            capture_output=True, check=False, timeout=10,
        )
        if head.returncode != 0:
            return {"available": False}
        status = subprocess.run(
            ["git", "status", "--porcelain=v1"], cwd=repo, text=True,
            capture_output=True, check=False, timeout=10,
        )
        diff = subprocess.run(
            ["git", "diff", "--binary"], cwd=repo, text=True,
            capture_output=True, check=False, timeout=30,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--binary"], cwd=repo, text=True,
            capture_output=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False}
    return {
        "available": True,
        "head": head.stdout.strip(),
        "status_porcelain_hash": sha256_text(status.stdout or ""),
        "diff_hash": sha256_text((diff.stdout or "") + "\n" + (staged.stdout or "")),
    }


def input_hashes(repo: str | Path, inputs: list[str] | None) -> list[dict]:
    if not inputs:
        return []
    repo = Path(repo)
    out = []
    for rel in inputs:
        full = repo / rel
        if full.is_file():
            out.append({"path": rel, "sha256": sha256_file(full)})
        else:
            out.append({"path": rel, "missing": True})
    return out


def evaluate_freshness(repo: str | Path, evidence: dict) -> dict:
    if evidence.get("historical") is True:
        return {"status": "historical"}
    for item in evidence.get("inputs") or []:
        rel = item.get("path")
        expected = item.get("sha256")
        if not rel or not expected:
            continue
        full = Path(repo) / rel
        if not full.is_file():
            return {"status": "stale", "reason": f"input-missing:{rel}"}
        if sha256_file(full) != expected:
            return {"status": "stale", "reason": f"input-hash-mismatch:{rel}"}
    git = evidence.get("git") if isinstance(evidence.get("git"), dict) else {}
    if git.get("available") is False:
        return {"status": "unknown", "reason": "git-unavailable"}
    current = git_snapshot(repo)
    if current.get("available") is False:
        return {"status": "unknown", "reason": "git-unavailable"}
    for key in ("head", "status_porcelain_hash", "diff_hash"):
        if git.get(key) and git.get(key) != current.get(key):
            return {"status": "stale", "reason": f"git-{key}-mismatch"}
    return {"status": "fresh"}
```

- [ ] **Step 5: Extend record_command signature and payload**

In `command_evidence.py`, import freshness:

```python
from e2e_harness.adapters.evidence import freshness
```

Change function signature:

```python
def record_command(repo: str | Path, command: str,
                   timeout: int = DEFAULT_TIMEOUT_SECONDS, *,
                   suite: dict | None = None,
                   inputs: list[str] | None = None,
                   phase: str | None = None,
                   historical: bool | None = None) -> dict:
```

Before returning success payload, create:

```python
    snapshot = freshness.git_snapshot(repo)
    input_records = freshness.input_hashes(repo, inputs)
    schema = "e2e-dev-harness.command-evidence.v2" if (
        suite is not None or inputs is not None or phase is not None or historical is not None
    ) else COMMAND_EVIDENCE_SCHEMA
```

Change return payload start:

```python
        "schema": schema, "command": command, "argv": argv,
```

Add optional fields before return:

```python
    if schema.endswith(".v2"):
        payload["git"] = snapshot
        payload["inputs"] = input_records
        if suite is not None:
            payload["suite"] = suite
        if phase is not None:
            payload["phase"] = phase
        if historical is not None:
            payload["historical"] = historical
```

This requires assigning the dict to `payload` instead of returning it directly.

- [ ] **Step 6: Accept v2 command evidence**

In `command_evidence.py`, change `is_command_evidence` to:

```python
def is_command_evidence(obj) -> bool:
    return (
        isinstance(obj, dict)
        and obj.get("schema") in {COMMAND_EVIDENCE_SCHEMA, "e2e-dev-harness.command-evidence.v2"}
        and "command" in obj
        and "exit_code" in obj
    )
```

- [ ] **Step 7: Run tests**

Run:

```bash
pytest skills/e2e-dev-harness/tests/test_evidence_freshness.py skills/e2e-dev-harness/tests/test_evidence_validation.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 8: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/command_evidence.py skills/e2e-dev-harness/scripts/e2e_harness/adapters/evidence/freshness.py skills/e2e-dev-harness/tests/test_evidence_freshness.py skills/e2e-dev-harness/tests/test_evidence_validation.py
git commit -m "feat: add command evidence freshness metadata"
```

---

### Task 5: Add Strict Pipeline Without Breaking Existing Runs

**Files:**
- Create: `skills/e2e-dev-harness/pipelines/standard-v2.yaml`
- Modify: `skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py`

- [ ] **Step 1: Create strict pipeline fixture**

Create `skills/e2e-dev-harness/pipelines/standard-v2.yaml`:

```yaml
schema: e2e-dev-harness.pipeline.v1
name: standard-v2
phases:
  - name: CREATED
  - name: CLARIFIED
    produces: [clarification, acceptance_contract]
    exit_gate: [clarification, acceptance_contract]
  - name: PLANNED
    produces: [plan, module_plan]
    exit_gate: [plan, module_plan]
  - name: RED
    produces: [failing_tests, red_failure_manifest]
    exit_gate: [failing_tests, red_failure_manifest]
  - name: IMPLEMENTED
    produces: [passing_tests, test_substance]
    exit_gate: [passing_tests, test_substance]
  - name: REVIEWED
    produces: [review]
    exit_gate: [review]
  - name: VERIFIED
    produces: [verification, scope_manifest]
    exit_gate: [verification, scope_manifest]
```

- [ ] **Step 2: Write pipeline loading test**

Append to `skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py`:

```python
def test_standard_v2_requires_red_failure_manifest():
    spec = pipeline.load_spec("standard-v2")
    spine = pipeline.build_spine_from_spec(spec)
    red = next(p for p in spine if p.name == "RED")

    assert red.produces == ("failing_tests", "red_failure_manifest")
    assert red.exit_gate == ("failing_tests", "red_failure_manifest")
```

- [ ] **Step 3: Run tests**

Run:

```bash
pytest skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py skills/e2e-dev-harness/tests/test_gates.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 4: Commit**

```bash
git add skills/e2e-dev-harness/pipelines/standard-v2.yaml skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py
git commit -m "feat: add standard v2 red manifest gate"
```

---

### Task 6: Add Doctor Freshness Reporting

**Files:**
- Modify: `skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/doctor.py`
- Modify: `skills/e2e-dev-harness/tests/test_cli_doctor.py`

- [ ] **Step 1: Write doctor test**

Append to `skills/e2e-dev-harness/tests/test_cli_doctor.py`:

```python
def test_doctor_reports_command_evidence_freshness(tmp_path):
    evidence = tmp_path / "docs" / "agent-runs" / "r" / "evidence" / "verification.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps({
        "schema": "e2e-dev-harness.command-evidence.v2",
        "command": "python -m pytest",
        "argv": ["python", "-m", "pytest"],
        "cwd": str(tmp_path),
        "exit_code": 0,
        "stdout_sha256": "0" * 64,
        "stderr_sha256": "1" * 64,
        "environment": {"python": "3.12", "platform": "win32"},
        "git": {"available": False},
        "suite": {"span": "feature", "selected_tests": ["tests/test_x.py"]},
    }), encoding="utf-8")
    state = tmp_path / "docs" / "agent-runs" / "r" / "run-state.json"
    state.write_text(json.dumps({
        "schema": "e2e-dev-harness.run-state.v1",
        "run_id": "r",
        "current_phase": "VERIFIED",
        "phases": {
            "VERIFIED": {
                "evidence": {"verification": {"path": str(evidence.relative_to(tmp_path))}}
            }
        },
    }), encoding="utf-8")

    result = doctor.inspect_run(tmp_path, state)

    assert result["evidence_freshness"]["VERIFIED.verification"]["status"] == "unknown"
    assert result["evidence_freshness"]["VERIFIED.verification"]["suite_span"] == "feature"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest skills/e2e-dev-harness/tests/test_cli_doctor.py::test_doctor_reports_command_evidence_freshness -q
```

Expected:

```text
AttributeError, KeyError, or assertion failure because doctor does not report freshness yet.
```

- [ ] **Step 3: Implement doctor helper**

In `doctor.py`, import:

```python
from e2e_harness.adapters.evidence import command_evidence, freshness
```

Add helper:

```python
def _evidence_freshness(repo_root: Path, state: dict) -> dict:
    out = {}
    for phase_name, phase_rec in (state.get("phases") or {}).items():
        evidence = phase_rec.get("evidence") or {}
        for key, entry in evidence.items():
            path = entry.get("path") if isinstance(entry, dict) else entry
            if not path:
                continue
            full = Path(path)
            if not full.is_absolute():
                full = repo_root / full
            try:
                obj = json.loads(full.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not command_evidence.is_command_evidence(obj):
                continue
            status = freshness.evaluate_freshness(repo_root, obj)
            suite = obj.get("suite") if isinstance(obj.get("suite"), dict) else {}
            status["suite_span"] = suite.get("span")
            out[f"{phase_name}.{key}"] = status
    return out
```

In the main inspection result, add:

```python
    result["evidence_freshness"] = _evidence_freshness(repo_root, state)
```

- [ ] **Step 4: Run doctor tests**

Run:

```bash
pytest skills/e2e-dev-harness/tests/test_cli_doctor.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness/scripts/e2e_harness/cli/commands/doctor.py skills/e2e-dev-harness/tests/test_cli_doctor.py
git commit -m "feat: report evidence freshness in doctor"
```

---

### Task 7: Update Worker Instructions

**Files:**
- Modify: `skills/e2e-harness-tdd-red/SKILL.md`
- Modify: `skills/e2e-harness-implementation/SKILL.md`
- Modify: `skills/e2e-harness-completion/SKILL.md`

- [ ] **Step 1: Update RED worker instructions**

Add to `skills/e2e-harness-tdd-red/SKILL.md`:

```markdown
## Test Runner Profile

When `context_paths` includes `language-profile.json`, read it before choosing
test commands. Use `profiles[].test.runner_styles` and
`profiles[].test.command_templates`; do not invent a runner that contradicts
the active profile.

Generated runners belong under:

```text
docs/agent-runs/<run_id>/generated-runners/
```

Do not write generated runner plumbing into `tests/` unless
`profiles[].test.generated_runner.may_write_to_tests` is true.

If the active pipeline expects `red_failure_manifest`, submit it with the same
acceptance ids from the CLARIFIED acceptance contract. `right_reason` must be
true only when the observed failure signature is acceptance-relevant rather than
an infrastructure or runner failure.
```

- [ ] **Step 2: Update implementation worker instructions**

Add to `skills/e2e-harness-implementation/SKILL.md`:

```markdown
## RED To GREEN Test Identity

When RED supplied a `red_failure_manifest`, use the same acceptance ids and test
identity when producing `test_substance`. RED proves the selected behavior fails;
IMPLEMENTED proves the same behavior is green and non-empty.

Do not replace the RED selected tests with unrelated broader tests unless you
also preserve the original selected-test evidence.
```

- [ ] **Step 3: Update completion worker instructions**

Add to `skills/e2e-harness-completion/SKILL.md`:

```markdown
## Fresh Verification Evidence

Prefer command evidence that is current for the worktree. If command evidence
contains freshness metadata and doctor reports it as stale, rerun verification
or explain why the evidence is intentionally `manual-e2e` or `external`.
```

- [ ] **Step 4: Run skill doc tests**

Run:

```bash
pytest skills/e2e-dev-harness/tests/test_skill_md.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-harness-tdd-red/SKILL.md skills/e2e-harness-implementation/SKILL.md skills/e2e-harness-completion/SKILL.md
git commit -m "docs: teach workers profile-aware test evidence"
```

---

### Task 8: Full Regression And GitNexus Change Detection

**Files:**
- No source edits unless prior tasks reveal a failure.

- [ ] **Step 1: Run focused regression**

Run:

```bash
pytest skills/e2e-dev-harness/tests/test_language_profile.py \
       skills/e2e-dev-harness/tests/test_red_failure_manifest.py \
       skills/e2e-dev-harness/tests/test_evidence_freshness.py \
       skills/e2e-dev-harness/tests/test_evidence_validation.py \
       skills/e2e-dev-harness/tests/test_pipeline_yaml_load.py \
       skills/e2e-dev-harness/tests/test_cli_doctor.py \
       skills/e2e-dev-harness/tests/test_skill_md.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 2: Run broader harness tests**

Run:

```bash
pytest skills/e2e-dev-harness/tests -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 3: Run GitNexus detect changes before final commit or PR**

Run:

```bash
npx gitnexus detect-changes --scope all
```

Expected:

```text
Changed symbols are limited to language profile, evidence validation, command evidence, doctor, pipeline, and worker docs.
No unexpected execution-flow blast radius.
```

- [ ] **Step 4: Run diff hygiene**

Run:

```bash
git diff --check
```

Expected:

```text
no whitespace errors
```

- [ ] **Step 5: Final integration commit if needed**

If prior tasks were not committed separately, commit all remaining changes:

```bash
git add docs/superpowers/specs/2026-06-14-evidence-freshness-test-runner-design.md \
        docs/superpowers/specs/2026-06-14-multilanguage-adaptation-design.md \
        skills/e2e-dev-harness/scripts/e2e_harness \
        skills/e2e-dev-harness/tests \
        skills/e2e-dev-harness/pipelines/standard-v2.yaml \
        skills/e2e-harness-tdd-red/SKILL.md \
        skills/e2e-harness-implementation/SKILL.md \
        skills/e2e-harness-completion/SKILL.md
git commit -m "feat: add profile-aware evidence freshness"
```

---

## Self-Review

- Spec coverage: The plan covers profile ownership, RED manifest/test-substance relationship, suite terminology, freshness metadata, gate compatibility, first slice, doctor output, and worker instructions.
- Placeholder scan: No unresolved placeholders or undefined implementation steps are intentionally left.
- Type consistency: The plan consistently uses `profiles[].test`, `suite.span`, `red_failure_manifest`, `acceptance_contract_path`, and `command_evidence`.
- Risk controls: Each symbol-editing task starts with GitNexus impact analysis. The final task requires GitNexus detect-changes before commit/PR.
