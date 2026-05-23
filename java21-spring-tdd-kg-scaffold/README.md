# Java 21 Spring 6 TDD KG Scaffold

This scaffold uses Spring Framework 6.x directly, not Spring Boot. It supports both a single Spring MVC service and a Maven monorepo with multiple services. Start with `services/sample-service`; add more services under `services/*` and register each module in the root `pom.xml`.

Prerequisites: Java 21 and Maven 3.9+ available on `PATH`.

## Workflow

1. Write or update a design note under `docs/design/`.
2. Run the unified prepare command and load root/scoped service `AGENT.md` instructions before clarification.
3. Probe the Superpowers adapter. When available, use `superpowers:brainstorming` for clarification.
4. Scan project memory and load only relevant facts.
5. Refresh the knowledge graph before coding.
6. Run the clarification gate. Implementation starts only when open questions are `None` or explicitly resolved.
7. For complex work, write an ExecPlan and use file-based agent handoffs.
8. For multi-service work, keep one implementation plan and one code-agent handoff per affected service.
9. Use `superpowers:test-driven-development` and write the first failing test.
10. Implement the smallest change to pass.
11. Refactor while green.
12. Capture unit-test evidence, coverage matrix, business review, and verified memory updates.
13. Run the affected Maven module tests, then broaden verification.

## Commands

```powershell
python ..\skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py prepare . --design-doc docs\design\feature-design-template.md --agent-mode strict --agent-scope discovery --service-scope discovery --include-agent-content
python ..\skills\e2e-dev-workflow\scripts\agent_instructions.py . --mode strict --scope discovery --include-content
python ..\skills\e2e-dev-workflow\scripts\agent_instructions.py . --mode strict --scope affected --service services/sample-service --include-content
python ..\skills\e2e-dev-workflow\scripts\superpowers_probe.py --mode auto
python ..\skills\e2e-dev-workflow\scripts\superpowers_probe.py --mode strict --phase implementation
python ..\skills\e2e-dev-workflow\scripts\memory_capture.py scan .
python ..\skills\e2e-dev-workflow\scripts\memory_capture.py validate .
.\scripts\update-knowledge-graph.ps1
.\scripts\verify.ps1 -DesignDoc docs\design\feature-design-template.md -AgentInstructionsMode strict -AgentInstructionsScope affected -AgentService services/sample-service -Module services/sample-service
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
python ..\skills\e2e-dev-workflow\scripts\orchestration_plan.py . --mode auto --service-scope discovery --design-doc docs\design\feature-design-template.md
python ..\skills\e2e-dev-workflow\scripts\orchestration_plan.py . --mode auto --service-scope affected --service services/sample-service --design-doc docs\design\feature-design-template.md
python ..\skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py plan . --design-doc docs\design\feature-design-template.md --service-scope affected --service services/sample-service --create-archive
```

Generated agent process files go under `docs/agent-runs/<date-feature>/`. Keep durable design docs and templates under `docs/design/`.

For hook-like gates:

```powershell
python ..\skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py gate . --phase planning --design-doc docs\design\feature-design-template.md
python ..\skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py gate . --phase implementation --design-doc docs\design\feature-design-template.md --red-test-evidence docs\design\feature-red-test.txt
python ..\skills\e2e-dev-workflow\scripts\e2e_dev_workflow.py gate . --phase completion --design-doc docs\design\feature-design-template.md --red-test-evidence docs\agent-runs\<run>\evidence\red-test.txt --coverage-matrix docs\agent-runs\<run>\evidence\coverage-matrix.md --unit-test-evidence docs\agent-runs\<run>\evidence\green-test.txt --business-review docs\agent-runs\<run>\evidence\business-review.md --memory-updates docs\agent-runs\<run>\proposed-memory-updates.md
```

For multi-service changes, generated service-specific files live under:

```text
docs/agent-runs/<date-feature>/service-plans/<service>/
  implementation-plan.md
  code-agent.md
  unit-test-evidence.txt
  coverage-matrix.md
  business-review.md
```

For first-time memory setup or appending verified decisions:

```powershell
python ..\skills\e2e-dev-workflow\scripts\memory_capture.py init .
python ..\skills\e2e-dev-workflow\scripts\memory_capture.py add . --type decision --source user-approved --confidence approved --text "Use Spring Framework 6.x directly rather than Spring Boot."
python ..\skills\e2e-dev-workflow\scripts\memory_capture.py select . --phase code --service services/sample-service
python ..\skills\e2e-dev-workflow\scripts\memory_capture.py promote . --from-file docs\agent-runs\<run>\proposed-memory-updates.md
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
