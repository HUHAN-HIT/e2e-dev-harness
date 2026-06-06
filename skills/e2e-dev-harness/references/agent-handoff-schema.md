# Agent Handoff Schema

Use this schema when splitting work across Requirements Clarifier, Use Case Designer, R1/R2/R3 semantic Reviewer agents, Test Case Developer, service-scoped Code Developer, and Coverage Reviewer agents.

Each agent writes a Markdown handoff file with YAML frontmatter:

```yaml
---
agent: requirements-clarifier
agent_id: developer-agent-1
status: draft | blocked | ready
service_scope: all-services | services/<service> | <module>
inputs:
  - user request
  - AGENT.md load order
  - knowledge graph status
outputs:
  - docs/agent-runs/<date-feature>/evidence/impact-summary.md
input_hashes:
  - user-request sha256:<64-hex>
output_hashes:
  - docs/agent-runs/<date-feature>/evidence/impact-summary.md sha256:<64-hex>
blocked_by: []
consumed_by:
  - use-case-designer
open_questions: None
memory_updates_proposed: []
---
```

## Body Sections

- Summary
- Facts used
- Decisions made
- Open questions
- Downstream assumptions
- Verification or review evidence
- Proposed memory updates

## Role Contracts

Each role owns a narrow context boundary and writes only its promised outputs. Later roles consume the previous files as artifacts instead of reloading the whole conversation.
Design, test, code, semantic review, and coverage are incompatible role groups. The same `agent_id` must not own tasks across those groups in `agent-schedule.json`; every role task references a generated `agent-roles/*.md` template, and handoff files are the communication boundary between groups.

Run `scripts/handoff_gate.py` before a downstream agent consumes a handoff. Use `--require-handoffs` for multi-service, contract/data-risk, or split-agent completion gates so an empty `handoffs/` directory blocks. The gate requires a concrete `agent_id`, a pass status, non-empty inputs/outputs, input/output SHA-256 entries, `consumed_by`, `open_questions: None`, a matching ready marker, and non-template body content in `Summary`, `Facts Used`, `Decisions Made`, `Downstream Assumptions`, and `Verification Evidence`. Draft starter files are intentionally not ready until the owning agent fills them. Do not list the handoff file itself in `outputs` or `output_hashes`; `<handoff>.ready.json` is the only place that records the handoff file hash. `output_hashes` must match the current files they name. Non-output `input_hashes` may record upstream or external artifacts that are not present in the current repository, but they still need a valid `sha256:<64-hex>` value.

Do not hand-roll `python -c "import hashlib"` to compute these values. Run the harness `hash` subcommand, which uses the same byte-exact digest the gate recomputes (so the entries can never drift):

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py hash . \
  --path docs/agent-runs/<run>/evidence/impact-summary.md \
  --path docs/agent-runs/<run>/evidence/another-artifact.md
```

Each `hash_entries[].frontmatter_line` in the output is already formatted as `<repo-relative-path> sha256:<64-hex>` for direct paste into `input_hashes` / `output_hashes`.

Handoff writes must be atomic. Do not hand-assemble the partial/rename/marker
steps; the worker writes the handoff body and frontmatter, then runs one command:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py handoff . \
  --path docs/agent-runs/<run>/handoffs/<handoff>.md \
  --agent <agent-id>
```

`handoff finalize` is the single writer of `<handoff>.ready.json`. It normalizes
`agent_id`/`status: ready`, writes `<handoff>.md` atomically (`.partial` -> rename),
computes the SHA-256, writes the canonical ready marker, then re-runs
`handoff_gate` locally. If anything is still missing it reports the exact blockers
and rolls the marker back, so an incomplete handoff never keeps a ready marker.
Only run the raw four-step sequence (write `<handoff>.md.partial`, compute the
final SHA-256, rename to `<handoff>.md`, write `<handoff>.ready.json` with `path`,
`sha256`, `producer_agent`, and `status: ready`) for manual recovery when the CLI
is unavailable.

Consumers read only `<handoff>.md` files that have a matching ready marker. Any leftover `*.partial` file blocks `handoff_gate.py`.

## Contract Artifacts

For HTTP/DMQ dependencies between services, write a contract artifact before parallel service implementation:

```text
docs/agent-runs/<date-feature>/contracts/<contract-id>.md
```

Required fields are `Contract ID`, `Kind`, `Producer Service`, `Consumer Services`, `Payload Schema`, `Compatibility Rule`, `Producer ACK`, `Consumer ACK`, `Contract Tests`, and `Status`. HTTP contracts must include `Endpoint` or `Route`; DMQ contracts must include `Topic`, `Tag`, and `Group`. Run `scripts/contract_gate.py` before service-scoped Code Developer agents implement against the contract.

## Archive Layout

Generated agent files belong under:

