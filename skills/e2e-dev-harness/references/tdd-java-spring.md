# Java/Spring 6 Addendum to Superpowers TDD

Use this reference only after applying `superpowers:test-driven-development`. The Superpowers TDD skill owns the method: write the test first, watch it fail for the expected reason, write minimal production code, watch it pass, then refactor while green.

## Enforcement Modes

TDD is always expected for production changes, but the harness uses scenario-based evidence depth:

| Scenario | Mode | Required proof |
| --- | --- | --- |
| Simple scoped change | `basic` | A red evidence note or command output that states the expected failing test/reason, then normal green unit-test JSON at completion. |
| Standard requirement | `basic` plus R2/R3 review | Red evidence, concrete coverage rows, green command JSON, and reviewer checks. |
| Public API, MQ/DMQ/Kafka, payment/refund, data/schema, auth/security, cross-service | `strict` or `auto` with `critical` tier | Structured red command JSON with non-zero `exit_code`, structured green command JSON with zero `exit_code`, and coverage mapping. |
| Audited/compliance run | `strict` | Strict red/green command evidence plus execution trace and replay. |

Use:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py gate . \
  --phase completion \
  --tdd-mode auto \
  --workflow-tier critical \
  --red-test-evidence docs/agent-runs/<run>/evidence/red-test.json \
  --unit-test-evidence docs/agent-runs/<run>/evidence/green-test.json
```

`basic` keeps simple tasks lightweight. `strict` is for cases where post-hoc tests would hide meaningful delivery risk.

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

Record strict red/green commands with `command_evidence.py` or compatible JSON. Red evidence should have a non-zero exit code; green evidence should pass:

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
## Completion Unit

The default completion unit is all assigned acceptance criteria for the current global design or service design slice.
After one AC turns green, continue with the next assigned AC until `e2e_dev_harness.py ac-progress` is ready.
Do not ask the user whether to continue or start R3 after only AC-1 unless the user explicitly scoped the run to AC-1 only.
