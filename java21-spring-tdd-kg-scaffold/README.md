# Java 21 Spring 6 TDD KG Scaffold

This scaffold uses Spring Framework 6.x directly, not Spring Boot. It supports both a single Spring MVC service and a Maven monorepo with multiple services. Start with `services/sample-service`; add more services under `services/*` and register each module in the root `pom.xml`.

Prerequisites: Java 21 and Maven 3.9+ available on `PATH`.

## Workflow

1. Write or update a design note under `docs/design/`.
2. Run the unified prepare command and load root/scoped service `AGENT.md` instructions before clarification.
3. Probe the Superpowers adapter. When available, use `superpowers:brainstorming` for clarification.
4. Scan project memory and load only relevant facts.
5. Refresh the knowledge graph and run the GitNexus-first cross-service dependency scan before coding.
6. Run the clarification gate. Implementation starts only when open questions are `None` or explicitly resolved.
7. For complex work, write an ExecPlan and use file-based agent handoffs.
8. For multi-service or multi-module work, keep one implementation plan, implementation manifest, and code-agent handoff per affected service/module.
9. Run independent R1 design review before planning proceeds.
10. Use `superpowers:test-driven-development` and write the first failing test.
11. Run independent R2 test review before production code.
12. Implement the smallest change to pass and refactor while green.
13. Run independent R3 implementation review before completion.
14. Capture implementation manifest, unit-test command JSON, semantic review reports, coverage matrix, business review, Spring static check result, and verified memory updates.
15. Run the affected Maven module tests, then broaden verification.

## Commands

