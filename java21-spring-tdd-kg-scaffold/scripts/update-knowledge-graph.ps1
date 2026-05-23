param(
    [ValidateSet("auto", "gitnexus", "graphify", "both")]
    [string]$Mode = "auto",
    [string]$GitNexusCommand,
    [string]$GraphifyCommand,
    [switch]$Execute,
    [switch]$UseSuggestedCommands
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StatusFile = Join-Path $RepoRoot "knowledge-graph\knowledge-graph-refresh.json"
$Candidates = @(
    (Join-Path $RepoRoot "skills\java-spring-tdd-kg\scripts\kg_refresh.py"),
    (Join-Path $RepoRoot ".agents\skills\java-spring-tdd-kg\scripts\kg_refresh.py"),
    (Join-Path $RepoRoot "..\skills\java-spring-tdd-kg\scripts\kg_refresh.py")
)

$Script = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Script) {
    throw "kg_refresh.py not found. Install or copy the java-spring-tdd-kg skill into skills/ or .agents/skills/."
}

$Args = @($Script, $RepoRoot, "--mode", $Mode, "--status-file", $StatusFile)
if ($GitNexusCommand) {
    $Args += @("--gitnexus-command", $GitNexusCommand)
}
if ($GraphifyCommand) {
    $Args += @("--graphify-command", $GraphifyCommand)
}
if ($Execute) {
    $Args += "--execute"
}
if ($UseSuggestedCommands) {
    $Args += "--use-suggested-commands"
}

python @Args
