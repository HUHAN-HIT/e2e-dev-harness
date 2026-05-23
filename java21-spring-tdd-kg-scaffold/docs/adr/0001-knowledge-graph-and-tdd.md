# ADR 0001: Knowledge Graph First, TDD Implementation

## Status

Accepted

## Context

The repository can be a single Spring Framework 6.x service or a Maven monorepo with multiple services. Changes should be based on current code structure and clarified use cases, not stale assumptions.

## Decision

Before implementation, refresh repository knowledge with GitNexus, Graphify, or both:

- Use GitNexus for Java/Spring/Maven code topology and impact analysis.
- Add Graphify for design documents, diagrams, screenshots, PDFs, or broad visual project understanding.
- Use both for cross-service changes driven by architecture/design material.

Implementation follows `superpowers:test-driven-development` when available:

- Clarify requirements and use cases first.
- Write the first failing test before production code.
- Watch the test fail for the expected reason.
- Implement the smallest passing change.
- Refactor only while green.

## Consequences

This adds a small upfront gate, but keeps changes tied to testable behavior and current repository knowledge.
