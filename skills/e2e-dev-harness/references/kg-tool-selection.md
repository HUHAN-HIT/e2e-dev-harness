# Knowledge Graph Tool Selection

Use this matrix before each implementation.

| Repo/task shape | Default | Add-on | Reason |
| --- | --- | --- | --- |
| Java/Spring 6/Maven code change in one service | GitNexus | None | Code structure, call paths, and impact analysis matter most. |
| Multi-service Java monorepo | GitNexus | Deterministic scanner, then Graphify when docs or diagrams drive the change | GitNexus follows code; the scanner extracts HTTP/DMQ seeds; Graphify helps visualize broader project context. |
| Cross-service HTTP or DMQ dependency analysis | Deterministic scanner plus GitNexus | Graphify for docs/ADR/architecture semantics only | Scan URLs, routes, topics, tags, groups, constants, producers, and consumers first; GitNexus verifies symbol context and impact. |
| Design document, PDF, architecture diagram, screenshot, or mixed media input | Graphify | GitNexus when code will change | Graphify is better for multimodal/project-document understanding. |
| Ambiguous service ownership or cross-service contract change | Both | None | Compare doc-level architecture against code-level dependencies. |
| Tool unavailable | Ask for degradation approval | Repo inspection after approval | Use Maven modules, `rg`, dependency trees, and targeted tests only as documented compensating evidence. |

## Refresh Protocol

1. Run the dry-run helper:

   ```bash
   python skills/e2e-dev-harness/scripts/kg_refresh.py .
   ```

2. Inspect the recommended tools and detected service/module list.
3. Run installed repo-specific graph commands. Prefer commands already documented in the repo.
4. Save or note the graph refresh location in the design note before implementation.
5. If Graphify is installed, prefer a fast local refresh when a graph already exists; use full extraction only when the graph is missing or stale.

## GitNexus And Search Augmentation

If GitNexus hooks augment `grep`, `rg`, or similar search commands locally, do not add repetitive skill instructions that tell agents to invoke GitNexus around every text search. Let search augmentation help exploration quietly.

For workflow evidence, still run explicit GitNexus commands and record their output path or summary. Hidden search augmentation is not auditable enough for planning, implementation, or completion gates.

Use GitNexus for requirements or diff impact analysis when scope is uncertain:

When more than one repository is indexed, pass the current project root through
`--repo <repo-root>` for `query`, `context`, `impact`, and `detect-changes`.
Use an absolute repo root for automation; `.` is acceptable only when the
command runs from the project root.

```bash
gitnexus detect-changes --repo <repo-root> --scope unstaged
gitnexus detect-changes --repo <repo-root> --scope staged
gitnexus detect-changes --repo <repo-root> --scope compare --base-ref main
gitnexus context "<ClassName|methodName|ClassName.methodName>" --repo <repo-root>
gitnexus impact "<changed-symbol-or-file>" --repo <repo-root> --include-tests
```

Use `context` only for code symbols such as classes, functions, and methods. It is not a directory scanner. Do not run `gitnexus context services/foo --repo <repo-root>`.
Use `impact` or `detect-changes` for affected-scope analysis, and constrain the seeds to the microservices declared in the global design or service design slices.

Use `detect-changes` to map a concrete diff to indexed symbols and execution flows. Use `impact` when the requirement names a symbol, path, API, route, topic, or contract seed before code has changed.

## Cross-Service Dependency Protocol

Use GitNexus-first evidence for hidden service dependencies:

The bundled deterministic Java scanner extracts HTTP/DMQ seeds with a tree-sitter
Java AST when `tree_sitter` and `tree_sitter_java` are installed
(`java_parser.backend: tree-sitter`, `ast_parser_active: true`); otherwise it
falls back per file to regex (`java_parser.backend: regex-fallback`,
`ast_parser_active: false`) and says so in `java_parser.warning`. The AST path
removes regex false positives such as annotations inside comments or string
literals. Either way the scanner only produces seeds: GitNexus remains the
authoritative code-graph source for high-risk Java call-path decisions, and
ambiguous scanner edges become clarification questions, not completion evidence.
If a project policy requires AST-backed deterministic scanning, run the scanner
with `--require-tree-sitter-ast` so the gate blocks unless the AST parser is
active.

