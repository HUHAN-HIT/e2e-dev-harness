# Clarification Gate

The gate prevents coding before the problem is testable.

## Required Fields

- Goal
- Non-goals or out-of-scope items
- Affected services/modules
- Actors or callers
- Use cases with happy and failure paths
- API, message, database, cache, or configuration changes
- Acceptance criteria
- Test design
- Open questions

Acceptance criteria may be written as explicit IDs (`AC-1`, `AC2`) or as plain bullets. The gate canonicalizes explicit IDs to `AC-n`; plain bullets are assigned `AC-1`, `AC-2`, and so on for coverage-matrix checking.

When an acceptance criterion or use case declares MQ/DMQ/Kafka/JMS notification behavior, the design must also state the cross-layer call chain and sender/producer injection point. Example:

```markdown
## Integration Call Chain
- PaymentController -> PaymentService -> PaymentCallbackDmqSender.send(topic, tag, payload).
- Sender injection: PaymentService constructor injects PaymentCallbackDmqSender.
```

This prevents a design from saying "publish MQ notification" while leaving the implementation agent to guess where orchestration and sender wiring belong.

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
- None
```
