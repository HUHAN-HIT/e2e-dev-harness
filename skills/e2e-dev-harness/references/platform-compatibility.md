# Platform Compatibility

Use this skill as an agent-neutral workflow package. The stable contract is the `SKILL.md`, `references/`, `scripts/`, and `review-profiles/` directory structure; Codex-specific UI metadata under `agents/openai.yaml` is optional.

## Runtime Mapping

| Runtime | Skill location | Invocation guidance |
| --- | --- | --- |
| Codex | project `skills/`, `~/.codex/skills`, or `~/.agents/skills` | Use the native skill loader when available; otherwise read `SKILL.md` and run bundled Python scripts directly. |
| Claude Code | project `skills/` or `~/.claude/skills` | Use the `Skill` tool when available. If unavailable, read `SKILL.md`, then load referenced files only when needed. |
| Gemini CLI | project `skills/` or `~/.gemini/skills` | Activate/read the skill, then use the same Python CLI and artifact conventions. |
| OpenCode | project `skills/`, `.opencode/skills`, or configured skill path | Treat `SKILL.md` as the entrypoint and install `.opencode/plugins/e2e-dev-harness.js` with `install_hooks.py --runtime opencode` for pre-tool blocking. |
| Other agents | project `skills/` or configured skill path | Treat `SKILL.md` as the entrypoint and scripts as deterministic gates. |

## Tool Name Equivalents

- Skill loading: use the runtime's native skill/activate/read mechanism. If none exists, open `SKILL.md` manually.
- Subagents: prefer native subagent/session support. If unavailable, use a fresh separate reviewer session with only the review request and allowed input files.
- Task tracking: use the runtime's todo/checklist tool when available. If unavailable, write checklist progress into the agent-run artifact.
- Shell commands: run the Python scripts directly; they avoid Codex-only APIs.
- OpenCode plugins: use `.opencode/plugins/e2e-dev-harness.js` to map `tool.execute.before` to `phase_guard.py`; keep design/test/review agents non-writing through OpenCode permissions when possible.

## Portability Rules

- Do not depend on Codex chat memory, Codex UI directives, or `agents/openai.yaml` for correctness.
- Keep all durable state in repository files: design docs, handoffs, review requests, invocation JSON, evidence, rework, contracts, memory proposals.
- Prefer relative repo paths in generated artifacts so Claude Code, Codex, Gemini, and CI can resolve the same files.
- Use `SUPERPOWERS_SKILLS_DIR` or `SUPERPOWERS_ROOT` in CI/custom harnesses when plugin cache layout is not predictable.
- If a runtime cannot spawn independent agents, R1/R2/R3 must still be separate isolated reviewer sessions with no inherited developer chat context.

## Review Profiles

Review profiles are plain JSON and portable across runtimes:

```bash
python skills/e2e-dev-harness/scripts/reviewer_gate.py . \
  --review-dir docs/agent-runs/<run>/reviews \
  --review-profile skills/e2e-dev-harness/review-profiles/default.json
```

If `--review-profile` is omitted, the gate discovers project profiles under `.e2e/` or `docs/`. If the target repo is a generated scaffold and the skill lives outside it, the gate also resolves explicit bundled profile names from the skill directory. For profile inheritance, severities, and common review issue guidance, read `review-profiles.md` and `common-review-issues.md`.
