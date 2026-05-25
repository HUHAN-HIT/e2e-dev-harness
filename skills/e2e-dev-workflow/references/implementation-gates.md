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
  --rework-dir docs/agent-runs/<run>/rework \
  --review-dir docs/agent-runs/<run>/reviews \
  --handoff-dir docs/agent-runs/<run>/handoffs
```

Planning checks clarification readiness, knowledge graph status, and R1 design review. Implementation additionally requires red-test evidence and R1+R2 reviews. Completion requires design doc, red-test evidence, unit-test command evidence, business review, R1+R2+R3 reviews, coverage matrix, implementation manifest, dependency report when cross-service, closed rework, and Spring static check unless explicitly skipped.

## Semantic Reviews

Review requests must include `Phase`, `Reviewer Role`, `Context Package`, `Forbidden`, `Output`, `Developer Agent`, `Reviewer Agent`, and `Reviewer Invocation`.

Review reports must include `Phase`, `Reviewer`, `Review Request`, `Developer Agent`, `Reviewer Agent`, `Reviewer Session`, `Reviewer Invocation`, `Request Hash`, `Independence`, `Context Boundary`, `No Code Changes`, `Scope`, `Inputs Reviewed`, `Findings`, `Required Rework`, and `Status`.

Blocking conditions include missing request/report files, phase mismatch, output mismatch, request hash mismatch, invalid invocation JSON, placeholder IDs, same-agent IDs, non-independent context, self-review, unsupported statuses, and missing service-local R2/R3 phases.

Allowed review statuses include `approved`, `verified`, `clear`, and `passed`. Blocking statuses include `blocked`, `changes-requested`, `needs-rework`, `open`, and `in-progress`.

Reviewer Invocation JSON must match Developer/Reviewer/Session, point to the same request and output, declare `fork_context: false`, use request-only/no-inherited context policy, and be `status: completed`.

## Completion Evidence

Coverage matrix rows must map every acceptance criterion to use cases, service/module ownership, tests, code refs, business review, and accepted status such as `implemented`, `covered`, `done`, `pass`, `passed`, or `verified`.

For multi-module or artifact-heavy designs, `implementation-manifest.md` must include `id`, `module`, `artifact`, `artifact_type`, `source`, `required`, `tests`, `status`, and `evidence`. Required rows must point to existing artifacts, real tests, and implemented or verified status.

Unit-test evidence must be structured JSON with `command` and integer `exit_code`. Plain text such as `PASS` is not accepted.

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
