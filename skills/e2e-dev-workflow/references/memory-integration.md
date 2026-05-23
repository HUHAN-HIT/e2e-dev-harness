# Memory Integration

Use memory to preserve verified project knowledge across tasks while keeping agent context small.

## Memory Layers

| Layer | Path | Commit? | Purpose |
| --- | --- | --- | --- |
| Project memory | `memory/*.md` | Usually yes | Durable decisions, boundaries, preferences, and validated facts. |
| Graph memory | `graphify-out/memory/` | Usually no | Graphify query answers saved by `graphify save-result`. |
| Refresh status | `knowledge-graph/knowledge-graph-refresh.json` | No | Per-machine tool availability and latest graph refresh metadata. |

## Files

- `memory/project.md`: stable project summary, stack, conventions, glossary.
- `memory/decisions.md`: user-approved architecture/product decisions.
- `memory/service-boundaries.md`: service ownership, APIs, events, data ownership.
- `memory/graph-findings.md`: verified Graphify/GitNexus findings worth reusing.
- `memory/workflow-preferences.md`: team preferences for testing, planning, tools, and review.

## Capture Rules

- Record only verified facts or user-approved decisions.
- Mark source: `user-approved`, `design`, `graphify`, `gitnexus`, `test`, or `code`.
- Mark confidence: `verified`, `approved`, or `observed`.
- Do not store secrets, tokens, credentials, personal data, or local machine paths.
- Do not store guesses. If useful but uncertain, keep it in the current design doc as an assumption instead.
- Current code and tests override memory when they conflict.
- Fresh knowledge graph output overrides old graph memory.

## Workflow

Before clarification:

```bash
python skills/e2e-dev-workflow/scripts/memory_capture.py scan .
python skills/e2e-dev-workflow/scripts/memory_capture.py validate .
```

For a new repo:

```bash
python skills/e2e-dev-workflow/scripts/memory_capture.py init .
```

After a verified decision or finding:

```bash
python skills/e2e-dev-workflow/scripts/memory_capture.py add . \
  --type decision \
  --source user-approved \
  --confidence approved \
  --text "Spring Framework 6.x is required; do not use Spring Boot."
```

Before dispatching an agent, select the smallest useful memory context:

```bash
python skills/e2e-dev-workflow/scripts/memory_capture.py select . --phase requirements
python skills/e2e-dev-workflow/scripts/memory_capture.py select . --phase code --service services/<service>
```

After Graphify answers a useful question, also consider:

```bash
graphify save-result --question "..." --answer "..." --type query --nodes NodeA NodeB
```

## Proposed Updates

Agents do not write durable memory directly. They propose entries in `docs/agent-runs/<run>/proposed-memory-updates.md`:

```markdown
### M-1

- Type: decision
- Source: user-approved
- Confidence: approved
- Status: accepted
- Text: Spring Framework 6.x is required; do not use Spring Boot.
```

Valid statuses are:

- `accepted`, `approved`, `verified`: promote to `memory/*.md`.
- `rejected`, `deferred`, `skipped`: handled but not promoted.

Promote handled entries after verification or user approval:

```bash
python skills/e2e-dev-workflow/scripts/memory_capture.py promote . --from-file docs/agent-runs/<run>/proposed-memory-updates.md
```

Run the completion gate with `--memory-updates` to block unhandled entries before reporting done.

## Multi-Agent Use

Each agent should load only the memory files relevant to its phase:

- Requirements Clarifier: `project.md`, `workflow-preferences.md`, `decisions.md`
- Use Case Designer: `project.md`, `service-boundaries.md`, `graph-findings.md`
- Test Case Developer: `workflow-preferences.md`, `decisions.md`, `graph-findings.md`
- Code Developer: `service-boundaries.md`, `graph-findings.md`, `decisions.md`

Agents write proposed memory updates in their handoff artifact first. The main agent appends to `memory/*.md` only after verification or user approval.

## Validation Rules

`memory_capture.py validate .` blocks missing required memory files, duplicate entry text, unresolved TODO/TBD markers, local machine paths, and likely secrets or credentials. Treat a validation failure as a memory hygiene issue, not as a reason to ignore memory entirely; fix or remove the bad entry, then rerun validation.
