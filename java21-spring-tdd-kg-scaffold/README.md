# Java 21 Spring 6 TDD KG Scaffold

This scaffold uses Spring Framework 6.x directly, not Spring Boot. It supports both a single Spring MVC service and a Maven monorepo with multiple services. Start with `services/sample-service`; add more services under `services/*` and register each module in the root `pom.xml`.

Prerequisites: Java 21 and Maven 3.9+ available on `PATH`.

## Workflow

1. Write or update a design note under `docs/design/`.
2. Load root and affected service `AGENT.md` instructions.
3. Probe the Superpowers adapter. When available, use `superpowers:brainstorming` for clarification.
4. Scan project memory and load only relevant facts.
5. Refresh the knowledge graph before coding.
6. Run the clarification gate. Implementation starts only when open questions are `None`.
7. Use `superpowers:test-driven-development` and write the first failing test.
8. Implement the smallest change to pass.
9. Refactor while green.
10. Capture verified memory updates.
11. Run the affected Maven module tests, then broaden verification.

## Commands

```powershell
python ..\skills\java-spring-tdd-kg\scripts\agent_instructions.py . --mode strict --include-content
python ..\skills\java-spring-tdd-kg\scripts\superpowers_probe.py --mode auto
python ..\skills\java-spring-tdd-kg\scripts\superpowers_probe.py --mode strict --phase implementation
python ..\skills\java-spring-tdd-kg\scripts\memory_capture.py scan .
.\scripts\update-knowledge-graph.ps1
.\scripts\verify.ps1 -DesignDoc docs\design\feature-design-template.md -AgentInstructionsMode strict -Module services/sample-service
```

When Graphify is installed and `graphify-out/graph.json` already exists, refresh it with:

```powershell
.\scripts\update-knowledge-graph.ps1 -Mode graphify -Execute -UseSuggestedCommands
```

For initial Graphify extraction, pass the exact command explicitly:

```powershell
.\scripts\update-knowledge-graph.ps1 -Mode graphify -Execute -GraphifyCommand "graphify extract ."
```

For design-only checks before Maven is available:

```powershell
.\scripts\verify.ps1 -DesignDoc docs\design\feature-design-template.md -AgentInstructionsMode strict -SuperpowersMode strict -SkipMaven
```

For multi-agent planning:

```powershell
python ..\skills\java-spring-tdd-kg\scripts\orchestration_plan.py . --mode auto --design-doc docs\design\feature-design-template.md
```

For first-time memory setup or appending verified decisions:

```powershell
python ..\skills\java-spring-tdd-kg\scripts\memory_capture.py init .
python ..\skills\java-spring-tdd-kg\scripts\memory_capture.py add . --type decision --source user-approved --confidence approved --text "Use Spring Framework 6.x directly rather than Spring Boot."
```

For Linux/macOS shells, call the same Python scripts directly and run:

```bash
mvn -pl services/sample-service -am test
```

## Service Layout

```text
services/<service>/
  src/main/java/...      Spring 6 configuration and production code
  src/test/java/...      JUnit tests written before implementation
  pom.xml               Service module build, packaged as a WAR
```

Keep domain logic in plain Java when possible, use Spring at the edges, and let tests describe the use cases.
