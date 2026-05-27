# Implementation Gates

Use this reference when running `gate`, `verify`, `guard`, completion checks, or rework loops.

## Phase Gates

Planning gate:

```bash
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py gate . \
  --phase planning \
  --design-doc docs/design/<feature>.md
```

Implementation gate:

```bash
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py gate . \
  --phase implementation \
  --design-doc docs/design/<feature>.md \
  --red-test-evidence docs/agent-runs/<run>/evidence/red-test.txt
```

Completion gate:

```bash
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py gate . \
  --phase completion \
  --design-doc docs/design/<feature>.md \
  --red-test-evidence docs/agent-runs/<run>/evidence/red-test.txt \
  --implementation-manifest docs/agent-runs/<run>/evidence/implementation-manifest.md \
  --coverage-matrix docs/agent-runs/<run>/evidence/coverage-matrix.md \
  --unit-test-evidence docs/agent-runs/<run>/evidence/green-test.txt \
  --business-review docs/agent-runs/<run>/evidence/business-review.md \
  --dependency-report docs/agent-runs/<run>/evidence/cross-service-dependencies.json \
  --contract-dir docs/agent-runs/<run>/contracts \
  --memory-updates docs/agent-runs/<run>/proposed-memory-updates.md \
  --requirements-archive docs/agent-runs/<run>/requirements-archive.md \
  --rework-dir docs/agent-runs/<run>/rework \
  --review-dir docs/agent-runs/<run>/reviews \
  --handoff-dir docs/agent-runs/<run>/handoffs
```

Planning checks clarification readiness, knowledge graph status, and R1 design review. Implementation additionally requires red-test evidence and R1+R2 reviews. Completion requires design doc, red-test evidence, unit-test command evidence, business review, R1+R2+R3 reviews, coverage matrix, implementation manifest, dependency report when cross-service, closed rework, and Spring static check unless explicitly skipped.

## Semantic Reviews

Review requests must include `Phase`, `Reviewer Role`, `Context Package`, `Forbidden`, `Output`, `Developer Agent`, `Reviewer Agent`, and `Reviewer Invocation`. When a project uses a review profile, include `Review Profile` and a `Required Review Checklist` section.

Review reports must include `Phase`, `Reviewer`, `Review Request`, `Developer Agent`, `Reviewer Agent`, `Reviewer Session`, `Reviewer Invocation`, `Request Hash`, `Independence`, `Context Boundary`, `No Code Changes`, `Scope`, `Inputs Reviewed`, `Findings`, `Required Rework`, and `Status`.

Blocking conditions include missing request/report files, phase mismatch, output mismatch, request hash mismatch, invalid invocation JSON, placeholder IDs, same-agent IDs, non-independent context, self-review, unsupported statuses, findings without required rework or a blocking/with-rework status, missing review-profile checklist items, and missing service-local R2/R3 phases.

Allowed review statuses include `approved`, `verified`, `clear`, and `passed`. Blocking statuses include `blocked`, `changes-requested`, `needs-rework`, `open`, and `in-progress`.

Review profile checks load from explicit `--review-profile <json-or-name>` first. If omitted, the gate auto-discovers the first project profile at `.e2e/review-profile.json`, `.e2e/review-profiles/default.json`, `docs/review-profile.json`, or `docs/review-profiles/default.json`. If none exists, no profile is enforced. Bundled profiles stay opt-in:

```text
skills/e2e-dev-workflow/review-profiles/default.json
skills/e2e-dev-workflow/review-profiles/security-heavy.json
skills/e2e-dev-workflow/review-profiles/api-first.json
```

Profiles may use `extends` to inherit bundled or project profiles. Checklist items support `description`, `severity`, and `references`; missing `severity: blocker` items block, while missing `severity: warning` items appear in gate warnings. For schema, discovery, and common issue guidance, read `review-profiles.md` and `common-review-issues.md`.

Required checklist items must appear in the review report as checked Markdown items such as:

```markdown
- [x] security-negative-paths: Verified authorization and failure behavior.
```

Reviewer Invocation JSON must match Developer/Reviewer/Session, point to the same request and output, declare `fork_context: false`, use request-only/no-inherited context policy, and be `status: completed`.

## Completion Evidence

