"""Task 1: verification replay allow-list coverage for go/cargo/pnpm/yarn/jest.

These pin the conservative test-subcommand contract: a first-class test runner
invocation is replayable, but a non-test subcommand of the same tool is NOT.
"""
from e2e_harness.adapters.evidence import validate


def test_replay_allows_first_class_test_commands():
    allowed = [
        "go test ./...",
        "cargo test --all",
        "pnpm test",
        "pnpm run test",
        "yarn test",
        "yarn run test",
        "npx jest --runInBand",
        "npx jest test",
    ]
    for command in allowed:
        assert validate._replay_command_allowed(command), command


def test_replay_rejects_non_test_commands_for_new_runners():
    rejected = [
        "go build ./...",
        "cargo build",
        "pnpm install",
        "yarn add lodash",
        "npx jest --init",
    ]
    for command in rejected:
        assert not validate._replay_command_allowed(command), command


def test_replay_still_allows_existing_runners():
    """Regression guard: rewriting the npx branch must not weaken the existing
    vitest/playwright/npm/python/node/mvn/gradle contracts."""
    allowed = [
        "python -m pytest",
        "python3 -m unittest",
        "pytest",
        "npm test",
        "npm run test",
        "npx vitest test",
        "npx playwright test",
        "node --check src/x.js",
        "mvn test",
        "gradle test",
    ]
    for command in allowed:
        assert validate._replay_command_allowed(command), command


def test_replay_keeps_existing_strictness():
    """Regression guard: bare vitest/playwright (no `test` token) and unrelated
    commands stay rejected after the rewrite."""
    rejected = [
        "npx vitest",
        "npx playwright",
        "npm install",
        "node x.js",
        "rm -rf /",
    ]
    for command in rejected:
        assert not validate._replay_command_allowed(command), command