```powershell
python ..\skills\e2e-dev-harness\scripts\e2e_dev_workflow.py prepare . --design-doc docs\design\feature-design-template.md --agent-mode strict --agent-scope discovery --service-scope discovery --include-agent-content
python ..\skills\e2e-dev-harness\scripts\agent_instructions.py . --mode strict --scope discovery --include-content
python ..\skills\e2e-dev-harness\scripts\agent_instructions.py . --mode strict --scope affected --service services/sample-service --include-content
python ..\skills\e2e-dev-harness\scripts\superpowers_probe.py --mode auto
python ..\skills\e2e-dev-harness\scripts\superpowers_probe.py --mode strict --phase implementation
python ..\skills\e2e-dev-harness\scripts\memory_capture.py scan .
python ..\skills\e2e-dev-harness\scripts\memory_capture.py validate .
python ..\skills\e2e-dev-harness\scripts\cross_service_dependency_scan.py . --gitnexus-mode auto --json
python ..\skills\e2e-dev-harness\scripts\spring_static_check.py . --json
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

To skip the cross-service dependency scan for a single local run:

```powershell
.\scripts\verify.ps1 -DesignDoc docs\design\feature-design-template.md -DependencyScanMode off -SkipMaven
```

For multi-agent planning:

```powershell
python ..\skills\e2e-dev-harness\scripts\orchestration_plan.py . --mode auto --service-scope discovery --design-doc docs\design\feature-design-template.md
python ..\skills\e2e-dev-harness\scripts\orchestration_plan.py . --mode auto --design-doc docs\design\feature-design-template.md
python ..\skills\e2e-dev-harness\scripts\orchestration_plan.py . --mode auto --service-scope affected --service services/sample-service --design-doc docs\design\feature-design-template.md
python ..\skills\e2e-dev-harness\scripts\e2e_dev_workflow.py plan . --design-doc docs\design\feature-design-template.md --create-archive
python ..\skills\e2e-dev-harness\scripts\e2e_dev_workflow.py plan . --design-doc docs\design\feature-design-template.md --service-scope affected --service services/sample-service --create-archive
```

Generated agent process files go under `docs/agent-runs/<date-feature>/`. Keep durable design docs and templates under `docs/design/`. When the design lists affected services/modules that match discovered candidates, auto planning creates one service plan, one code-agent handoff, and one implementation manifest per service/module; explicit `--service` is only needed to override or disambiguate.

For hook-like gates:

```powershell
python ..\skills\e2e-dev-harness\scripts\e2e_dev_workflow.py gate . --phase planning --design-doc docs\design\feature-design-template.md
python ..\skills\e2e-dev-harness\scripts\e2e_dev_workflow.py gate . --phase implementation --design-doc docs\design\feature-design-template.md --red-test-evidence docs\design\feature-red-test.txt
python ..\skills\e2e-dev-harness\scripts\e2e_dev_workflow.py gate . --phase completion --design-doc docs\design\feature-design-template.md --red-test-evidence docs\agent-runs\<run>\evidence\red-test.txt --implementation-manifest docs\agent-runs\<run>\evidence\implementation-manifest.md --coverage-matrix docs\agent-runs\<run>\evidence\coverage-matrix.md --unit-test-evidence docs\agent-runs\<run>\evidence\green-test.txt --business-review docs\agent-runs\<run>\evidence\business-review.md --dependency-report docs\agent-runs\<run>\evidence\cross-service-dependencies.json --contract-dir docs\agent-runs\<run>\contracts --memory-updates docs\agent-runs\<run>\proposed-memory-updates.md --rework-dir docs\agent-runs\<run>\rework --review-dir docs\agent-runs\<run>\reviews --handoff-dir docs\agent-runs\<run>\handoffs
```

For strict hook/CI usage, save a verify status and run the guard:

```powershell
python ..\skills\e2e-dev-harness\scripts\e2e_dev_workflow.py verify . --strict-workflow --run-gate --phase completion --design-doc docs\design\feature-design-template.md --red-test-evidence docs\agent-runs\<run>\evidence\red-test.txt --implementation-manifest docs\agent-runs\<run>\evidence\implementation-manifest.md --coverage-matrix docs\agent-runs\<run>\evidence\coverage-matrix.md --unit-test-evidence docs\agent-runs\<run>\evidence\green-test.txt --business-review docs\agent-runs\<run>\evidence\business-review.md --dependency-report docs\agent-runs\<run>\evidence\cross-service-dependencies.json --contract-dir docs\agent-runs\<run>\contracts --memory-updates docs\agent-runs\<run>\proposed-memory-updates.md --rework-dir docs\agent-runs\<run>\rework --review-dir docs\agent-runs\<run>\reviews --handoff-dir docs\agent-runs\<run>\handoffs --status-file docs\agent-runs\<run>\evidence\verify.json
.\scripts\workflow-guard.ps1 -VerifyStatus docs\agent-runs\<run>\evidence\verify.json -Strict -RequireCompletion
```

Strict guard blocks skipped Maven, disabled dependency scan, missing completion gate, missing independent R1/R2/R3 semantic review evidence, unresolved dependency questions, and skipped Spring static check during completion unless an approval file contains `Approval: user-approved`.

For cross-service HTTP/DMQ work, unresolved dependency questions in `cross-service-dependencies.json` must be clarified before implementation or completion.

Semantic review requests live in `docs/agent-runs/<run>/review-requests/` and service-local `service-plans/<service>/review-requests/`. Reports live in `docs/agent-runs/<run>/reviews/` as `R1-design-review.md`, `R2-test-review.md`, and `R3-implementation-review.md`; multi-service R2/R3 reviews must also live under `service-plans/<service>/reviews/` for every affected service. Each request must assign concrete `Developer Agent` and `Reviewer Agent` ids before dispatch. Each report must include `Phase`, `Reviewer`, `Review Request`, `Developer Agent`, `Reviewer Agent`, `Reviewer Session`, `Reviewer Invocation`, `Request Hash`, `Independence`, `Context Boundary`, `No Code Changes`, `Scope`, `Inputs Reviewed`, `Findings`, `Required Rework`, and `Status`. The reviewer must be an independent agent/session, the report must be the exact `Output` declared by its review request, the invocation JSON must declare `fork_context: false` and request-only/no-inherited context, and the report `Request Hash` must match the current request file SHA-256. Before a downstream agent consumes a non-review handoff, run `handoff_gate.py` or pass `--handoff-dir`; ready handoffs need concrete agent ids, input/output hashes, downstream consumers, closed open questions, no partial files, and a matching ready marker. For cross-service HTTP/DMQ dependencies, add `docs/agent-runs/<run>/contracts/<contract-id>.md` and run `contract_gate.py` or pass `--contract-dir`; producer/consumer ACKs and contract tests are required before parallel service implementation.

For multi-module work, `implementation-manifest.md` is the hard completeness checklist. It must list every required artifact with module, source, tests, status, and evidence; missing required files or modules block completion. Use explicit design sections such as `Required Artifacts`, `Affected Classes`, or `[artifact] ClassName` markers for must-implement files/classes so reference notes do not become false requirements.

If review finds missed behavior, create `docs/agent-runs/<run>/rework/rework-NNN.md` or `docs/agent-runs/<run>/service-plans/<service>/rework-NNN.md`, route it back to the required phase, and close it as `verified` or explicitly approved `deferred` before reporting done.

If Maven is installed but not available on the current `PATH`, pass it explicitly:

```powershell
.\scripts\verify.ps1 -DesignDoc docs\design\feature-design-template.md -Module services/sample-service -MavenCommand "D:\SOFTWARE\apache-maven-3.9.16\bin\mvn.cmd"
```

`green-test.txt` and each service `unit-test-evidence.txt` must contain JSON like:

```json
{
  "command": "mvn -pl services/sample-service -am test",
  "exit_code": 0,
  "stdout_tail": "BUILD SUCCESS",
  "stderr_tail": ""
}
```

For multi-service changes, generated service-specific files live under:

```text
docs/agent-runs/<date-feature>/service-plans/<service>/
  implementation-plan.md
  code-agent.md
  review-requests/
    R2-test-review-request.md
    R3-implementation-review-request.md
  reviews/
    R2-test-review.md
    R3-implementation-review.md
  implementation-manifest.md
  unit-test-evidence.txt
  coverage-matrix.md
  business-review.md
  rework-NNN.md
```

For first-time memory setup or appending verified decisions:

```powershell
python ..\skills\e2e-dev-harness\scripts\memory_capture.py init .
python ..\skills\e2e-dev-harness\scripts\memory_capture.py add . --type decision --source user-approved --confidence approved --tag decision --tag service/sample-service --link services/sample-service --link AC-1 --text "Use Spring Framework 6.x directly rather than Spring Boot."
python ..\skills\e2e-dev-harness\scripts\memory_capture.py select . --phase code --service services/sample-service
python ..\skills\e2e-dev-harness\scripts\memory_capture.py promote . --from-file docs\agent-runs\<run>\proposed-memory-updates.md
```

Memory entries may include controlled Obsidian metadata:

```markdown
- Tags: #decision #service/sample-service #phase/code
- Links: [[services/sample-service]] [[AC-1]]
```

These fields make service-scoped selection and graph navigation cleaner; they still must describe verified facts in `Text`.

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
