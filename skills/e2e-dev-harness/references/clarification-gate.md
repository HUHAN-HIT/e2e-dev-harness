# Clarification Gate

The gate prevents coding before the problem is testable.
Run it with `e2e_dev_harness.py clarify`; `gate --phase clarification` is not a valid command.

## Required Fields

- Restated Intent with user confirmation provenance for normal interactive `clarify` runs
- Goal
- Non-goals or out-of-scope items
- Affected services/modules
- Actors or callers
- Use cases with happy and failure paths
- API, message, database, cache, or configuration changes
- Change Logic for public API, messaging, data, auth, payment, refund, or cross-service changes
- Impact Summary for public API, messaging, data, auth, payment, or cross-service changes
- Acceptance criteria
- Test design
- Open questions

Acceptance criteria may be written as explicit IDs (`AC-1`, `AC2`) or as plain bullets. The gate canonicalizes explicit IDs to `AC-n`; plain bullets are assigned `AC-1`, `AC-2`, and so on for coverage-matrix checking.

## Restated Intent

For interactive runs, add:

```markdown
## Restated Intent
- The agent understands the user wants ...
- User confirmation: confirmed-by: user @<date/session/artifact>.

## Open Questions
- None. confirmed-by: user @<date/session/artifact>
```

`clarify` requires Restated Intent and user confirmation provenance by default. Use
`--no-require-intent` or `--no-require-user-confirmation` only for non-interactive
replay or explicitly documented degradation. `gate --require-intent` still makes
Restated Intent a hard blocker in implementation-gate replay.

Do not mark Open Questions as `None`, `resolved`, or `confirmed` from agent-only
reasoning. When the answer came from the user, record provenance such as
`confirmed-by: user @2026-06-02-session`. When the answer is evidence-backed
rather than user-provided, keep the question open or explicitly defer it out of
scope with evidence before rerunning clarify.

During the `CREATED` lifecycle, `next` and `phase_guard` expose a `clarification_interaction` contract. The active TodoList must include a user-facing step to confirm Restated Intent and resolve open questions before planning, TDD, reviewer dispatch that depends on clarified behavior, or production-code edits. If `clarify` finds unresolved items, its JSON includes `interaction_required`, `questions_to_ask_user`, and `interaction_contract` so the agent can ask the user directly instead of guessing from blocked reasons.

The interaction contract keeps `questions_to_ask_user` for existing callers and also exposes `ask_user_schema: codex.request_user_input.v1` plus `ask_user_requests`. Each request has a stable `id`, short `header`, user-facing `question`, selectable `options`, and `provenance_required`. The contract also includes `runtime_action.tool: request_user_input` with sanitized `runtime_action.arguments.questions`; Codex coordinators should call that action instead of merely printing the questions. Text-only runtimes should present the same options and record the selected answer as `confirmed-by: user @<date/session/artifact>` in the design doc.

When an acceptance criterion or use case declares MQ/DMQ/Kafka/JMS notification behavior, the design must also state the cross-layer call chain and sender/producer injection point. Example:

```markdown
## Integration Call Chain
- PaymentController -> PaymentService -> PaymentCallbackDmqSender.send(topic, tag, payload).
- Sender injection: PaymentService constructor injects PaymentCallbackDmqSender.
```

This prevents a design from saying "publish MQ notification" while leaving the implementation agent to guess where orchestration and sender wiring belong.

## Change Logic

For public API, HTTP, MQ/DMQ/Kafka/JMS, database/schema, configuration, auth/security, payment, refund, or cross-service changes, include a compact `Change Logic` section before implementation.

Required shape:

```markdown
## Change Logic
- Current behavior: refund reconciliation records differences but does not emit auto-handle result notifications.
- Target behavior: long-pending differences update local state and emit AutoHandleResultNotifyMQ.
- Runtime path: ReconcileController -> ReconciliationTaskExecutor -> ReconcileAutoHandler -> AutoHandleResultNotifySender.send.
- State/data/API/event effects: updates refund status, writes audit fields, publishes MQ payload, returns batch id.
- Compatibility or migration notes: existing diff-found topic remains unchanged.
```

The section should explain what logic changes, not only list files. It gives R1/R3 reviewers a path to verify implementation completeness.

## Bounded Impact Summary

For public API, HTTP, MQ/DMQ/Kafka/JMS, database/schema, configuration, auth/security, payment, refund, or cross-service changes, include a compact `Impact Summary` before implementation.
Use GitNexus impact analysis and the deterministic dependency scanner when available, but put raw output in an evidence file instead of the design body.

Required shape:

```markdown
## Impact Summary
- Source: GitNexus impact + dependency scanner
- Raw Evidence: docs/agent-runs/<run>/evidence/impact-analysis.json

| type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
| --- | --- | --- | --- | --- | --- |
| HTTP | POST /api/refunds/callback | merchant-admin | AC-1 | controller contract test | medium |
| MQ | topic=payment_callback, tag=success | settlement-service | AC-2 | sender payload test; consumer ACK | high |
```

Keep the table to direct callers/consumers and high-risk indirect effects, at most 12 rows.
If there is no public/cross-service/interface impact, write a single `N/A` row with the raw evidence path or manual non-applicability note.
Do not paste full GitNexus call graphs into the design.

## Stop Conditions

Stop before production-code edits if any question changes:

- Public API shape, status codes, events, or message schema
- Data model, migration, transactional boundary, or consistency expectation
- Authorization, validation, idempotency, retry, timeout, or error behavior
- Which microservice owns the behavior
- Which tests prove acceptance

Implementation may proceed when unresolved items are cosmetic, wording-only, or explicitly deferred outside the current scope.

## Output Shape

Keep the clarification response compact:

```markdown
Assumptions:
- ...

Use cases:
- UC1: ...

Acceptance tests:
- ...

Open questions:
- None. confirmed-by: user @<date/session>
```
