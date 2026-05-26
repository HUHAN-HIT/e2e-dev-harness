# Common Review Issues

This catalog gives reviewer agents concrete examples and 判定标准 for recurring review failures. Profiles reference these Issue ID anchors; gates enforce the structured profile checklist, not this prose.

## missing-acceptance-coverage

Issue ID: `missing-acceptance-coverage`

问题描述: Acceptance criteria are present, but tests, code refs, implementation manifest rows, or coverage-matrix rows do not prove every behavior.

示例:

- AC says "reject unauthorized users", but only the happy path is tested.
- The implementation manifest lists a required artifact with no test evidence.

判定标准:

- Every AC maps to at least one use case, test, code reference, and accepted coverage row.
- Deferred behavior has explicit user approval and a tracked rework/defer item.

## dependency-impact-gap

Issue ID: `dependency-impact-gap`

问题描述: The review accepts an affected-service list without GitNexus, scanner, or explicit path evidence.

示例:

- A controller route changes, but downstream HTTP clients are not checked.
- A DMQ topic constant changes without producer/consumer impact evidence.

判定标准:

- Changed routes, clients, topics, tags, groups, payloads, configuration keys, and service references are scanned or marked non-applicable.
- Cross-service findings are reflected in contracts, service plans, and dependency reports.

## contract-coverage-gap

Issue ID: `contract-coverage-gap`

问题描述: HTTP or DMQ contract behavior is implemented without producer/consumer expectations and tests.

示例:

- API response field changes without client-facing compatibility tests.
- DMQ payload schema changes without topic/tag/group and consumer ACK.

判定标准:

- Contract docs include producer ACK, consumer ACK, tests, non-draft status, and transport-specific details.
- Tests cover success, failure, compatibility, and downstream error behavior where relevant.

## security-negative-path-gap

Issue ID: `security-negative-path-gap`

问题描述: Security-sensitive behavior has only happy-path coverage or relies on assumptions instead of explicit enforcement.

示例:

- Tenant ownership is checked in service code but not at the API entry path.
- Unauthorized, unauthenticated, wrong-role, or wrong-resource cases are not tested.

判定标准:

- Design names the affected auth/authz/tenant/sensitive-data paths.
- Tests prove denial behavior, and implementation enforces boundaries at real entry points.

## sensitive-data-exposure

Issue ID: `sensitive-data-exposure`

问题描述: Sensitive data can leak through logs, API responses, events, persistence, or external calls.

示例:

- Token, credential, payment, or PII fields are logged in an exception path.
- A DTO exposes internal identifiers or secrets not declared in the API contract.

判定标准:

- Sensitive fields are masked, omitted, encrypted, or explicitly approved for exposure.
- Tests or review evidence cover both success and failure paths.

## project-pattern-drift

Issue ID: `project-pattern-drift`

问题描述: Implementation works locally but diverges from established project layering, dependency direction, transaction handling, mapping, or error patterns.

示例:

- A service bypasses the project mapper style with ad hoc DTO assembly.
- A repository or client dependency is introduced in the wrong layer.

判定标准:

- Code matches nearby module patterns unless the design explicitly approved a new pattern.
- Divergence has a concrete reason, tests, and migration guidance.

## api-contract-drift

Issue ID: `api-contract-drift`

问题描述: API behavior changes without synchronized schema, docs, clients, tests, and compatibility decisions.

示例:

- A response field is renamed but clients and API docs are unchanged.
- Validation becomes stricter without backward-compatibility risk review.

判定标准:

- Request/response schemas, status codes, error bodies, docs, clients, and tests agree.
- Breaking changes are versioned, approved, or intentionally deferred with evidence.

## error-contract-gap

Issue ID: `error-contract-gap`

问题描述: Failure behavior is unspecified or inconsistent with existing API and retry/idempotency semantics.

示例:

- Duplicate submit behavior is undefined.
- Downstream timeout returns a status/body inconsistent with similar endpoints.

判定标准:

- Error codes, response bodies, retry behavior, idempotency, and conflict handling are documented and tested.
- Implementation follows existing project error conventions.

## findings-without-rework

Issue ID: `findings-without-rework`

问题描述: A reviewer records Findings but leaves Required Rework empty or marks the review as approved without routing the issue.

示例:

- Findings: "missing negative test"; Required Rework: "None"; Status: "approved".

判定标准:

- Findings either become required rework with a return phase or the review uses a blocking/with-rework status.
- Completion proceeds only after rework is verified or explicitly deferred with user approval.