1. Run the deterministic scanner:

   ```bash
   python skills/e2e-dev-harness/scripts/cross_service_dependency_scan.py . --gitnexus-mode auto --json
   ```

2. Inspect `knowledge-graph/cross-service-dependencies.json` and `.md`.
3. Treat unresolved URL, topic, tag, group, or service mappings as clarification questions.
4. Use GitNexus evidence from the report (`analyze`, symbol-scoped `context`, symbol/file-scoped `impact`) as code-level evidence for implementation planning and completion.
5. Use Graphify only to add document/ADR/architecture context. `INFERRED` or `AMBIGUOUS` Graphify relationships are not hard completion evidence.

For high-risk cross-service work, use `--gitnexus-mode strict`. If GitNexus is unavailable, the report remains useful as a seed list, but it should be treated as evidence-insufficient until reviewed with `rg`, Maven modules, and targeted code reads.

## GitNexus Degradation

GitNexus is a primary evidence source for critical/audited completion. Do not silently treat a deterministic scan, `rg`, or manual code reads as equivalent when GitNexus MCP/CLI is unavailable or blocked by a DB owner.

If GitNexus cannot produce verified evidence, pause and ask the user whether to degrade for this run. If approved, write an evidence file such as `docs/agent-runs/<run>/evidence/gitnexus-degradation.md`:

```markdown
# GitNexus Degradation
Approval: user-approved
Reason: GitNexus MCP/CLI was unavailable or could not access the index.
Fallback Evidence: deterministic scanner report, Maven module graph, targeted `rg` reads, contract review, and affected-service tests.
```

Then pass it to completion:

```bash
python skills/e2e-dev-harness/scripts/e2e_dev_harness.py gate . \
  --phase completion \
  --require-gitnexus-evidence auto \
  --gitnexus-degradation docs/agent-runs/<run>/evidence/gitnexus-degradation.md
```

Use `--require-gitnexus-evidence strict` when project policy requires GitNexus evidence even outside auto-classified critical/audited work. Use `off` only for explicitly approved non-code or non-Java runs.

## Command Discovery

Do not invent flags. Inspect installed help first:

```bash
gitnexus --help
graphify --help
```

If the repo defines graph commands in Maven plugins, package scripts, Makefiles, CI, or docs, use those instead of a guessed command.

For current GitNexus CLI versions, the local command shape is:

```bash
gitnexus analyze .
gitnexus status
gitnexus query "<concept>" --repo <repo-root>
gitnexus context "<ClassName|methodName|ClassName.methodName>" --repo <repo-root>
gitnexus impact "<changed-symbol-or-file>" --repo <repo-root>
gitnexus detect-changes --repo <repo-root> --scope unstaged
```

Use `gitnexus analyze .` as the default refresh command when GitNexus is installed and the repo has no more specific script.

For current Graphify CLI versions, the local command shape is:

```bash
graphify update .
graphify extract .
graphify query "<question>" --graph graphify-out/graph.json
graphify affected "<symbol-or-file>" --graph graphify-out/graph.json
graphify tree --graph graphify-out/graph.json
```

Use `graphify update .` when `graphify-out/graph.json` already exists. Use `graphify extract .` for initial extraction, but expect semantic extraction to require an LLM backend/API key unless the repo workflow documents a no-LLM mode. For CI or quick local checks, prefer explicit repo commands such as `graphify extract . --no-cluster` only after confirming they fit the project.

## Conflict Handling

When Graphify and GitNexus disagree, use the code graph and tests for implementation truth, and use the document graph to identify stale documentation or missing ADR updates.