```text
docs/agent-runs/<date-feature>/
  exec-plan.md
  prepare.json (optional status output)
  handoffs/
    01-requirements-clarifier.md
    02-use-case-designer.md
    03-test-case-developer.md
    04-code-developer.md
  service-designs/
    <service>.md
  review-requests/
    R1-design-review-request.md
    R2-test-review-request.md
    R3-implementation-review-request.md
  reviews/
    R1-design-review.md
    R2-test-review.md
    R3-implementation-review.md
  contracts/
    <contract-id>.md
  service-plans/
    <service>/
      implementation-plan.md
      test-impact-plan.json
      code-agent.md
      review-requests/
        R2-test-review-request.md
        R3-implementation-review-request.md
      reviews/
        R2-test-review.md
        R3-implementation-review.md
      unit-test-evidence.txt
      coverage-matrix.md
      business-review.md
      rework-NNN.md
  evidence/
    knowledge-graph-refresh.json
    red-test.txt
    green-test.txt
    coverage-matrix.md
    business-review.md
    verification.txt
  proposed-memory-updates.md
  rework/
    rework-NNN.md
```

Keep `AGENT.md` files in their directory scopes. Do not move them into this archive.

Knowledge graph refresh skips `agent-runs` by default so previous execution traces do not pollute current project analysis.

Requirements Clarifier:
- Owns goal, non-goals, constraints, acceptance criteria, open questions.
- Stops while behavior/API/data/test-impacting questions remain unresolved.

Use Case Designer:
- Owns happy paths, failure paths, data effects, contracts, cross-service sequence.
- Maps every acceptance criterion to at least one use case or marks it deferred.

Test Case Developer:
- Owns test strategy, first red test, contract tests, Maven scope, red-test evidence path.
- Does not modify production code.
- Must be a different agent from Requirements/Use Case design and Code Developer roles.

Semantic Reviewers:
- R1 Design Reviewer checks requirements, AC completeness, affected modules, security-sensitive paths, and reference-pattern consistency before planning.
- R2 Test Reviewer checks red-test depth, happy/failure coverage, security paths, and contract coverage before production code.
- R3 Implementation Reviewer checks code/test completeness, security flaws, anti-patterns, and project-pattern consistency before completion.
- In `single-review` mode, the same reviewer role family may cover R1/R2/R3, but only through separate phase-boundary review requests, outputs, invocation JSON files, and reviewer sessions. A single consolidated report does not satisfy the gate.
- Review requests use fields: `Phase`, `Reviewer Role`, `Review Profile`, `Context Package`, `Allowed Inputs`, `Forbidden`, and `Output`. Projects can pass the same profile to gates with `--review-profile <json-or-name>` or rely on project profile discovery under `.e2e/` or `docs/`.
- Review reports use fields: `Phase`, `Reviewer`, `Review Request`, `Developer Agent`, `Reviewer Agent`, `Reviewer Session`, `Reviewer Invocation`, `Request Hash`, `Independence`, `Context Boundary`, `No Code Changes`, `Scope`, `Inputs Reviewed`, `Findings`, `Required Rework`, and `Status`.
- `Developer Agent`, `Reviewer Agent`, and `Reviewer Session` must be concrete ids, not placeholders. `Developer Agent` and `Reviewer Agent` must be different. `Independence` must be exactly `independent-agent`. `Context Boundary` must be request-scoped with no inherited developer chat context. `No Code Changes` must be confirmed/read-only.
- The `Review Request` file must exist, match the report phase, declare the report as its exact `Output`, assign the same Developer Agent and Reviewer Agent as the report, and hash to the report `Request Hash`.
- The `Reviewer Invocation` JSON must contain runtime isolation proof: `runtime`, isolated `invocation_type`, `developer_session`, `reviewer_session`, `context_pack`, matching Developer/Reviewer ids, matching review request/output paths, `fork_context: false`, request-only/no-inherited `context_policy`, and `status: completed`. The developer and reviewer sessions must be different.
- In multi-service runs, service-local R2 and R3 reviews are required for every `service-plans/<service>/` directory when those phases are required. A global R2/R3 report does not replace service-local review evidence.
- Findings become rework items; reviewer agents do not patch implementation directly.
- If `Findings` is not empty, `Required Rework` must name the rework or the report must use a blocking/with-rework status. Approved reports with findings and no rework are invalid.

Code Developer:
- Owns minimal implementation, red-green-refactor, service-local verification evidence, residual risk report.
- Does not start without approved requirements, use cases, test plan, and red-test evidence.
- Must be a different agent from design and test roles.
- For multi-service work, each Code Developer owns exactly one service/module and writes under `service-plans/<service>/`.
- Does not write R1/R2/R3 semantic review reports.

Coverage Reviewer:
- Owns final design-to-code/test coverage, business logic review, and requirements archive.
- Builds a matrix with `id`, `acceptance`, `use_case`, `service`, `tests`, `code_refs`, `business_review`, and `status`.
- Writes `docs/agent-runs/<run>/requirements-archive.md` as a concise final summary for future requirement analysis.
- Blocks completion if any acceptance criterion lacks test evidence, code refs, or business review.
- Accepts unit-test evidence only when it is structured command JSON with `exit_code: 0`.
- Checks Spring static check results unless the run explicitly documents why the check was skipped.
- Creates a rework item instead of directly asking for code patches when review finds missed behavior, missing tests, failed verification, business-logic risk, or multi-service contract gaps.
- Blocks completion while any rework item is `open`, `in-progress`, `blocked`, or `deferred` without explicit approval.

## Memory Rule

Agents may propose memory updates in their handoff files. The controlling agent writes durable memory only after the fact is verified or user-approved.
