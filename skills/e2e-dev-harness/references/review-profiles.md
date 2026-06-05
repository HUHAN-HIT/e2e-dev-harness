# Review Profiles

Use review profiles when a project needs repeatable semantic-review expectations across Codex, Claude Code, Gemini CLI, CI, or any other agent runtime.

Profiles are plain JSON. They guide reviewer agents and let `reviewer_gate.py` enforce required checklist coverage without relying on chat memory.

## Discovery Order

Explicit CLI input wins:

```bash
e2e-harness exec reviewer_gate.py . \
  --review-dir docs/agent-runs/<run>/reviews \
  --review-profile .e2e/review-profile.json
```

When `--review-profile` is omitted, the gate auto-discovers the first project profile that exists:

1. `.e2e/review-profile.json`
2. `.e2e/review-profiles/default.json`
3. `docs/review-profile.json`
4. `docs/review-profiles/default.json`

If none exists, no profile is enforced. Bundled profiles are never auto-enabled for a project; use them explicitly by path or name.

```bash
e2e-harness exec reviewer_gate.py . --review-profile default
e2e-harness exec reviewer_gate.py . --review-profile security-heavy
e2e-harness exec reviewer_gate.py . --review-profile api-first
```

Use `--review-profile off` to disable profile loading in custom harnesses.

## Extending Profiles

Create a project profile by extending a bundled or nearby profile:

```json
{
  "name": "project-default",
  "extends": "default",
  "required_checklist": {
    "implementation": [
      {
        "id": "project-specific-risk",
        "title": "Project-specific risk",
        "description": "Reviewer must check the project-specific failure mode.",
        "severity": "blocker",
        "references": ["docs/review-guides/project-risk.md"],
        "required": true
      }
    ]
  }
}
```

`extends` can be a string or a list. Relative paths resolve from the child profile first, then the repository root, then bundled `review-profiles/`.

Checklist items are merged by `id`. A child item with the same `id` overrides parent fields while preserving parent order; new child items are appended.

## Checklist Schema

Each item may include:

| Field | Meaning |
| --- | --- |
| `id` | Stable machine-readable checklist id used in reviewer reports. |
| `title` | Human-readable name. |
| `description` | What the reviewer should inspect. |
| `severity` | `blocker` blocks when missing; `warning` records a warning but does not block. |
| `references` | Local docs, anchors, or external references the reviewer should read when needed. |
| `required` | Defaults to `true`; set `false` for non-enforced guidance. |

Reviewer reports satisfy a profile item with checked Markdown:

```markdown
- [x] project-specific-risk: checked tenant-boundary behavior and failure paths.
```

## Bundled Profiles

- `default`: baseline R1/R2/R3 completeness, dependency, contract, security, and project-pattern checks.
- `security-heavy`: extends `default` for authorization, sensitive data, and abuse-path work.
- `api-first`: extends `default` for API compatibility, contract tests, and error-model work.

For issue descriptions, examples, and criteria, read `references/common-review-issues.md`.
