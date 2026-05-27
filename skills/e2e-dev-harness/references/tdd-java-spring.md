# Java/Spring 6 Addendum to Superpowers TDD

Use this reference only after applying `superpowers:test-driven-development`. The Superpowers TDD skill owns the method: write the test first, watch it fail for the expected reason, write minimal production code, watch it pass, then refactor while green.

## Test Selection

Within that cycle, use the lowest-cost Java/Spring test that proves the behavior:

| Risk | Test style |
| --- | --- |
| Business rule, calculation, state transition | JUnit unit test without Spring |
| Application orchestration | Unit test with fakes or mocks |
| JSON validation, status codes, controller mapping | Spring MVC test with `MockMvcBuilders` |
| Persistence query, transaction, mapping | repository/data test |
| Cross-module contract | producer/consumer contract or integration test |
| Cross-service behavior | contract test plus targeted service tests |

## Maven Scope

Use the narrowest Maven command that runs the red/green test quickly.

For one module:

```bash
mvn -pl services/<service> -am test
```

For shared code touched by several services:

```bash
mvn -pl shared/<module>,services/<service-a>,services/<service-b> -am test
```

Before finishing:

```bash
mvn test
```

Record each passing command as JSON evidence for the completion gate:

```json
{
  "command": "mvn -pl services/<service> -am test",
  "exit_code": 0,
  "stdout_tail": "BUILD SUCCESS",
  "stderr_tail": ""
}
```

## Coding Biases

- Keep domain rules in plain Java classes or records when practical.
- Keep controllers focused on transport mapping.
- Keep application services focused on use-case orchestration.
- Avoid starting containers or Spring contexts for tests that can run as plain JUnit.
- Prefer explicit validation and error tests over snapshot-style assertions.
- Refactor only while green, as required by Superpowers TDD.
- For Spring-managed constructor dependencies declared in this repository, register the injected type with a component stereotype or an explicit `@Bean`; `spring_static_check.py` is the completion safety net for this.

## Audit Field Template

When an acceptance criterion creates or updates persisted business data, tests should name the expected audit behavior. Use the project convention when one exists; otherwise start with:

| Operation | Required audit fields |
| --- | --- |
| Create | `createdAt`, `createdBy`, and `updatedAt` when the row is immediately current. |
| Update/refund/callback status change | `updatedAt` plus the actor/source field used by the project. |

For update-like flows such as refunds, callbacks, status transitions, or MQ-consumer side effects, add at least one red test that fails when `updatedAt` is not changed. If `createdBy` is system-derived, assert the system actor or explicitly document why the project does not store it.
