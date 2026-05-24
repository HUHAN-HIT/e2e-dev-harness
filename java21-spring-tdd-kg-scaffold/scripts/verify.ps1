param(
    [string]$DesignDoc,
    [string]$Module,
    [ValidateSet("auto", "strict", "optional", "off")]
    [string]$AgentInstructionsMode = "strict",
    [ValidateSet("auto", "discovery", "affected", "all")]
    [string]$AgentInstructionsScope = "auto",
    [string[]]$AgentService,
    [ValidateSet("auto", "strict", "optional", "off")]
    [string]$SuperpowersMode = "auto",
    [ValidateSet("auto", "single", "multi", "off")]
    [string]$AgentMode = "off",
    [ValidateSet("auto", "strict", "optional", "off")]
    [string]$MemoryMode = "auto",
    [ValidateSet("auto", "strict", "optional", "off")]
    [string]$DependencyScanMode = "auto",
    [string]$MavenCommand = "mvn",
    [switch]$SkipDependencyReportWrite,
    [switch]$SkipSpringStaticCheck,
    [switch]$SkipMaven
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($AgentInstructionsMode -ne "off") {
    $AgentInstructionCandidates = @(
        (Join-Path $RepoRoot "skills\e2e-dev-workflow\scripts\agent_instructions.py"),
        (Join-Path $RepoRoot ".agents\skills\e2e-dev-workflow\scripts\agent_instructions.py"),
        (Join-Path $RepoRoot "..\skills\e2e-dev-workflow\scripts\agent_instructions.py")
    )
    $AgentInstructionScript = $AgentInstructionCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $AgentInstructionScript) {
        throw "agent_instructions.py not found."
    }
    $AgentInstructionArgs = @($AgentInstructionScript, $RepoRoot, "--mode", $AgentInstructionsMode, "--scope", $AgentInstructionsScope)
    foreach ($Service in $AgentService) {
        $AgentInstructionArgs += @("--service", $Service)
    }
    python @AgentInstructionArgs
}

$SuperpowersCandidates = @(
    (Join-Path $RepoRoot "skills\e2e-dev-workflow\scripts\superpowers_probe.py"),
    (Join-Path $RepoRoot ".agents\skills\e2e-dev-workflow\scripts\superpowers_probe.py"),
    (Join-Path $RepoRoot "..\skills\e2e-dev-workflow\scripts\superpowers_probe.py")
)
$SuperpowersScript = $SuperpowersCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($SuperpowersScript) {
    python $SuperpowersScript --mode $SuperpowersMode
} elseif ($SuperpowersMode -eq "strict") {
    throw "superpowers_probe.py not found and SuperpowersMode is strict."
}

if ($AgentMode -ne "off") {
    $OrchestrationCandidates = @(
        (Join-Path $RepoRoot "skills\e2e-dev-workflow\scripts\orchestration_plan.py"),
        (Join-Path $RepoRoot ".agents\skills\e2e-dev-workflow\scripts\orchestration_plan.py"),
        (Join-Path $RepoRoot "..\skills\e2e-dev-workflow\scripts\orchestration_plan.py")
    )
    $OrchestrationScript = $OrchestrationCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $OrchestrationScript) {
        throw "orchestration_plan.py not found."
    }
    $OrchestrationArgs = @($OrchestrationScript, $RepoRoot, "--mode", $AgentMode)
    if ($DesignDoc) {
        $OrchestrationArgs += @("--design-doc", $DesignDoc)
    }
    python @OrchestrationArgs
}

if ($MemoryMode -ne "off") {
    $MemoryCandidates = @(
        (Join-Path $RepoRoot "skills\e2e-dev-workflow\scripts\memory_capture.py"),
        (Join-Path $RepoRoot ".agents\skills\e2e-dev-workflow\scripts\memory_capture.py"),
        (Join-Path $RepoRoot "..\skills\e2e-dev-workflow\scripts\memory_capture.py")
    )
    $MemoryScript = $MemoryCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $MemoryScript) {
        throw "memory_capture.py not found."
    }
    python $MemoryScript scan $RepoRoot --mode $MemoryMode
    python $MemoryScript validate $RepoRoot
}

if ($DependencyScanMode -ne "off") {
    $DependencyScanCandidates = @(
        (Join-Path $RepoRoot "skills\e2e-dev-workflow\scripts\cross_service_dependency_scan.py"),
        (Join-Path $RepoRoot ".agents\skills\e2e-dev-workflow\scripts\cross_service_dependency_scan.py"),
        (Join-Path $RepoRoot "..\skills\e2e-dev-workflow\scripts\cross_service_dependency_scan.py")
    )
    $DependencyScanScript = $DependencyScanCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($DependencyScanScript) {
        $DependencyScanArgs = @($DependencyScanScript, $RepoRoot, "--gitnexus-mode", $DependencyScanMode)
        if ($SkipDependencyReportWrite) {
            $DependencyScanArgs += "--no-write"
        }
        python @DependencyScanArgs
    } else {
        Write-Warning "cross_service_dependency_scan.py not found; skipping cross-service dependency scan."
    }
}

if ($DesignDoc) {
    $Candidates = @(
        (Join-Path $RepoRoot "skills\e2e-dev-workflow\scripts\clarification_gate.py"),
        (Join-Path $RepoRoot ".agents\skills\e2e-dev-workflow\scripts\clarification_gate.py"),
        (Join-Path $RepoRoot "..\skills\e2e-dev-workflow\scripts\clarification_gate.py")
    )
    $GateScript = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $GateScript) {
        throw "clarification_gate.py not found. Install or copy the e2e-dev-workflow skill into skills/ or .agents/skills/."
    }
    $DesignPath = Join-Path $RepoRoot $DesignDoc
    python $GateScript $DesignPath
}

if (-not $SkipSpringStaticCheck) {
    $SpringCheckCandidates = @(
        (Join-Path $RepoRoot "skills\e2e-dev-workflow\scripts\spring_static_check.py"),
        (Join-Path $RepoRoot ".agents\skills\e2e-dev-workflow\scripts\spring_static_check.py"),
        (Join-Path $RepoRoot "..\skills\e2e-dev-workflow\scripts\spring_static_check.py")
    )
    $SpringCheckScript = $SpringCheckCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($SpringCheckScript) {
        python $SpringCheckScript $RepoRoot --json
    } else {
        Write-Warning "spring_static_check.py not found; skipping Spring static check."
    }
}

if ($SkipMaven) {
    return
}

Push-Location $RepoRoot
try {
    if ($Module) {
        & $MavenCommand -pl $Module -am test
    } else {
        & $MavenCommand test
    }
} finally {
    Pop-Location
}
