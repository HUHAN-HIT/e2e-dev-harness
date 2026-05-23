# Knowledge Graph Tool Selection

Use this matrix before each implementation.

| Repo/task shape | Default | Add-on | Reason |
| --- | --- | --- | --- |
| Java/Spring 6/Maven code change in one service | GitNexus | None | Code structure, call paths, and impact analysis matter most. |
| Multi-service Java monorepo | GitNexus | Graphify when docs or diagrams drive the change | GitNexus follows code; Graphify helps visualize broader project context. |
| Design document, PDF, architecture diagram, screenshot, or mixed media input | Graphify | GitNexus when code will change | Graphify is better for multimodal/project-document understanding. |
| Ambiguous service ownership or cross-service contract change | Both | None | Compare doc-level architecture against code-level dependencies. |
| Tool unavailable | Fallback to repo inspection | None | Use Maven modules, `rg`, dependency trees, and targeted tests. |

## Refresh Protocol

1. Run the dry-run helper:

   ```bash
   python skills/java-spring-tdd-kg/scripts/kg_refresh.py .
   ```

2. Inspect the recommended tools and detected service/module list.
3. Run installed repo-specific graph commands. Prefer commands already documented in the repo.
4. Save or note the graph refresh location in the design note before implementation.
5. If Graphify is installed, prefer a fast local refresh when a graph already exists; use full extraction only when the graph is missing or stale.

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
gitnexus query "<concept>"
gitnexus impact "<symbol-or-path>"
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