Coverage matrix rows must map every acceptance criterion to use cases, service/module ownership, tests, code refs, business review, and accepted status such as `implemented`, `covered`, `done`, `pass`, `passed`, or `verified`.
The `tests` and `code_refs` cells must be concrete evidence, not generic status text:
name a test file/class/command and a production code path such as `PaymentService#complete -> PaymentCallbackDmqSender.send`.
For messaging/event ACs, coverage must name the sender/producer/publisher path and send/publish/topic/payload test evidence.
For audit or null-safety ACs, coverage must name the audit fields or null/missing/empty tests that prove the behavior.

For multi-module or artifact-heavy designs, `implementation-manifest.md` must include `id`, `module`, `artifact`, `artifact_type`, `source`, `required`, `tests`, `status`, and `evidence`. Required rows must point to existing artifacts, real tests, and implemented or verified status.

Unit-test evidence must be structured JSON with `command` and integer `exit_code`. Plain text such as `PASS` is not accepted.

The requirements archive summarizes the final clarified requirement, acceptance-criteria status, use-case coverage, impacted services/contracts, evidence links, review/rework outcome, promoted memory entries, and follow-up opportunities. It is recommended for every completed run and required by strict completion workflows. When `--requirements-archive` is omitted, the gate auto-discovers `docs/agent-runs/<run>/requirements-archive.md` from other artifacts in the same run. Read `requirements-archive.md`.

If the design is cross-service, completion requires the dependency report. Any unresolved URL/topic/tag/service mapping question blocks completion.

If contracts are declared or `--require-contracts` is used, every HTTP/DMQ contract needs producer ACK, consumer ACK, contract tests, and non-draft status. DMQ contracts must include topic, tag, and group.

The Spring static check runs by default. It catches repository-local constructor-injected types that are not Spring components or beans, plus shared `SimpleDateFormat` fields inside Spring components.

## Strict Workflow Guard

Use the guard when the model must not skip scripts:

```bash
python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py verify . \
  --strict-workflow \
  --run-gate \
  --phase completion \
  --design-doc docs/design/<feature>.md \
  --red-test-evidence docs/agent-runs/<run>/evidence/red-test.txt \
  --implementation-manifest docs/agent-runs/<run>/evidence/implementation-manifest.md \
  --coverage-matrix docs/agent-runs/<run>/evidence/coverage-matrix.md \
  --unit-test-evidence docs/agent-runs/<run>/evidence/green-test.txt \
  --business-review docs/agent-runs/<run>/evidence/business-review.md \
  --dependency-report docs/agent-runs/<run>/evidence/cross-service-dependencies.json \
  --contract-dir docs/agent-runs/<run>/contracts \
  --memory-updates docs/agent-runs/<run>/proposed-memory-updates.md \
  --requirements-archive docs/agent-runs/<run>/requirements-archive.md \
  --rework-dir docs/agent-runs/<run>/rework \
  --review-dir docs/agent-runs/<run>/reviews \
  --handoff-dir docs/agent-runs/<run>/handoffs \
  --status-file docs/agent-runs/<run>/evidence/verify.json

python skills/e2e-dev-workflow/scripts/e2e_dev_workflow.py guard . \
  --verify-status docs/agent-runs/<run>/evidence/verify.json \
  --strict \
  --require-completion
```

Strict guard blocks missing prepare, disabled dependency scan, disabled dependency report writing, skipped Maven, skipped Spring static check during completion, missing clarification status, missing completion gate, failed completion gate, missing independent semantic review evidence, failed Maven, and unresolved dependency questions. A skip can pass only with an approval file containing `Approval: user-approved`.

## Rework Protocol

Do not directly patch production code when missed requirements, missing tests, failed tests, multi-service contract gaps, or business logic risks are found after implementation.

Create global rework at:

```text
docs/agent-runs/<run>/rework/rework-NNN.md
```

Create service-local rework at:

```text
docs/agent-runs/<run>/service-plans/<service>/rework-NNN.md
```

Required fields are `Source`, `Related AC`, `Affected Services`, `Problem Type`, `Return Phase`, `Required Red Test`, `Evidence`, `Exit Criteria`, and `Status`.

Return phase routing:

- `unclear-requirement` and `missing-acceptance`: return to `clarify`.
- `missing-use-case` and `business-logic-risk`: return to `use-case-design`.
- `missing-test`: return to `test-case-design`.
- `missing-code` and `test-failure`: return to `tdd-implement`.
- `multi-service-contract`: return to `plan`.

Only `Status: verified` or `Status: deferred` with `Approval: user-approved` can pass completion. Rework implementation still follows Superpowers TDD: add or update the red test, observe the expected failure, implement minimally, rerun verification, then close the item.
