# Harness v2 — M2 Backend-Complete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (chosen) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the v2 harness gates validate real artifacts, finish the two remaining worker-skill delegators, and add tier-scaled pipelines (standard/critical/audited) with r1/r2/r3 review fan-out — plus cheap SSOT-robustness and navigation/dispatch enrichments.

**Architecture:** Keep the SSOT single `run-state.json` + declarative spine. Gates gain a `repo_root` so they can verify the artifact a worker actually produced (exists + non-empty + hash + command-evidence for test keys). Pipelines become a small structured map (phase list + per-phase gate overrides) keyed by tier; the navigation map and dispatch packet derive everything from that. Clean leaves (`sha256`, `command_evidence`, `task_tier` classification) are ported behind narrow `adapters/` interfaces with their tests; heavy leaves (scanner/KG/memory/runtime) are explicitly deferred per design §16.

**Tech Stack:** Python 3 (stdlib only), pytest. No new third-party deps.

**Scope (confirmed):** R1, R1', L1, L2, L5–L7, tier pipelines + review fan-out, §4 all-tier closure seed, ports required by R1 (`hashing`, `command_evidence`) + `task_tier` classification. **Out of scope (deferred):** porting scanner / KG-evidence / memory / runtime-adapter leaves (design §16 "不整体搬运").

**Shared contracts (keep identical across tasks):**
- Evidence entry stored by `submit`: `{"path": str, "sha256": str | None, "bytes": int | None}` (legacy bare-string entries still accepted by validators).
- `harness_v2.adapters.evidence.hashing.sha256_file(path: Path) -> str`
- `harness_v2.adapters.evidence.command_evidence.record_command(repo: Path, command: str, timeout: int = 600) -> dict`; `COMMAND_EVIDENCE_SCHEMA = "e2e-dev-harness-v2.command-evidence.v1"`; `is_command_evidence(obj) -> bool`
- `harness_v2.adapters.evidence.validate.validate_evidence(repo_root, key, entry) -> tuple[bool, str | None]`; `COMMAND_KEYS = {"failing_tests": "nonzero", "passing_tests": "zero"}`
- `gates.gate_passes(phase, phase_record, repo_root=None) -> tuple[bool, list[str]]`
- `engine.submit_evidence(state, phase_name, key, path, *, repo_root=None, status="done", reason=None) -> None`
- `engine.evaluate(spine, state, repo_root=None) -> dict`
- `navigation.navigation_map(spine, state, repo_root=None) -> dict`
- `lifecycle.build_spine(phase_names, overrides=None) -> list[Phase]`
- `pipeline.build_spine(name) -> list[Phase]`, `pipeline.active_phase_names(name)`, `pipeline.PIPELINES`
- `dispatch.DispatchStatus.FAILED` (already exists)

**Conventions:** All paths below are relative to repo root `skill-skill-superpowers-skill-tdd-graphify`. The harness package lives under `skills/e2e-dev-harness-v2/scripts/harness_v2/`; tests under `skills/e2e-dev-harness-v2/tests/`. Run tests from the harness dir:

```bash
cd skills/e2e-dev-harness-v2 && python -m pytest -q
```

**Per-CLAUDE.md:** the v2 package is a new tree the GitNexus index (`e2e-dev-workflow`, 8562 symbols) does not cover; `gitnexus_impact` will not resolve v2 symbols. The only edits to *indexed legacy* symbols are read-only ports (copy logic into new files) — we never modify `skills/e2e-dev-harness/scripts/*`. Before each task that ports legacy logic, run `gitnexus_impact({target:"<symbol>", direction:"upstream"})` on the **legacy source symbol** (`sha256`, `run_command`, `gates_for`) to confirm no in-place edit is implied; report the blast radius. Run `gitnexus_detect_changes()` before the final commit of each task that touches code.

---

## Baseline

- [ ] **Step 0: Confirm green baseline (25 passed)**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: all tests pass (spec says 25). If not, stop and report — do not build on red.

---

## Task 1: Cheap SSOT robustness (L5 schema check, L6 atomic write, L7 CLI JSON guard)

Smallest, highest-leverage; protects the single source of truth. Do first.

**Files:**
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/core/run_state.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/main.py`
- Test: `skills/e2e-dev-harness-v2/tests/test_run_state.py` (extend)
- Test: `skills/e2e-dev-harness-v2/tests/test_cli_error_json.py` (new)

- [ ] **Step 1: Write failing tests for run_state L5/L6**

Append to `tests/test_run_state.py`:

```python
import json
import pytest
from pathlib import Path


def test_load_rejects_schema_mismatch(tmp_path):
    from harness_v2.core import run_state
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema": "wrong", "run_id": "x"}), encoding="utf-8")
    with pytest.raises(ValueError) as ei:
        run_state.load(p)
    assert "schema" in str(ei.value)


def test_save_is_atomic_no_partial_on_replace(tmp_path):
    from harness_v2.core import run_state
    st = run_state.new_run_state("r1", "feat", "req")
    p = tmp_path / "run-state.json"
    run_state.save(p, st)
    # no leftover temp file beside the target
    leftovers = [q.name for q in tmp_path.iterdir() if q.name != "run-state.json"]
    assert leftovers == []
    assert run_state.load(p)["run_id"] == "r1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_run_state.py -q`
Expected: FAIL — `test_load_rejects_schema_mismatch` (no ValueError raised). The atomic test may already pass; the load test must fail.

- [ ] **Step 3: Implement L5 + L6 in `run_state.py`**

Replace the whole file with:

```python
"""SSOT run-state: one JSON file, versioned schema, atomic writes."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "e2e-dev-harness-v2.run-state.v1"


def _stamp(now: str | None = None) -> str:
    if now:
        return now
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def new_run_state(run_id: str, feature: str, request: str,
                  tier: str = "minimal", pipeline: str = "minimal",
                  now: str | None = None) -> dict:
    ts = _stamp(now)
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "feature": feature,
        "request": request,
        "tier": tier,
        "pipeline": pipeline,
        "current_phase": "CREATED",
        "phases": {},
        "created_at": ts,
        "updated_at": ts,
    }


def load(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    got = data.get("schema")
    if got != SCHEMA:
        raise ValueError(
            f"run-state schema mismatch: expected {SCHEMA!r}, got {got!r}"
        )
    return data


def save(path: str | Path, state: dict, now: str | None = None) -> None:
    state = dict(state)
    state["updated_at"] = _stamp(now)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, indent=2, ensure_ascii=False)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)
```

- [ ] **Step 4: Run run_state tests to verify pass**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_run_state.py -q`
Expected: PASS (all, including new).

- [ ] **Step 5: Write failing test for L7 (CLI always emits JSON)**

Create `tests/test_cli_error_json.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness_v2.py"


