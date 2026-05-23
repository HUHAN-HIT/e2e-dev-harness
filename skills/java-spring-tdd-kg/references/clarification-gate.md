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
