# Requirements Archive

Use `docs/agent-runs/<run>/requirements-archive.md` as the final feature-level summary after implementation is complete. It sits between noisy run evidence and durable `memory/*.md`: detailed enough for future requirement analysis, concise enough to read before related follow-up work.

## When To Create

Create the archive in the agent-run directory when `plan --create-archive` writes starter artifacts. Complete it during the coverage/completion stage after reviews, rework, tests, and memory decisions are known.

Run completion validation with:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py gate . \
  --phase completion \
  --requirements-archive docs/agent-runs/<run>/requirements-archive.md
```

Use `--require-requirements-archive` when a local gate should block missing archives. `verify --strict-workflow --phase completion --run-gate` also treats the archive as required.

When the archive path is omitted but an anchor artifact is inside `docs/agent-runs/<run>/`, the gate auto-discovers `docs/agent-runs/<run>/requirements-archive.md`. Pass `--requirements-archive` explicitly to override discovery.

## Required Sections

The archive must include:

- `Original Request`
- `Final Clarified Requirement`
- `Scope And Non-Goals`
- `Acceptance Criteria Status`
- `Use Case Coverage`
- `Impacted Services APIs And Contracts`
- `Implementation Evidence`
- `Test Evidence`
- `Review And Rework Summary`
- `Deferred And Residual Risks`
- `Promoted Memory Entries`
- `Follow Up Opportunities`

Use links or repo-relative paths to point at design docs, handoffs, implementation manifests, tests, reviews, dependency reports, contracts, rework, and promoted memory entries. Do not paste whole artifacts into the archive.

## What To Record

`Acceptance Criteria Status` should map each AC to implemented/deferred status and concrete evidence.
Use the coverage matrix as the source of truth: every completed AC needs a named test reference and a named production code reference, not `done` or `implemented` text alone.

`Impacted Services APIs And Contracts` should summarize affected services, public APIs, data ownership, HTTP contracts, DMQ topic/tag/group details, and non-applicability decisions.

`Review And Rework Summary` should name R1/R2/R3 review status and whether rework is verified, deferred with approval, or not applicable.

`Promoted Memory Entries` should list entries promoted from `proposed-memory-updates.md` or explicitly say none were promoted.

`Follow Up Opportunities` should capture useful next work without turning it into unapproved scope.

## Validation

Validate directly:

```bash
python skills/e2e-dev-harness/scripts/requirements_archive.py . \
  --archive docs/agent-runs/<run>/requirements-archive.md \
  --json
```

The validator blocks missing required sections, empty section bodies, placeholder markers such as `TBD` or `<...>`, missing files, and paths outside the repository.
