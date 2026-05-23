# AGENT Instruction Loading

Load repository instructions before requirement clarification. This keeps project and microservice conventions ahead of the skill's generic defaults.

## Load Order

1. Root `AGENT.md` or `AGENTS.md`.
2. Affected service `AGENT.md` or `AGENTS.md` under `services/<service>/`.
3. If affected services are unknown, load all discovered service instruction files before asking clarification questions.

Precedence is: current user instruction > loaded `AGENT.md` / `AGENTS.md` > this skill.

## Modes

- `strict`: block if the root instruction file or any discovered service instruction file is missing. Use for formal project work.
- `auto`: discover and report files, but do not block on missing files.
- `optional`: same practical behavior as auto, useful when retrofitting old repos.
- `off`: disable the gate only when the user or repo policy explicitly asks for it.

## Discovery Rules

The helper discovers service directories from:

- `services/*` children that contain `pom.xml` or `src/`.
- Maven root `pom.xml` modules that contain both `pom.xml` and `src/`.

Generated and tool directories such as `.git`, `target`, `build`, `node_modules`, and `graphify-out` are ignored.

## Commands

Load instruction content for a normal clarification session:

```bash
python skills/java-spring-tdd-kg/scripts/agent_instructions.py . --mode strict --include-content
```

Machine-readable scan:

```bash
python skills/java-spring-tdd-kg/scripts/agent_instructions.py . --mode strict --json
```

For very large repositories, use the JSON `load_order` to open only the root and affected service files.
