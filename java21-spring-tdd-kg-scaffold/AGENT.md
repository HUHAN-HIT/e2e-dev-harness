# Project Agent Instructions

These instructions apply to the whole repository.

## Stack

- Use Java 21.
- Use Spring Framework 6.x directly.
- Do not introduce Spring Boot unless the user explicitly changes the project direction.
- Use Maven modules for services and shared libraries.

## Process

- Load this file before requirement clarification.
- Use discovery scope before affected services are known; do not load every service `AGENT.md` into context.
- Load only affected service `AGENT.md` files before asking service-specific clarification questions or implementing.
- Prefer the unified `e2e_dev_workflow.py prepare` command when the skill is available.
- Clarify requirements and use cases before implementation.
- Refresh the knowledge graph before implementation.
- For complex or cross-service work, maintain an ExecPlan under `docs/design/`.
- Use `superpowers:test-driven-development` for production-code changes.
- Capture red-test evidence before production-code edits.
- Keep memory updates limited to verified facts or user-approved decisions.

## Code Style

- Keep domain logic testable without Spring when practical.
- Keep Spring MVC controllers focused on transport mapping.
- Keep application services focused on use-case orchestration.
- Prefer focused tests over broad Spring contexts unless framework wiring is the risk.
