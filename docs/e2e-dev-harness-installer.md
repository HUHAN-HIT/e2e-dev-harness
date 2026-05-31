# E2E Dev Harness Installer

This guide explains how to use the Node bootstrap installer:

```powershell
node tools\install-e2e-dev-harness.mjs
```

The installer copies the `e2e-dev-harness` skill into agent runtime skill
directories, optionally installs the editable Python CLI, optionally installs
GitNexus/Graphify, and can invoke the bundled runtime hook installer.

## What It Installs

By default, the installer targets Codex and copies:

```text
skills/e2e-dev-harness/
```

to:

```text
%USERPROFILE%\.codex\skills\e2e-dev-harness
```

Supported targets:

| Target | Destination |
| --- | --- |
| `codex` | `%USERPROFILE%\.codex\skills\e2e-dev-harness` |
| `claude` | `%USERPROFILE%\.claude\skills\e2e-dev-harness` |
| `agents` | `%USERPROFILE%\.agents\skills\e2e-dev-harness` |
| `all` | all three destinations above |

The installer skips transient Python artifacts such as `__pycache__`,
`.pytest_cache`, and `*.egg-info` directories when copying the skill.

## Safety Model

The installer is a dry run by default. It prints the plan but does not copy
files or run install commands unless `--yes` is supplied.

Dry run:

```powershell
node tools\install-e2e-dev-harness.mjs --target codex
```

Execute:

```powershell
node tools\install-e2e-dev-harness.mjs --target codex --yes
```

When an existing target skill directory already exists, the installer first
copies it to:

```text
<install-root>\.e2e-dev-harness-backups\<timestamp>\<target>\e2e-dev-harness
```

Then it replaces the target skill directory.

Every successful executed install writes:

```text
<install-root>\.e2e-dev-harness-install.json
```

This manifest records the repo, source skill directory, targets, installed
paths, and environment checks.

## Recommended First Run

Preview the Codex install and emit machine-readable output:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target codex `
  --install-root $env:USERPROFILE `
  --skip-python-cli `
  --json
```

If the plan looks correct, execute the copy:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target codex `
  --install-root $env:USERPROFILE `
  --skip-python-cli `
  --yes
```

Use `--skip-python-cli` when you only want to install the skill files and do
not want the installer to run `pip`.

## Full Local Developer Install

From this repository root:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target codex `
  --install-root $env:USERPROFILE `
  --yes
```

This performs two actions:

1. Copies the skill to the selected runtime skill directory.
2. Runs:

```powershell
python -m pip install -e .[dev,ast]
```

Use `--no-dev` to omit the `dev` extra, and `--no-ast` to omit the
tree-sitter Java parser extra:

```powershell
node tools\install-e2e-dev-harness.mjs --target codex --no-dev --yes
node tools\install-e2e-dev-harness.mjs --target codex --no-ast --yes
```

## Install For Multiple Agent Runtimes

Install to Codex, Claude, and `.agents` skill directories:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target all `
  --install-root $env:USERPROFILE `
  --skip-python-cli `
  --yes
```

Install only for Claude:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target claude `
  --install-root $env:USERPROFILE `
  --skip-python-cli `
  --yes
```

## External Dependencies

The installer always checks for:

- `python`
- `npm`
- `gitnexus`
- `graphify`
- `mvn` / `mvn.cmd`
- required Superpowers skills

It does not install GitNexus or Graphify unless `--install-external` is passed.

Plan external installs:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target codex `
  --install-external `
  --json
```

Execute missing external installs:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target codex `
  --install-external `
  --yes
```

GitNexus install command when missing:

```powershell
npm install -g gitnexus
```

Graphify install priority when missing:

1. `uv tool install --upgrade graphifyy`
2. `pipx install graphifyy`
3. `python -m pip install --user graphifyy`

Superpowers is not treated as a normal npm or pip package. The installer probes
for the required Superpowers skills through the bundled `superpowers_probe.py`.
Use `--strict-superpowers` if a missing Superpowers setup should block install.

Check a custom Superpowers skills directory:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target codex `
  --superpowers-dir C:\path\to\superpowers\skills `
  --strict-superpowers `
  --json
