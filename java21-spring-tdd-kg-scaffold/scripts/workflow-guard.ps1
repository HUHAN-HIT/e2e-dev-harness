param(
    [Parameter(Mandatory = $true)]
    [string]$VerifyStatus,
    [switch]$Strict,
    [switch]$RequireCompletion,
    [string]$ApprovalFile
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Candidates = @(
    (Join-Path $RepoRoot "skills\e2e-dev-harness\scripts\workflow_guard.py"),
    (Join-Path $RepoRoot ".agents\skills\e2e-dev-harness\scripts\workflow_guard.py"),
    (Join-Path $RepoRoot "..\skills\e2e-dev-harness\scripts\workflow_guard.py")
)

$Script = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Script) {
    throw "workflow_guard.py not found. Install or copy the e2e-dev-harness skill into skills/ or .agents/skills/."
}

$Args = @($Script, $RepoRoot, "--verify-status", $VerifyStatus)
if ($Strict) {
    $Args += "--strict"
}
if ($RequireCompletion) {
    $Args += "--require-completion"
}
if ($ApprovalFile) {
    $Args += @("--approval-file", $ApprovalFile)
}

python @Args
exit $LASTEXITCODE
