# Migration: e2e-dev-harness → e2e-dev-harness-v2 (0.2.0)

v2 is now the **default, canonical** delivery harness. The legacy `skills/e2e-dev-harness/`
skill has been retired and deleted. This guide covers what changed and how to recover any
intentionally-deferred legacy capability.

## What changed

### CLI: 35 verbs → 6 (+1)
The sprawling legacy command surface collapses to a terminating spine. Mapping (design §6):

| v2 verb | replaces | purpose |
|---|---|---|
| `start` | start / prepare / install | create the single run-state |
| `next` | next / map / doctor / preflight / ac-progress | advance the spine or return one blocker |
| `dispatch` | dispatch-next / -beat / -ack | emit one worker packet |
| `submit` | dispatch-complete / -finish / handoff / hash | record worker evidence + mark done |
| `gate` | gate / verify / guard / clarify | run a phase's declarative exit gate |
| `status` | dispatch-status / timeline | human-readable navigation map |
| `validate-pipeline` | — (new) | validate a custom pipeline against the invariants |

### Entry points
- **Python console scripts** now target `harness_v2.cli.main:main`:
  `e2e-harness-v2` (canonical), plus `e2e-dev-harness` / `e2eh` aliases retained for muscle memory.
- **Node CLI** (`e2e-harness`, `bin/e2e-harness.js`) dispatches v2 verbs to `scripts/e2e_dev_harness_v2.py`.
- New runtime dependency declared: **PyYAML** (`pyyaml>=6`) — pipelines are YAML.

### Hooks (tool-layer enforcement)
The legacy `phase_guard.py` (PreToolUse) and `harness_stop_guard.py` (Stop) are replaced by the
U7 v2 hook layer:

| legacy | v2 |
|---|---|
| `phase_guard.py` | `scripts/harness_v2/adapters/hooks/phase_guard_v2.py` |
| `harness_stop_guard.py` | `scripts/harness_v2/adapters/hooks/stop_guard_v2.py` |
| `install_hooks.py` | `e2e-harness init` materializes the hooks directly (or `tools/install-e2e-dev-harness.mjs --with-hooks --runtime claude`) |

Example configs ship at `skills/e2e-dev-harness-v2/hooks/` (claude settings + opencode plugin);
the installer rewrites `__HARNESS_V2_SCRIPTS__` to the installed absolute scripts dir and merges
the `PreToolUse` / `Stop` entries into `<project>/.claude/settings.json`.

Recommended path: from inside the business repo run `e2e-harness init` — it installs the
skill if missing, wires both hooks into `.claude/settings.json` (idempotent, with backup), and
verifies. See the README Quick Start §2.

### Tiers / pipelines
`task_tier.py` heuristics → declarative `pipelines/*.yaml` (`minimal` / `standard` / `critical` /
`audited`) + user-custom pipelines validated by `validate-pipeline`.

## Parity

Every capability the legacy skill offered is **covered**, **deferred** (recorded below, recoverable),
or **dropped** per design §16. Full table: `docs/superpowers/specs/2026-06-08-harness-v2-u6-cutover-design.md` §2.

## Deferred / recoverable

These were intentionally not ported (YAGNI, design §5/§6/§16). They are **not lost** — recover from
git history if a real flow needs them:

| capability | legacy module | recover |
|---|---|---|
| session checkpoint | `session_checkpoint.py` | see below |
| recover / gc / timeline | `gc_run.py`, `execution_trace.py` | see below |
| dir-graph contract | `dir_graph.py` | see below |

To recover a deleted legacy file, find the removal commit and read the file from its parent:

```bash
# find the Stage 5 removal commit
git log --oneline --diff-filter=D -- skills/e2e-dev-harness | head -1
# read a file as it existed just before deletion (<sha> = that removal commit)
git show <sha>^:skills/e2e-dev-harness/scripts/session_checkpoint.py
```

## Dropped (not recoverable as designed)
- legacy state aliases and the `worker_running_unverified` compatibility shim — superseded by the
  single v2 state enum (design §5). v2 does not reintroduce them.