```

## Runtime Hooks

For Claude Code hook installation, run:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target claude `
  --with-hooks `
  --runtime claude `
  --yes
```

This invokes:

```powershell
python skills/e2e-dev-harness/scripts/install_hooks.py . --runtime claude --json
```

The hook installer writes or validates runtime hook configuration using the
bundled `phase_guard.py` and `harness_stop_guard.py` scripts.

For Codex or Gemini runtimes, use the template files under:

```text
skills/e2e-dev-harness/hooks/
```

Runtime support for blocking pre-action/pre-tool hooks depends on the host.
When a runtime cannot enforce hooks, use the portable `pre-code` command before
code edits and `guard` before completion.

## Check-Only Mode

Run environment checks without planning copy or install actions:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --check-only `
  --json
```

This is useful in CI or onboarding scripts before deciding whether to run a
real install.

## Verify After Install

After a real install, verify the Python CLI and environment:

```powershell
e2e-dev-harness --version
e2e-dev-harness doctor . --json
```

If the editable CLI was skipped, run the scripts directly from this repository:

```powershell
python skills\e2e-dev-harness\scripts\e2e_dev_harness.py doctor . --json
python skills\e2e-dev-harness\scripts\superpowers_probe.py --json
python skills\e2e-dev-harness\scripts\kg_refresh.py . --mode both
```

## Common Recipes

Install only the skill for Codex:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target codex `
  --skip-python-cli `
  --yes
```

Install skill and Python CLI for all runtimes:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target all `
  --yes
```

Install skill, Python CLI, and missing GitNexus/Graphify:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target codex `
  --install-external `
  --yes
```

Preview all actions as JSON:

```powershell
node tools\install-e2e-dev-harness.mjs `
  --target all `
  --install-external `
  --with-hooks `
  --json
```

## Troubleshooting

If the installer reports `Source skill is missing SKILL.md`, run it from this
repository root or provide `--repo` and `--source-skill-dir` explicitly:

```powershell
node C:\path\to\repo\tools\install-e2e-dev-harness.mjs `
  --repo C:\path\to\repo `
  --source-skill-dir C:\path\to\repo\skills\e2e-dev-harness `
  --target codex `
  --yes
```

If Python CLI install fails, rerun without `--yes` to inspect the plan, then run
the pip command manually:

```powershell
python -m pip install -e .[dev,ast]
```

If GitNexus is missing and external install is not desired, leave
`--install-external` off. Critical or audited harness runs can still proceed
only with explicit user-approved GitNexus degradation evidence.

If Graphify is missing, the installer can install the CLI, but the initial
Graphify extraction may still require project-specific LLM/API configuration.

## Argument Reference

| Option | Meaning |
| --- | --- |
| `--target codex\|claude\|agents\|all` | Select install destination. Default: `codex`. |
| `--install-root <path>` | Root containing `.codex`, `.claude`, or `.agents`. Default: user home. |
| `--repo <path>` | Repository root used for Python CLI and hook commands. Default: current directory. |
| `--source-skill-dir <path>` | Source skill directory. Default: `<repo>\skills\e2e-dev-harness`. |
| `--yes` | Execute planned writes and commands. Without it, the installer is dry-run only. |
| `--json` | Print JSON plan/result. |
| `--skip-python-cli` | Do not run `python -m pip install -e .[dev,ast]`. |
| `--no-dev` | Omit the `dev` extra from editable Python install. |
| `--no-ast` | Omit the `ast` extra from editable Python install. |
| `--install-external` | Install missing GitNexus and Graphify. |
| `--skip-external` | Check external tools but never plan external install actions. |
| `--with-hooks` | Invoke the bundled hook installer. |
| `--runtime claude` | Runtime passed to `install_hooks.py`. Currently used with `--with-hooks`. |
| `--strict-superpowers` | Block when required Superpowers skills are missing. |
| `--superpowers-dir <path>` | Check a specific Superpowers skills directory. |
| `--check-only` | Run checks only; do not plan copy or install actions. |
| `--help` | Print command help. |
