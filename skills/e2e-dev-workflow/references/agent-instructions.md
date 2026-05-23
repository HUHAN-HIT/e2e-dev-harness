# AGENT Instruction Loading

Load repository instructions in phases. Keep root project rules ahead of generic skill defaults, but avoid loading every service instruction file before affected services are known.

## Load Order

1. Root `AGENTS.override.md`, `AGENT.override.md`, `AGENT.md`, or `AGENTS.md`.
2. In `discovery` scope, list discovered service AGENT files but do not load their contents.
3. In `affected` scope, load AGENT files whose directory scope contains a path that may be touched.
4. In `affected` scope, load affected service `AGENT.md` or `AGENTS.md` under `services/<service>/`.
5. In `all` scope, load every discovered service instruction file.

Precedence is: current user instruction > more deeply nested AGENT file > broader AGENT file > this skill.

## Scope Strategy

- `auto`: default. Uses `discovery` when no `--path` or `--service` is supplied, and `affected` when either is supplied.
- `discovery`: pre-clarification mode. Load root instructions and report service instruction locations for later.
- `affected`: post-clarification/design mode. Load root, scoped path AGENT files, and only affected service AGENT files.
- `all`: legacy/full mode. Use only when the task genuinely needs whole-repo service rules.

## Modes

- `strict`: block if the root instruction file is missing, if a requested service name cannot be matched, or if a selected affected/all service instruction file is missing. In discovery scope, missing discovered service AGENT files are reported but do not block.
- `auto`: discover and report files, but do not block on missing files.
- `optional`: same practical behavior as auto, useful when retrofitting old repos.
- `off`: disable the gate only when the user or repo policy explicitly asks for it.

## Discovery Rules

The helper discovers service directories from:

- `services/*` children that contain `pom.xml` or `src/`.
- Maven root `pom.xml` modules that contain both `pom.xml` and `src/`.
- `--path` values by walking from the repo root to each path's parent directory and loading scoped AGENT files in order.

Generated and tool directories such as `.git`, `target`, `build`, `node_modules`, and `graphify-out` are ignored.

## Commands

Load instruction content for a normal clarification session:

```bash
python skills/e2e-dev-workflow/scripts/agent_instructions.py . --mode strict --scope discovery --include-content
```

After clarification identifies affected services, load only relevant instructions:

```bash
python skills/e2e-dev-workflow/scripts/agent_instructions.py . --mode strict --scope affected --include-content --service services/<service>
python skills/e2e-dev-workflow/scripts/agent_instructions.py . --mode strict --scope affected --include-content --path services/<service>/src/main/java/...
```

Load all service instructions only when explicitly needed:

```bash
python skills/e2e-dev-workflow/scripts/agent_instructions.py . --mode strict --scope all --include-content
```

Machine-readable scan:

```bash
python skills/e2e-dev-workflow/scripts/agent_instructions.py . --mode strict --scope discovery --json
```

For very large repositories, discovery JSON reports `discovered_service_count` and caps `discovered_service_agent_files` to a small sample by default. Use that inventory to choose candidate services, then rerun in affected scope. Do not open files from `discovered_service_agent_files` until the design narrows the service list.