def test_unknown_pipeline_emits_json_not_traceback(tmp_path):
    # craft a valid-schema state whose pipeline does not exist
    from harness_v2.core import run_state
    st = run_state.new_run_state("r1", "f", "r", tier="bogus", pipeline="bogus")
    p = tmp_path / "run-state.json"
    run_state.save(p, st)
    proc = subprocess.run(
        [sys.executable, str(ENTRY), "next", "--state", str(p), "--repo", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode != 0
    # stdout must still be parseable JSON carrying an error — the "every command emits JSON" contract
    payload = json.loads(proc.stdout or "{}")
    assert "error" in payload
    assert "bogus" in payload["error"]
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_cli_error_json.py -q`
Expected: FAIL — `json.loads` raises because stdout is an uncaught traceback (empty stdout).

- [ ] **Step 7: Implement L7 guard in `cli/main.py`**

Replace `main()` in `cli/main.py` with:

```python
def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        code, result = _COMMANDS[args.command](args)
    except Exception as exc:  # noqa: BLE001 — contract: every command emits JSON
        sys.stdout.write(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return code
```

- [ ] **Step 8: Run full suite to verify green**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: PASS (baseline + new tests).

- [ ] **Step 9: Commit**

```bash
git add skills/e2e-dev-harness-v2/scripts/harness_v2/core/run_state.py \
        skills/e2e-dev-harness-v2/scripts/harness_v2/cli/main.py \
        skills/e2e-dev-harness-v2/tests/test_run_state.py \
        skills/e2e-dev-harness-v2/tests/test_cli_error_json.py
git commit -m "feat(harness-v2): SSOT robustness — schema check, atomic save, CLI JSON guard (L5-L7)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Port evidence leaves — `hashing` + `command_evidence` (R1 prerequisite)

Copy clean logic from legacy `artifact_registry.sha256` and `command_evidence.run_command` into narrow v2 adapters, with their own tests. No legacy file is modified.

**Pre-task KG:** run `gitnexus_impact({target:"sha256", direction:"upstream"})` and `gitnexus_impact({target:"run_command", direction:"upstream"})` on the legacy source; report blast radius. (We are copying, not editing — expect legacy callers unaffected.)

**Files:**
- Create: `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/__init__.py`
- Create: `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/evidence/__init__.py`
- Create: `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/evidence/hashing.py`
- Create: `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/evidence/command_evidence.py`
- Test: `skills/e2e-dev-harness-v2/tests/test_evidence_adapters.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_evidence_adapters.py`:

```python
import json
import sys
from pathlib import Path


def test_sha256_file_matches_hashlib(tmp_path):
    from harness_v2.adapters.evidence import hashing
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    import hashlib
    assert hashing.sha256_file(f) == hashlib.sha256(b"hello").hexdigest()


def test_record_command_captures_exit_code_and_hashes(tmp_path):
    from harness_v2.adapters.evidence import command_evidence as ce
    ev = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(3)"')
    assert ev["schema"] == ce.COMMAND_EVIDENCE_SCHEMA
    assert ev["exit_code"] == 3
    assert len(ev["stdout_sha256"]) == 64
    assert ce.is_command_evidence(ev) is True


def test_is_command_evidence_rejects_plain_dict():
    from harness_v2.adapters.evidence import command_evidence as ce
    assert ce.is_command_evidence({"foo": "bar"}) is False
```

- [ ] **Step 2: Run to verify fail**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_evidence_adapters.py -q`
Expected: FAIL — `ModuleNotFoundError: harness_v2.adapters`.

- [ ] **Step 3: Create the adapter package + hashing module**

Create `adapters/__init__.py` (empty), `adapters/evidence/__init__.py` (empty), and `adapters/evidence/hashing.py`:

```python
"""Narrow hashing leaf (ported from legacy artifact_registry.sha256)."""
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

- [ ] **Step 4: Create command_evidence module**

Create `adapters/evidence/command_evidence.py`:

```python
"""Narrow command-evidence leaf (ported from legacy command_evidence.run_command).

Runs a command and returns tamper-evident JSON (exit code + stdout/stderr hashes).
"""
from __future__ import annotations

import hashlib
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

COMMAND_EVIDENCE_SCHEMA = "e2e-dev-harness-v2.command-evidence.v1"
DEFAULT_TIMEOUT_SECONDS = 600


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def record_command(repo: str | Path, command: str,
                   timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    repo = Path(repo).resolve()
    started = _now_iso()
    started_perf = time.perf_counter()
    try:
        # posix=True parses our controlled, quoted command strings consistently on
        # Windows and POSIX (Windows native quoting would leave literal quotes in argv).
        argv = shlex.split(command, posix=True)
    except ValueError as error:
        return {
            "schema": COMMAND_EVIDENCE_SCHEMA, "command": command, "argv": [],
            "cwd": str(repo), "started_at": started, "finished_at": _now_iso(),
            "elapsed_ms": 0, "exit_code": 2, "stdout_tail": "", "stderr_tail": str(error),
            "stdout_sha256": _sha256_text(""), "stderr_sha256": _sha256_text(str(error)),
        }
    try:
        completed = subprocess.run(argv, cwd=repo, text=True, capture_output=True,
                                   check=False, timeout=timeout)
        stdout, stderr, exit_code = completed.stdout or "", completed.stderr or "", completed.returncode
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = f"Command timed out after {timeout} seconds."
        exit_code = 124
    except OSError as error:
        stdout, stderr, exit_code = "", str(error), 127
    return {
        "schema": COMMAND_EVIDENCE_SCHEMA, "command": command, "argv": argv,
        "cwd": str(repo), "started_at": started, "finished_at": _now_iso(),
        "elapsed_ms": int((time.perf_counter() - started_perf) * 1000),
        "exit_code": exit_code,
        "stdout_tail": stdout[-4000:], "stderr_tail": stderr[-4000:],
        "stdout_sha256": _sha256_text(stdout), "stderr_sha256": _sha256_text(stderr),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
    }


def is_command_evidence(obj) -> bool:
    return (
        isinstance(obj, dict)
        and obj.get("schema") == COMMAND_EVIDENCE_SCHEMA
        and "exit_code" in obj
    )
```

- [ ] **Step 5: Run to verify pass**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_evidence_adapters.py -q`
Expected: PASS.

- [ ] **Step 6: Run full suite (no regression)**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add skills/e2e-dev-harness-v2/scripts/harness_v2/adapters \
        skills/e2e-dev-harness-v2/tests/test_evidence_adapters.py
git commit -m "feat(harness-v2): port hashing + command-evidence leaves behind narrow adapters (R1 prereq)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: R1 — gates validate real artifacts (highest priority)

Wire artifact validation into `gate_passes` via a `repo_root` param; enrich `submit_evidence`; thread `repo_root` through `evaluate`, `navigation_map`, and the CLI; rewrite the e2e test to land real artifacts; add a negative artifact test.

**Files:**
- Create: `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/evidence/validate.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/core/gates.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/core/engine.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/core/navigation.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/submit.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/gate.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/next.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/status.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/main.py` (submit args)
- Test: `skills/e2e-dev-harness-v2/tests/test_gate_artifact_validation.py` (new)
- Test: `skills/e2e-dev-harness-v2/tests/test_cli_e2e.py` (rewrite)

- [ ] **Step 1: Write failing unit tests for the validator**

Create `tests/test_gate_artifact_validation.py`:

```python
import json
import sys
from pathlib import Path

from harness_v2.core import lifecycle, gates
from harness_v2 import pipeline


def _phase(name):
    return next(p for p in lifecycle.build_spine(pipeline.active_phase_names("minimal")) if p.name == name)


def test_validate_missing_file_fails(tmp_path):
    from harness_v2.adapters.evidence import validate
    ok, reason = validate.validate_evidence(tmp_path, "clarification", {"path": "nope.md"})
    assert ok is False
    assert reason == "file-not-found"


def test_validate_empty_file_fails(tmp_path):
    from harness_v2.adapters.evidence import validate
    (tmp_path / "e.md").write_text("", encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "clarification", {"path": "e.md"})
    assert ok is False
    assert reason == "empty-file"


def test_validate_nonempty_doc_passes(tmp_path):
    from harness_v2.adapters.evidence import validate
    (tmp_path / "c.md").write_text("real", encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "clarification", {"path": "c.md"})
    assert ok is True and reason is None


def test_validate_passing_tests_requires_zero_exit(tmp_path):
    from harness_v2.adapters.evidence import command_evidence as ce, validate
    ev = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(1)"')
    (tmp_path / "t.json").write_text(json.dumps(ev), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "passing_tests", {"path": "t.json"})
    assert ok is False and reason.startswith("exit-code")


def test_validate_failing_tests_requires_nonzero_exit(tmp_path):
    from harness_v2.adapters.evidence import command_evidence as ce, validate
    ev = ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit(0)"')
    (tmp_path / "t.json").write_text(json.dumps(ev), encoding="utf-8")
    ok, reason = validate.validate_evidence(tmp_path, "failing_tests", {"path": "t.json"})
    assert ok is False and reason.startswith("exit-code")


def test_gate_passes_with_repo_root_rejects_fake_path(tmp_path):
    # the core R1 property: a present-but-fake evidence path does NOT pass the gate
    rec = {"evidence": {"clarification": {"path": "ghost.md"}}}
    ok, missing = gates.gate_passes(_phase("CLARIFIED"), rec, repo_root=tmp_path)
    assert ok is False
    assert "clarification" in missing


def test_gate_passes_presence_only_without_repo_root():
    # backward-compatible: no repo_root -> presence check only
    rec = {"evidence": {"clarification": "anything"}}
    ok, missing = gates.gate_passes(_phase("CLARIFIED"), rec)
    assert ok is True and missing == []
```

- [ ] **Step 2: Run to verify fail**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_gate_artifact_validation.py -q`
Expected: FAIL — `harness_v2.adapters.evidence.validate` missing; `gate_passes` rejects nothing.

- [ ] **Step 3: Create the validator**

Create `adapters/evidence/validate.py`:

```python
"""Validate a worker's evidence artifact: exists + non-empty + hash + command-evidence."""
from __future__ import annotations

import json
from pathlib import Path

from harness_v2.adapters.evidence import command_evidence, hashing

# Evidence keys whose artifact must be command-evidence JSON with a specific exit code.
COMMAND_KEYS = {"failing_tests": "nonzero", "passing_tests": "zero"}


def _path_of(entry) -> str:
    return entry["path"] if isinstance(entry, dict) else entry


def validate_evidence(repo_root, key: str, entry) -> tuple[bool, str | None]:
    path = _path_of(entry)
    if not path:
        return False, "no-path"
    candidate = Path(path)
    full = candidate if candidate.is_absolute() else Path(repo_root) / candidate
    if not full.is_file():
        return False, "file-not-found"
    if full.stat().st_size == 0:
        return False, "empty-file"
    if isinstance(entry, dict) and entry.get("sha256"):
        if hashing.sha256_file(full) != entry["sha256"]:
            return False, "hash-mismatch"
    if key in COMMAND_KEYS:
        try:
            obj = json.loads(full.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False, "not-json"
        if not command_evidence.is_command_evidence(obj):
            return False, "not-command-evidence"
        ec = obj.get("exit_code")
        want = COMMAND_KEYS[key]
        if want == "zero" and ec != 0:
            return False, f"exit-code-{ec}"
        if want == "nonzero" and (ec == 0 or ec is None):
            return False, f"exit-code-{ec}"
    return True, None
```

- [ ] **Step 4: Update `gate_passes` to accept `repo_root`**

Replace `core/gates.py` with:

```python
"""Declarative gate evaluation + closure invariant (I2)."""
from __future__ import annotations

from harness_v2.adapters.evidence import validate
from harness_v2.core.lifecycle import Phase


def gate_passes(phase: Phase, phase_record: dict | None,
                repo_root=None) -> tuple[bool, list[str]]:
    evidence = (phase_record or {}).get("evidence", {})
    missing: list[str] = []
    for k in phase.exit_gate:
        if k not in evidence:
            missing.append(k)
            continue
        if repo_root is not None:
            ok, _reason = validate.validate_evidence(repo_root, k, evidence[k])
            if not ok:
                missing.append(k)
    return (not missing, missing)


def gate_closure_ok(spine: list[Phase]) -> tuple[bool, list[str]]:
    produced: set[str] = set()
    required: set[str] = set()
    for p in spine:
        produced.update(p.produces)
        required.update(p.exit_gate)
    unmet = sorted(required - produced)
    return (not unmet, unmet)
```

- [ ] **Step 5: Run validator + gate unit tests to verify pass**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_gate_artifact_validation.py tests/test_gates.py tests/test_gate_closure.py -q`
Expected: PASS (existing `test_gates.py` uses presence-only path — still green).

- [ ] **Step 6: Enrich `submit_evidence` and thread `repo_root` through engine**

Replace `core/engine.py` with:

```python
"""Engine: terminating advance (I1) + evidence submission."""
from __future__ import annotations

from pathlib import Path

from harness_v2.adapters.evidence import hashing
from harness_v2.core import gates, dispatch
from harness_v2.core.lifecycle import Phase


def _phase_record(state: dict, name: str) -> dict:
    return state.setdefault("phases", {}).setdefault(name, {})


def submit_evidence(state: dict, phase_name: str, key: str, path: str, *,
                    repo_root=None, status: str = "done", reason: str | None = None) -> None:
    rec = _phase_record(state, phase_name)
    if status == "failed":
        rec["dispatch"] = dispatch.DispatchStatus.FAILED.value
        if reason:
            rec["blocker"] = reason
        return
    entry: dict = {"path": path}
    if repo_root is not None and path:
        candidate = Path(path)
        full = candidate if candidate.is_absolute() else Path(repo_root) / candidate
        if full.is_file():
            entry["sha256"] = hashing.sha256_file(full)
            entry["bytes"] = full.stat().st_size
    rec.setdefault("evidence", {})[key] = entry
    rec["dispatch"] = dispatch.DispatchStatus.DONE.value
    rec.pop("blocker", None)


def _by_name(spine: list[Phase]) -> dict[str, Phase]:
    return {p.name: p for p in spine}


def evaluate(spine: list[Phase], state: dict, repo_root=None) -> dict:
    """Advance current_phase past every gate that already passes; stop at first
    blocker or terminal. Terminates: each pass advances >=0 phases along a finite
    spine then blocks or completes."""
    by_name = _by_name(spine)
    name = state.get("current_phase", spine[0].name)
    while True:
        phase = by_name[name]
        rec = state.get("phases", {}).get(name, {})
        ok, missing = gates.gate_passes(phase, rec, repo_root)
        if not ok:
            state["current_phase"] = name
            result = {
                "complete": False,
                "blocked_phase": name,
                "missing_evidence": missing,
                "next_action": dispatch.worker_packet(phase, state.get("_run_state_path", "")),
            }
            if rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
                result["failed"] = True
                result["blocker"] = rec.get("blocker")
            return result
        if phase.next_phase is None:
            state["current_phase"] = name
            return {"complete": True, "blocked_phase": None, "missing_evidence": [], "next_action": {}}
        name = phase.next_phase
```

- [ ] **Step 7: Thread `repo_root` through navigation (signature only here; L1 enrichment is Task 8)**

In `core/navigation.py`, change the two signatures and the gate call to accept/forward `repo_root`. Replace `_phase_status` and `navigation_map`:

```python
def _phase_status(spine: list[Phase], state: dict, idx: int, repo_root=None) -> str:
    names = [p.name for p in spine]
    cur = state.get("current_phase", spine[0].name)
    cur_idx = names.index(cur) if cur in names else 0
    phase = spine[idx]
    rec = state.get("phases", {}).get(phase.name, {})
    if idx < cur_idx:
        return "done"
    if idx == cur_idx:
        ok, _ = gates.gate_passes(phase, rec, repo_root)
        if phase.next_phase is None and ok:
            return "done"
        return "current"
    return "pending"


def navigation_map(spine: list[Phase], state: dict, repo_root=None) -> dict:
    phases = [{"name": p.name, "status": _phase_status(spine, state, i, repo_root)}
              for i, p in enumerate(spine)]
    active = {p.name for p in spine}
    full = []
    for name in catalog():
        if name in active:
            st = next(x["status"] for x in phases if x["name"] == name)
        else:
            st = "skipped"
        full.append({"name": name, "status": st})
    done = sum(1 for p in phases if p["status"] == "done")
    return {
        "schema": "e2e-dev-harness-v2.navigation-map.v1",
        "goal": GOAL,
        "you_are_here": state.get("current_phase", spine[0].name),
        "phases": phases,
        "full_catalog": full,
        "progress": f"{done}/{len(spine)}",
    }
```

- [ ] **Step 8: Thread `--repo` through the CLI commands**

`cli/commands/submit.py` — pass repo and support status/reason:

```python
"""submit: record worker evidence (or mark failed) and update dispatch."""
from __future__ import annotations

from pathlib import Path

from harness_v2.core import run_state, engine


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    engine.submit_evidence(
        state, args.phase, args.key, args.path,
        repo_root=Path(args.repo).resolve(),
        status=getattr(args, "status", "done"),
        reason=getattr(args, "reason", None),
    )
    run_state.save(args.state, state)
    return 0, {"schema": "e2e-dev-harness-v2.submit.v1", "phase": args.phase,
               "key": args.key, "recorded": args.path,
               "status": getattr(args, "status", "done")}
```

`cli/commands/gate.py` — pass repo into `gate_passes` (add `from pathlib import Path` at top, replace the `gate_passes` call lines):

```python
    rec = state.get("phases", {}).get(name, {})
    ok, missing = gates.gate_passes(phase, rec, Path(args.repo).resolve())
    return (0 if ok else 1), {"phase": name, "passed": ok, "missing_evidence": missing}
```

`cli/commands/next.py` — pass repo into `evaluate` and `navigation_map`:

```python
"""next: advance spine or return single blocker + navigation map."""
from __future__ import annotations

from pathlib import Path

from harness_v2.core import run_state, lifecycle, engine, navigation
from harness_v2 import pipeline


def run(args) -> tuple[int, dict]:
    repo = Path(args.repo).resolve()
    state = run_state.load(args.state)
    state["_run_state_path"] = str(args.state)
    spine = lifecycle.build_spine(pipeline.active_phase_names(state.get("pipeline", "minimal")))
    res = engine.evaluate(spine, state, repo)
    state.pop("_run_state_path", None)
    run_state.save(args.state, state)
    res["navigation_map"] = navigation.navigation_map(spine, state, repo)
    res["run_state"] = str(args.state)
    return 0, res
```

`cli/commands/status.py` — pass repo into `navigation_map`:

```python
"""status: human-readable navigation map (same source as next)."""
from __future__ import annotations

from pathlib import Path

from harness_v2.core import run_state, lifecycle, navigation
from harness_v2 import pipeline


def run(args) -> tuple[int, dict]:
    state = run_state.load(args.state)
    spine = lifecycle.build_spine(pipeline.active_phase_names(state.get("pipeline", "minimal")))
    return 0, {"navigation_map": navigation.navigation_map(spine, state, Path(args.repo).resolve())}
```

In `cli/main.py` `build_parser`, change the `submit` arg lines so `--key`/`--path` are optional and add `--status`/`--reason`:

```python
    sm = sub.add_parser("submit"); sm.add_argument("--state", required=True); sm.add_argument("--repo", default=".")
    sm.add_argument("--phase", required=True); sm.add_argument("--key", default=None); sm.add_argument("--path", default=None)
    sm.add_argument("--status", choices=["done", "failed"], default="done")
    sm.add_argument("--reason", default=None)
```

- [ ] **Step 9: Run engine/navigation/gate suites to verify no regression**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_engine_termination.py tests/test_navigation.py tests/test_gates.py -q`
Expected: PASS (these call the core functions without `repo_root`, so presence-only behavior is preserved).

- [ ] **Step 10: Rewrite the e2e test to land REAL artifacts (R1 #4)**

Replace `tests/test_cli_e2e.py` with:

```python
import json
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness_v2.py"


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def _make_artifact(repo: Path, phase: str, key: str) -> str:
    """Produce a REAL artifact for `key`; return its repo-relative path."""
    from harness_v2.adapters.evidence import command_evidence as ce
    base = repo / "docs" / "agent-runs" / "art"
    base.mkdir(parents=True, exist_ok=True)
    if key in ("failing_tests", "passing_tests"):
        code = 1 if key == "failing_tests" else 0
        ev = ce.record_command(repo, f'"{sys.executable}" -c "import sys; sys.exit({code})"')
        f = base / f"{phase}-{key}.json"
        f.write_text(json.dumps(ev), encoding="utf-8")
    else:
        f = base / f"{phase}-{key}.md"
        f.write_text(f"# {phase} {key}\nreal evidence content\n", encoding="utf-8")
    return str(f.relative_to(repo))


def test_start_then_drive_to_verified_with_real_artifacts_terminates(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    assert code == 0
    state_path = res["run_state"]
    steps = 0
    nres = {"complete": False}
    while steps < 50:
        steps += 1
        code, nres = _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
        if nres["complete"]:
            break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            rel = _make_artifact(tmp_path, phase, key)
            _run("submit", "--state", state_path, "--phase", phase,
                 "--key", key, "--path", rel, "--repo", str(tmp_path), cwd=tmp_path)
    assert nres["complete"] is True
    assert nres["navigation_map"]["you_are_here"] == "VERIFIED"
    assert steps <= 6


def test_fake_path_evidence_never_reaches_verified(tmp_path):
    """R1: a present-but-nonexistent evidence path must NOT drive the run to VERIFIED."""
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    steps = 0
    nres = {"complete": False}
    while steps < 8:
        steps += 1
        code, nres = _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
        if nres["complete"]:
            break
        phase = nres["blocked_phase"]
        for key in nres["next_action"]["expected_outputs"]:
            _run("submit", "--state", state_path, "--phase", phase,
                 "--key", key, "--path", f"{phase}-{key}.md",  # FAKE: never created
                 "--repo", str(tmp_path), cwd=tmp_path)
    assert nres["complete"] is False
    assert nres["navigation_map"]["you_are_here"] != "VERIFIED"


def test_dispatch_returns_pointer_packet(tmp_path):
    code, res = _run("start", "--repo", str(tmp_path), "--feature", "demo",
                     "--request", "do x", cwd=tmp_path)
    state_path = res["run_state"]
    _run("next", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    code, dres = _run("dispatch", "--state", state_path, "--repo", str(tmp_path), cwd=tmp_path)
    assert dres["skill"] == "e2e-harness-clarification"
    assert dres["expected_outputs"] == ["clarification"]
```

- [ ] **Step 11: Run e2e + full suite**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: PASS — including the rewritten e2e (real artifacts reach VERIFIED) and the new negative test (fake paths never do).

- [ ] **Step 12: KG change check + commit**

Run `gitnexus_detect_changes({scope:"unstaged"})`; confirm only v2 files changed. Then:

```bash
git add skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/evidence/validate.py \
        skills/e2e-dev-harness-v2/scripts/harness_v2/core/gates.py \
        skills/e2e-dev-harness-v2/scripts/harness_v2/core/engine.py \
        skills/e2e-dev-harness-v2/scripts/harness_v2/core/navigation.py \
        skills/e2e-dev-harness-v2/scripts/harness_v2/cli \
        skills/e2e-dev-harness-v2/tests/test_gate_artifact_validation.py \
        skills/e2e-dev-harness-v2/tests/test_cli_e2e.py
git commit -m "feat(harness-v2): R1 — gates validate real artifacts (exists+nonempty+hash+command-evidence)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: R1' — finish PLANNED + REVIEWED worker-skill delegators (= L4)

Rework the two stub skills into v2 delegators that reference the **v2** CLI and delegate method to Superpowers; extend the delegate test to 6 skills and assert the old CLI path is gone from the two reworked skills.

**Files:**
- Modify: `skills/e2e-harness-planning/SKILL.md`
- Modify: `skills/e2e-harness-review/SKILL.md`
- Test: `skills/e2e-dev-harness-v2/tests/test_worker_skills_delegate.py` (extend)

- [ ] **Step 1: Write failing test extension**

Replace `tests/test_worker_skills_delegate.py` with:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAP = {
    "e2e-harness-clarification": "superpowers:brainstorming",
    "e2e-harness-planning": "superpowers:writing-plans",
    "e2e-harness-tdd-red": "superpowers:test-driven-development",
    "e2e-harness-implementation": "superpowers:test-driven-development",
    "e2e-harness-review": "superpowers:requesting-code-review",
    "e2e-harness-completion": "superpowers:verification-before-completion",
}
OUTPUTS = {
    "e2e-harness-clarification": "clarification",
    "e2e-harness-planning": "plan",
    "e2e-harness-tdd-red": "failing_tests",
    "e2e-harness-implementation": "passing_tests",
    "e2e-harness-review": "review",
    "e2e-harness-completion": "verification",
}
# the reworked PLANNED/REVIEWED skills must reference the v2 CLI, not the legacy one
NO_LEGACY_CLI = ("e2e-harness-planning", "e2e-harness-review")
LEGACY_CLI = "skills/e2e-dev-harness/scripts/e2e_dev_harness.py"


def test_worker_skills_delegate_and_declare_outputs():
    for skill, sp in MAP.items():
        text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert sp in text, f"{skill} missing delegation to {sp}"
        assert OUTPUTS[skill] in text, f"{skill} missing output {OUTPUTS[skill]}"
        assert "expected_outputs" in text, f"{skill} missing output contract section"


def test_reworked_skills_drop_legacy_cli():
    for skill in NO_LEGACY_CLI:
        text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert LEGACY_CLI not in text, f"{skill} still references legacy CLI"
        assert "e2e_dev_harness_v2.py" in text, f"{skill} missing v2 CLI reference"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_worker_skills_delegate.py -q`
Expected: FAIL — planning/review lack delegation, still reference legacy CLI.

- [ ] **Step 3: Rework `skills/e2e-harness-planning/SKILL.md`**

Replace the whole file with:

```markdown
---
name: e2e-harness-planning
description: Use for e2e-dev-harness implementation-planner worker tasks that turn clarified requirements into a service-sliced implementation plan and schedule from a fresh isolated context.
---

# E2E Harness Planning Worker

Do not inherit coordinator chat context. Use only the packet `context_paths` (run-state, requirements handoff, any R1 review, service-scope inputs).

## v2 契约 (e2e-dev-harness-v2)

- **方法委派**: 用 `superpowers:writing-plans` 把澄清后的需求转成服务切片实现计划与调度。本 skill 只持 harness 专属胶水,不重造规划方法。
- **expected_outputs**: 产出证据键 `plan` —— 写实现计划到 `docs/agent-runs/<run>/handoffs/02-implementation-planner.md`,然后:
  `python skills/e2e-dev-harness-v2/scripts/e2e_dev_harness_v2.py submit --state <run-state> --phase PLANNED --key plan --path <plan-path>`
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。
- 仅就需求 handoff 未解决的范围/排序决策向用户提问。
```

- [ ] **Step 4: Rework `skills/e2e-harness-review/SKILL.md`**

Replace the whole file with:

```markdown
---
name: e2e-harness-review
description: Use for e2e-dev-harness r1/r2/r3 reviewer worker tasks that independently review a phase from a fresh isolated context and never review their own implementation.
---

# E2E Harness Review Worker

Do not inherit coordinator chat context. Use only the packet `context_paths` (run-state, the review request, relevant handoffs).

## v2 契约 (e2e-dev-harness-v2)

- **方法委派**: 用 `superpowers:requesting-code-review` 发起审查、`superpowers:receiving-code-review` 消化反馈。本 skill 只持 harness 专属胶水。
- **expected_outputs**: 产出证据键 `review` —— 写审查报告到 `docs/agent-runs/<run>/handoffs/<reviewer>-review.md`,然后:
  `python skills/e2e-dev-harness-v2/scripts/e2e_dev_harness_v2.py submit --state <run-state> --phase REVIEWED --key <review-key> --path <report-path>`
- **review fan-out (critical tier)**: REVIEWED 在 critical/audited tier 要求三份独立证据 `r1_review` / `r2_review` / `r3_review`。每个 reviewer 在**全新隔离上下文**运行,**绝不 review 自己写过的实现**;coordinator 为三个键各 spawn 一个独立子 agent。
- **上下文**: 不继承 coordinator 对话;只用 packet 的 `context_paths`。写完报告即停,不改实现文件。
```

- [ ] **Step 5: Run to verify pass + full suite**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_worker_skills_delegate.py -q && python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/e2e-harness-planning/SKILL.md skills/e2e-harness-review/SKILL.md \
        skills/e2e-dev-harness-v2/tests/test_worker_skills_delegate.py
git commit -m "feat(harness-v2): R1' — PLANNED/REVIEWED worker skills delegate to Superpowers, v2 CLI (L4)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Tier-scaled pipelines (standard / critical / audited) + structured phase pruning

Evolve `lifecycle.build_spine` to accept per-phase overrides; make `pipeline.py` the structured tier→(phases + overrides) map and add `pipeline.build_spine(name)`; let `start` pick a tier. Centralize spine building in the CLI.

**Files:**
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/core/lifecycle.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/pipeline.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/start.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/main.py` (add `--tier` to `start`)
- Modify (spine call sites): `cli/commands/next.py`, `status.py`, `dispatch.py`, `gate.py`
- Test: `skills/e2e-dev-harness-v2/tests/test_pipeline_tiers.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_pipeline_tiers.py`:

```python
from harness_v2 import pipeline
from harness_v2.core import lifecycle


def test_minimal_skips_planned_and_reviewed():
    names = pipeline.active_phase_names("minimal")
    assert "PLANNED" not in names and "REVIEWED" not in names


def test_standard_is_full_spine_single_reviewer():
    names = pipeline.active_phase_names("standard")
    assert names == ["CREATED", "CLARIFIED", "PLANNED", "RED", "IMPLEMENTED", "REVIEWED", "VERIFIED"]
    spine = pipeline.build_spine("standard")
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    assert reviewed.exit_gate == ("review",)


def test_critical_reviewed_requires_three_reviews():
    spine = pipeline.build_spine("critical")
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    assert reviewed.exit_gate == ("r1_review", "r2_review", "r3_review")
    assert reviewed.produces == ("r1_review", "r2_review", "r3_review")


def test_audited_adds_audit_replay_to_verified():
    spine = pipeline.build_spine("audited")
    verified = next(p for p in spine if p.name == "VERIFIED")
    assert "audit_replay" in verified.exit_gate
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    assert reviewed.exit_gate == ("r1_review", "r2_review", "r3_review")


def test_build_spine_overrides_are_isolated_from_catalog():
    # overrides must not mutate the shared catalog
    pipeline.build_spine("critical")
    assert lifecycle.catalog()["REVIEWED"].exit_gate == ("review",)


def test_unknown_pipeline_raises():
    import pytest
    with pytest.raises(KeyError):
        pipeline.active_phase_names("nope")
```

- [ ] **Step 2: Run to verify fail**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_pipeline_tiers.py -q`
Expected: FAIL — only `minimal` exists; `build_spine` missing.

- [ ] **Step 3: Add `overrides` to `lifecycle.build_spine`**

Replace `build_spine` in `core/lifecycle.py` with:

```python
def build_spine(phase_names: list[str], overrides: dict | None = None) -> list[Phase]:
    overrides = overrides or {}
    spine: list[Phase] = []
    for i, name in enumerate(phase_names):
        base = _CATALOG[name]
        nxt = phase_names[i + 1] if i + 1 < len(phase_names) else None
        fields = {"next_phase": nxt}
        if name in overrides:
            fields.update(overrides[name])
        spine.append(replace(base, **fields))
    return spine
```

- [ ] **Step 4: Make `pipeline.py` the structured tier map**

Replace `pipeline.py` with:

```python
"""Pipeline config: tier -> (active phases + per-phase gate overrides)."""
from __future__ import annotations

from harness_v2.core import lifecycle

_FULL = ("CREATED", "CLARIFIED", "PLANNED", "RED", "IMPLEMENTED", "REVIEWED", "VERIFIED")
_REVIEW_FANOUT = ("r1_review", "r2_review", "r3_review")

# Each pipeline: ordered phase names + overrides applied when building the spine.
PIPELINES: dict[str, dict] = {
    "minimal": {
        "phases": ("CREATED", "CLARIFIED", "RED", "IMPLEMENTED", "VERIFIED"),
        "overrides": {},
    },
    "standard": {
        "phases": _FULL,
        "overrides": {},
    },
    "critical": {
        "phases": _FULL,
        "overrides": {
            "REVIEWED": {"produces": _REVIEW_FANOUT, "exit_gate": _REVIEW_FANOUT},
        },
    },
    "audited": {
        "phases": _FULL,
        "overrides": {
            "REVIEWED": {"produces": _REVIEW_FANOUT, "exit_gate": _REVIEW_FANOUT},
            "VERIFIED": {"produces": ("verification", "audit_replay"),
                          "exit_gate": ("verification", "audit_replay")},
        },
    },
}


def active_phase_names(pipeline: str) -> list[str]:
    if pipeline not in PIPELINES:
        raise KeyError(f"unknown pipeline: {pipeline}")
    return list(PIPELINES[pipeline]["phases"])


def build_spine(pipeline: str) -> list[lifecycle.Phase]:
    if pipeline not in PIPELINES:
        raise KeyError(f"unknown pipeline: {pipeline}")
    cfg = PIPELINES[pipeline]
    return lifecycle.build_spine(list(cfg["phases"]), cfg.get("overrides"))
```

- [ ] **Step 5: Centralize spine building in CLI**

In each of `cli/commands/next.py`, `status.py`, `dispatch.py`, `gate.py`, replace the line
`spine = lifecycle.build_spine(pipeline.active_phase_names(state.get("pipeline", "minimal")))`
with
`spine = pipeline.build_spine(state.get("pipeline", "minimal"))`.
In `next.py`/`status.py` the `lifecycle` import is no longer used — remove `lifecycle` from their `from harness_v2.core import ...` line. In `dispatch.py`/`gate.py`, `lifecycle` is also only used for that call — remove it from their imports too. Verify with the test run in Step 7 (an unused-import won't fail tests, but keep it clean).

- [ ] **Step 6: Add `--tier` to `start`**

In `cli/main.py` `build_parser`, extend the `start` subparser (after the `--request` arg):

```python
    s.add_argument("--tier", choices=["minimal", "standard", "critical", "audited"], default="minimal")
```

Replace the `new_run_state(...)` + return in `cli/commands/start.py` so tier drives both fields:

```python
    st = run_state.new_run_state(run_id, args.feature, args.request,
                                 tier=args.tier, pipeline=args.tier)
    run_state.save(path, st)
    return 0, {"schema": "e2e-dev-harness-v2.start.v1", "run_id": run_id,
               "run_state": str(path), "current_phase": "CREATED", "tier": args.tier}
```

- [ ] **Step 7: Run pipeline + full suite**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: PASS (existing `test_lifecycle_spine.py` / `test_navigation.py` use `pipeline.active_phase_names("minimal")` which is unchanged).

- [ ] **Step 8: Commit**

```bash
git add skills/e2e-dev-harness-v2/scripts/harness_v2/core/lifecycle.py \
        skills/e2e-dev-harness-v2/scripts/harness_v2/pipeline.py \
        skills/e2e-dev-harness-v2/scripts/harness_v2/cli \
        skills/e2e-dev-harness-v2/tests/test_pipeline_tiers.py
git commit -m "feat(harness-v2): tier-scaled pipelines + structured phase pruning (standard/critical/audited)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: r1/r2/r3 review fan-out behavior (dispatch packet + gate) + §4 all-tier closure seed

Verify the critical-tier REVIEWED gate requires three independent reviews end-to-end, the dispatch packet advertises all three outputs, and **every built-in tier is gate-closed** (the M3/R2 seed test).

**Files:**
- Test: `skills/e2e-dev-harness-v2/tests/test_review_fanout.py` (new)
- Test: `skills/e2e-dev-harness-v2/tests/test_gate_closure.py` (extend)

(No new production code expected — Task 5 already encodes the fan-out gate. If a test fails it reveals a real gap to fix minimally.)

- [ ] **Step 1: Write the fan-out tests**

Create `tests/test_review_fanout.py`:

```python
from pathlib import Path

from harness_v2 import pipeline
from harness_v2.core import run_state, engine, dispatch, gates


def _drive_to(state, repo, target, spine):
    """Advance, fabricating real artifacts, until current_phase == target."""
    base = Path(repo) / "art"
    base.mkdir(parents=True, exist_ok=True)
    res = {"complete": False}
    for _ in range(20):
        res = engine.evaluate(spine, state, repo)
        if state["current_phase"] == target or res["complete"]:
            return res
        phase = res["blocked_phase"]
        ph = next(p for p in spine if p.name == phase)
        for key in ph.produces:
            f = base / f"{phase}-{key}.md"
            f.write_text("real", encoding="utf-8")
            engine.submit_evidence(state, phase, key, str(f), repo_root=repo)
    return res


def test_critical_reviewed_dispatch_packet_lists_three_reviews():
    spine = pipeline.build_spine("critical")
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    packet = dispatch.worker_packet(reviewed, "docs/agent-runs/r1/run-state.json")
    assert packet["expected_outputs"] == ["r1_review", "r2_review", "r3_review"]


def test_critical_reviewed_blocks_until_three_real_reviews(tmp_path):
    spine = pipeline.build_spine("critical")
    st = run_state.new_run_state("r1", "f", "r", tier="critical", pipeline="critical")
    _drive_to(st, tmp_path, "REVIEWED", spine)
    assert st["current_phase"] == "REVIEWED"
    reviewed = next(p for p in spine if p.name == "REVIEWED")
    # submit only two real reviews -> still blocked
    for key in ("r1_review", "r2_review"):
        f = tmp_path / f"{key}.md"; f.write_text("ok", encoding="utf-8")
        engine.submit_evidence(st, "REVIEWED", key, str(f), repo_root=tmp_path)
    ok, missing = gates.gate_passes(reviewed, st["phases"]["REVIEWED"], tmp_path)
    assert ok is False and "r3_review" in missing
    # third review -> gate passes
    f = tmp_path / "r3_review.md"; f.write_text("ok", encoding="utf-8")
    engine.submit_evidence(st, "REVIEWED", "r3_review", str(f), repo_root=tmp_path)
    ok, missing = gates.gate_passes(reviewed, st["phases"]["REVIEWED"], tmp_path)
    assert ok is True and missing == []
```

- [ ] **Step 2: Extend `tests/test_gate_closure.py` with the all-tier seed (§4)**

Append to `tests/test_gate_closure.py`:

```python
def test_all_builtin_tiers_gate_closed():
    from harness_v2 import pipeline
    for tier in ("minimal", "standard", "critical", "audited"):
        spine = pipeline.build_spine(tier)
        ok, unmet = gates.gate_closure_ok(spine)
        assert ok is True, f"tier {tier} not gate-closed: {unmet}"
```

- [ ] **Step 3: Run to verify (and fix only if a real gap surfaces)**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_review_fanout.py tests/test_gate_closure.py -q`
Expected: PASS. If `test_all_builtin_tiers_gate_closed` fails for a tier, the override produces/exit_gate sets disagree — fix the offending entry in `pipeline.py` so every `exit_gate` key is in some phase's `produces`.

- [ ] **Step 4: Full suite + commit**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: PASS.

```bash
git add skills/e2e-dev-harness-v2/tests/test_review_fanout.py \
        skills/e2e-dev-harness-v2/tests/test_gate_closure.py
git commit -m "test(harness-v2): r1/r2/r3 review fan-out + all-builtin-tier gate-closure seed (M2 fan-out, M3/R2 seed)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: L2 — DispatchStatus FAILED path (worker failure + re-dispatch)

Surface worker failure in the run-state and navigation so the coordinator can see a blocked phase and re-dispatch. (Engine/submit/CLI support landed in Task 3; this task proves the path and adds the navigation `blocked` render.)

**Files:**
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/core/navigation.py`
- Test: `skills/e2e-dev-harness-v2/tests/test_dispatch_failure.py` (new)

- [ ] **Step 1: Write proving tests**

Create `tests/test_dispatch_failure.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

from harness_v2.core import run_state, engine, dispatch
from harness_v2 import pipeline

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "e2e_dev_harness_v2.py"


def _run(*args, cwd):
    proc = subprocess.run([sys.executable, str(ENTRY), *args], cwd=cwd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}")


def test_submit_failed_marks_dispatch_failed_with_blocker():
    spine = pipeline.build_spine("minimal")
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(spine, st)  # at CLARIFIED
    engine.submit_evidence(st, "CLARIFIED", None, None, status="failed", reason="clarifier crashed")
    assert st["phases"]["CLARIFIED"]["dispatch"] == dispatch.DispatchStatus.FAILED.value
    assert st["phases"]["CLARIFIED"]["blocker"] == "clarifier crashed"


def test_evaluate_reports_failed_phase():
    spine = pipeline.build_spine("minimal")
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(spine, st)
    engine.submit_evidence(st, "CLARIFIED", None, None, status="failed", reason="boom")
    res = engine.evaluate(spine, st)
    assert res["blocked_phase"] == "CLARIFIED"
    assert res.get("failed") is True
    assert res.get("blocker") == "boom"


def test_successful_resubmit_clears_blocker_and_advances(tmp_path):
    spine = pipeline.build_spine("minimal")
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(spine, st)
    engine.submit_evidence(st, "CLARIFIED", None, None, status="failed", reason="boom")
    f = tmp_path / "c.md"; f.write_text("real", encoding="utf-8")
    engine.submit_evidence(st, "CLARIFIED", "clarification", str(f), repo_root=tmp_path)
    engine.evaluate(spine, st, tmp_path)
    assert "blocker" not in st["phases"]["CLARIFIED"]
    assert st["current_phase"] == "RED"


def test_cli_submit_failed_then_status_shows_blocked(tmp_path):
    _, res = _run("start", "--repo", str(tmp_path), "--feature", "demo", "--request", "x", cwd=tmp_path)
    sp = res["run_state"]
    _run("next", "--state", sp, "--repo", str(tmp_path), cwd=tmp_path)
    _run("submit", "--state", sp, "--phase", "CLARIFIED", "--status", "failed",
         "--reason", "crashed", "--repo", str(tmp_path), cwd=tmp_path)
    _, sres = _run("status", "--state", sp, "--repo", str(tmp_path), cwd=tmp_path)
    phases = {p["name"]: p["status"] for p in sres["navigation_map"]["phases"]}
    assert phases["CLARIFIED"] == "blocked"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_dispatch_failure.py -q`
Expected: the first three pass (Task 3 support), `test_cli_submit_failed_then_status_shows_blocked` FAILS — navigation renders `current`, not `blocked`.

- [ ] **Step 3: Render `blocked` in navigation for FAILED current phase**

In `core/navigation.py`, add the `dispatch` import (alongside the existing `from harness_v2.core import gates` — change it to `from harness_v2.core import gates, dispatch`), and inside `_phase_status`, in the `idx == cur_idx` branch, immediately before `return "current"`:

```python
        if rec.get("dispatch") == dispatch.DispatchStatus.FAILED.value:
            return "blocked"
```

- [ ] **Step 4: Run to verify pass + full suite**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness-v2/scripts/harness_v2/core/navigation.py \
        skills/e2e-dev-harness-v2/tests/test_dispatch_failure.py
git commit -m "feat(harness-v2): L2 — DispatchStatus FAILED path (worker failure -> blocked -> re-dispatch)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: L1 — richer navigation map (per-phase gate summary, remaining gates, next-in-map)

The `blocked` state already lands in Task 7. Add the remaining L1 items: per-phase gate evidence summary, distance-to-goal gate count, and the next action framed inside the map.

**Files:**
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/core/navigation.py`
- Test: `skills/e2e-dev-harness-v2/tests/test_navigation.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_navigation.py`:

```python
def test_map_carries_per_phase_gate_summary():
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(_spine(), st)  # blocked at CLARIFIED, no evidence
    m = navigation.navigation_map(_spine(), st)
    clar = next(p for p in m["phases"] if p["name"] == "CLARIFIED")
    assert clar["gate"]["required"] == 1
    assert clar["gate"]["missing"] == ["clarification"]
    assert clar["gate"]["ok"] is False


def test_map_reports_remaining_gates_to_goal():
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(_spine(), st)
    m = navigation.navigation_map(_spine(), st)
    # CLARIFIED(1) + RED(1) + IMPLEMENTED(1) + VERIFIED(1) = 4 unmet gate keys ahead
    assert m["remaining_gates"] == 4


def test_map_frames_next_action_inside_map():
    st = run_state.new_run_state("r1", "f", "r")
    engine.evaluate(_spine(), st)
    m = navigation.navigation_map(_spine(), st)
    assert m["next"]["phase"] == "CLARIFIED"
    assert "e2e-harness-clarification" in m["next"]["action"]


def test_map_next_is_null_when_complete(tmp_path):
    import json, sys
    from harness_v2.adapters.evidence import command_evidence as ce
    st = run_state.new_run_state("r1", "f", "r")
    spine = _spine()
    base = tmp_path / "art"; base.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        res = engine.evaluate(spine, st, tmp_path)
        if res["complete"]:
            break
        ph = next(p for p in spine if p.name == res["blocked_phase"])
        for key in ph.produces:
            if key in ("failing_tests", "passing_tests"):
                code = 1 if key == "failing_tests" else 0
                f = base / f"{ph.name}-{key}.json"
                f.write_text(json.dumps(ce.record_command(tmp_path, f'"{sys.executable}" -c "import sys; sys.exit({code})"')), encoding="utf-8")
            else:
                f = base / f"{ph.name}-{key}.md"; f.write_text("real", encoding="utf-8")
            engine.submit_evidence(st, ph.name, key, str(f), repo_root=tmp_path)
    m = navigation.navigation_map(spine, st, tmp_path)
    assert m["next"] is None
```

- [ ] **Step 2: Run to verify fail**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_navigation.py -q`
Expected: FAIL — `gate`/`remaining_gates`/`next` keys absent.

- [ ] **Step 3: Implement the enriched map**

Replace `navigation_map` in `core/navigation.py` with:

```python
def navigation_map(spine: list[Phase], state: dict, repo_root=None) -> dict:
    names = [p.name for p in spine]
    cur = state.get("current_phase", spine[0].name)
    cur_idx = names.index(cur) if cur in names else 0

    phases = []
    for i, p in enumerate(spine):
        rec = state.get("phases", {}).get(p.name, {})
        ok, missing = gates.gate_passes(p, rec, repo_root)
        phases.append({
            "name": p.name,
            "status": _phase_status(spine, state, i, repo_root),
            "gate": {"required": len(p.exit_gate), "missing": missing, "ok": ok},
        })

    active = {p.name for p in spine}
    full = []
    for name in catalog():
        if name in active:
            st = next(x["status"] for x in phases if x["name"] == name)
        else:
            st = "skipped"
        full.append({"name": name, "status": st})

    done = sum(1 for p in phases if p["status"] == "done")
    remaining_gates = sum(len(p["gate"]["missing"]) for i, p in enumerate(phases) if i >= cur_idx)

    complete = done == len(spine)
    nxt = None
    if not complete:
        cur_phase = spine[cur_idx]
        nxt = {"phase": cur_phase.name, "action": f"dispatch {cur_phase.worker_skill}"}

    return {
        "schema": "e2e-dev-harness-v2.navigation-map.v1",
        "goal": GOAL,
        "you_are_here": cur,
        "phases": phases,
        "full_catalog": full,
        "progress": f"{done}/{len(spine)}",
        "remaining_gates": remaining_gates,
        "next": nxt,
    }
```

- [ ] **Step 4: Run to verify pass + full suite**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: PASS (original three navigation tests still hold: phases entries keep `name`/`status`, plus the new `gate` key).

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness-v2/scripts/harness_v2/core/navigation.py \
        skills/e2e-dev-harness-v2/tests/test_navigation.py
git commit -m "feat(harness-v2): L1 — navigation map gate summary, remaining-gates, next-in-map

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Port `task_tier` classification leaf + `start --tier auto`

Narrow port of the legacy keyword classifier (text-only; multi-service/dependency inputs are deferred with the scanner leaf). Lets `start --tier auto` pick a tier from the request text.

**Pre-task KG:** run `gitnexus_impact({target:"gates_for", direction:"upstream"})` on the legacy source; report blast radius. We copy the keyword logic, not the legacy gate-name vocabulary.

**Files:**
- Create: `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/tier/__init__.py`
- Create: `skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/tier/classify.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/commands/start.py`
- Modify: `skills/e2e-dev-harness-v2/scripts/harness_v2/cli/main.py` (add `auto` to `--tier` choices)
- Test: `skills/e2e-dev-harness-v2/tests/test_tier_classify.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_tier_classify.py`:

```python
from harness_v2.adapters.tier import classify


def test_plain_request_is_minimal():
    tier, reasons = classify.classify_tier("rename a helper function")
    assert tier == "minimal"
    assert reasons


def test_payment_keyword_escalates_to_critical():
    tier, _ = classify.classify_tier("add refund settlement to the ledger")
    assert tier == "critical"


def test_audit_keyword_escalates_to_audited():
    tier, _ = classify.classify_tier("compliance audit of the incident response")
    assert tier == "audited"


def test_single_service_api_surface_is_standard():
    tier, _ = classify.classify_tier("add a REST endpoint for the client")
    assert tier == "standard"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_tier_classify.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Create the classifier (text-only port)**

Create `adapters/tier/__init__.py` (empty) and `adapters/tier/classify.py`:

```python
"""Narrow tier classification (ported from legacy task_tier keyword logic, text-only).

Multi-service / dependency-report escalation is intentionally omitted until the
scanner leaf is ported (design §16). Maps request text -> one of
minimal / standard / critical / audited.
"""
from __future__ import annotations

import re

_PAYMENT = {"payment", "refund", "settlement", "ledger", "accounting", "reconcile",
            "chargeback", "支付", "退款", "结算", "账务", "对账"}
_CONTRACT = {"contract", "compatibility", "接口", "契约", "兼容"}
_WEAK_CONTRACT = {"api", "http", "rest", "client", "endpoint"}
_DATA = {"database", "db", "sql", "migration", "transaction", "audit",
         "数据", "迁移", "事务", "审计"}
_MESSAGING = {"mq", "kafka", "rocketmq", "rabbitmq", "topic", "producer", "consumer",
              "payload", "消息", "队列", "生产者", "消费者"}
_AUDIT = {"audit", "compliance", "incident", "regulatory", "合规", "审计", "事故"}


def _hits(text: str, keywords: set[str], label: str) -> list[str]:
    lowered = text.lower()
    for kw in sorted(keywords):
        if re.search(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])", lowered):
            return [f"{label} keyword detected: {kw}"]
    return []


def classify_tier(request_text: str) -> tuple[str, list[str]]:
    text = request_text or ""
    audit = _hits(text, _AUDIT, "audit")
    if audit:
        return "audited", audit
    risk: list[str] = []
    risk += _hits(text, _PAYMENT, "payment/refund")
    risk += _hits(text, _CONTRACT, "contract/API")
    risk += _hits(text, _DATA, "data")
    risk += _hits(text, _MESSAGING, "messaging")
    if risk:
        return "critical", risk
    weak = _hits(text, _WEAK_CONTRACT, "contract/API")
    if weak:
        return "standard", ["single-service API surface detected"] + weak
    return "minimal", ["no risk keyword detected"]
```

- [ ] **Step 4: Wire `auto` into `start`**

In `cli/main.py` `build_parser`, change the `start --tier` choices to include `auto`:

```python
    s.add_argument("--tier", choices=["auto", "minimal", "standard", "critical", "audited"], default="minimal")
```

In `cli/commands/start.py`, resolve `auto` before creating the state (insert after `run_id` is computed, before building `rel`/`path`):

```python
    tier = args.tier
    reasons: list[str] = []
    if tier == "auto":
        from harness_v2.adapters.tier import classify
        tier, reasons = classify.classify_tier(args.request)
```

then use `tier` (not `args.tier`) in `new_run_state(...)` and include it plus `reasons` in the returned dict:

```python
    st = run_state.new_run_state(run_id, args.feature, args.request, tier=tier, pipeline=tier)
    run_state.save(path, st)
    return 0, {"schema": "e2e-dev-harness-v2.start.v1", "run_id": run_id,
               "run_state": str(path), "current_phase": "CREATED",
               "tier": tier, "tier_reasons": reasons}
```

- [ ] **Step 5: Run tier tests + full suite**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: KG change check + commit**

Run `gitnexus_detect_changes({scope:"unstaged"})`; confirm only v2 files changed.

```bash
git add skills/e2e-dev-harness-v2/scripts/harness_v2/adapters/tier \
        skills/e2e-dev-harness-v2/scripts/harness_v2/cli \
        skills/e2e-dev-harness-v2/tests/test_tier_classify.py
git commit -m "feat(harness-v2): port task_tier classification leaf + start --tier auto

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Update v2 coordinator SKILL.md for tiers + final verification

Bring the coordinator doc in line with the new tier behavior and run the whole suite once more.

**Files:**
- Modify: `skills/e2e-dev-harness-v2/SKILL.md`
- Test: `skills/e2e-dev-harness-v2/tests/test_skill_md.py` (extend)

- [ ] **Step 1: Write failing test extension**

Append to `tests/test_skill_md.py`:

```python
def test_skill_md_documents_tiers_and_review_fanout():
    text = SKILL.read_text(encoding="utf-8")
    for tier in ("minimal", "standard", "critical", "audited"):
        assert tier in text
    assert "r1" in text and "r2" in text and "r3" in text  # review fan-out
    assert "--tier" in text
```

- [ ] **Step 2: Run to verify fail**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest tests/test_skill_md.py -q`
Expected: FAIL — current SKILL.md mentions only `minimal`.

- [ ] **Step 3: Update the `## tier` section of `skills/e2e-dev-harness-v2/SKILL.md`**

Replace the final `## tier (M1: minimal)` section with:

```markdown
## tier 与流水线 (M2)

`start --tier <t>` 选择流水线(默认 `minimal`,`auto` 由请求文本分类):

| tier | 活跃阶段 | 说明 |
|---|---|---|
| `minimal` | CREATED→CLARIFIED→RED→IMPLEMENTED→VERIFIED | 跳过 PLANNED/REVIEWED |
| `standard` | 全主干 | 单 reviewer |
| `critical` | 全主干 | REVIEWED 派 r1/r2/r3 三份独立 review(隔离上下文,不 review 自己实现) |
| `audited` | 全主干 | r1/r2/r3 + VERIFIED 增 audit_replay 证据 |

裁剪是结构性的:被跳阶段从计算出的 spine 移除,`next` 越过、导航地图渲染 `– skipped`。每个内建 tier 都过 I2 门禁闭包(`gate_closure_ok`)。门禁校验**真实产物**(文件存在+非空+哈希;`failing_tests`/`passing_tests` 须为命令证据且退出码正确)。
```

- [ ] **Step 4: Run full suite (final green gate)**

Run: `cd skills/e2e-dev-harness-v2 && python -m pytest -q`
Expected: PASS — full suite green (baseline 25 + all new tests).

- [ ] **Step 5: Commit**

```bash
git add skills/e2e-dev-harness-v2/SKILL.md skills/e2e-dev-harness-v2/tests/test_skill_md.py
git commit -m "docs(harness-v2): coordinator SKILL.md documents M2 tiers + review fan-out + artifact gates

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Exit checklist (M2 done?)

- [ ] **R1**: fake-path / empty-file evidence does NOT pass the gate; test-keys require valid command-evidence with correct exit code; e2e test lands real artifacts to reach VERIFIED; `test_fake_path_evidence_never_reaches_verified` is green. ✅ hard standard
- [ ] **R1' (L4)**: `e2e-harness-planning` delegates to `superpowers:writing-plans` (output `plan`); `e2e-harness-review` delegates to `superpowers:requesting-code-review`/`receiving-code-review` (output `review`); both reference the v2 CLI and not the legacy one. ✅ hard standard
- [ ] **Tier scaling**: standard/critical/audited pipelines exist; each tier's exit_gate sets are assertable.
- [ ] **Phase pruning**: structural — skipped phases removed from spine, rendered `– skipped`; pruned spines pass I2.
- [ ] **Review fan-out**: critical REVIEWED requires ≥3 independent reviews; packet advertises all three.
- [ ] **L1/L2/L5–L7**: navigation enrichment, FAILED path, schema check, atomic save, CLI JSON guard.
- [ ] **§4 seed**: `test_all_builtin_tiers_gate_closed` green for all built-in tiers.
- [ ] Full suite green; `gitnexus_detect_changes` shows only `skills/e2e-dev-harness-v2/` + the two reworked skill files changed.

## Deferred (NOT in this plan, per design §16 + user scope choice)

- Port of scanner / KG-evidence / memory / runtime-adapter leaves with their legacy tests.
- M3 config layer (`pipelines/*.yaml` + `validate-pipeline`) and R2 runtime enforcement (only its seed test — all-tier closure — is pre-landed here).
- M4 frontend adapter, M5 switchover.
