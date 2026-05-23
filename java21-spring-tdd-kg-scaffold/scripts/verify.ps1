param(
    [string]$DesignDoc,
    [string]$Module,
    [ValidateSet("auto", "strict", "optional", "off")]
    [string]$AgentInstructionsMode = "strict",
    [ValidateSet("auto", "strict", "optional", "off")]
    [string]$SuperpowersMode = "auto",
    [ValidateSet("auto", "single", "multi", "off")]
    [string]$AgentMode = "off",
    [ValidateSet("auto", "strict", "optional", "off")]
    [string]$MemoryMode = "auto",
    [switch]$SkipMaven
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($AgentInstructionsMode -ne "off") {
    $AgentInstructionCandidates = @(
        (Join-Path $RepoRoot "skills\java-spring-tdd-kg\scripts\agent_instructions.py"),
        (Join-Path $RepoRoot ".agents\skills\java-spring-tdd-kg\scripts\agent_instructions.py"),
        (Join-Path $RepoRoot "..\skills\java-spring-tdd-kg\scripts\agent_instructions.py")
    )
    $AgentInstructionScript = $AgentInstructionCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $AgentInstructionScript) {
        throw "agent_instructions.py not found."
    }
    python $AgentInstructionScript $RepoRoot --mode $AgentInstructionsMode
}

$SuperpowersCandidates = @(
    (Join-Path $RepoRoot "skills\java-spring-tdd-kg\scripts\superpowers_probe.py"),
    (Join-Path $RepoRoot ".agents\skills\java-spring-tdd-kg\scripts\superpowers_probe.py"),
    (Join-Path $RepoRoot "..\skills\java-spring-tdd-kg\scripts\superpowers_probe.py")
)
$SuperpowersScript = $SuperpowersCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($SuperpowersScript) {
    python $SuperpowersScript --mode $SuperpowersMode
} elseif ($SuperpowersMode -eq "strict") {
    throw "superpowers_probe.py not found and SuperpowersMode is strict."
}

if ($AgentMode -ne "off") {
    $OrchestrationCandidates = @(
        (Join-Path $RepoRoot "skills\java-spring-tdd-kg\scripts\orchestration_plan.py"),
        (Join-Path $RepoRoot ".agents\skills\java-spring-tdd-kg\scripts\orchestration_plan.py"),
        (Join-Path $RepoRoot "..\skills\java-spring-tdd-kg\scripts\orchestration_plan.py")
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
        (Join-Path $RepoRoot "skills\java-spring-tdd-kg\scripts\memory_capture.py"),
        (Join-Path $RepoRoot ".agents\skills\java-spring-tdd-kg\scripts\memory_capture.py"),
        (Join-Path $RepoRoot "..\skills\java-spring-tdd-kg\scripts\memory_capture.py")
    )
    $MemoryScript = $MemoryCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $MemoryScript) {
        throw "memory_capture.py not found."
    }
    python $MemoryScript scan $RepoRoot --mode $MemoryMode
}

if ($DesignDoc) {
    $Candidates = @(
        (Join-Path $RepoRoot "skills\java-spring-tdd-kg\scripts\clarification_gate.py"),
        (Join-Path $RepoRoot ".agents\skills\java-spring-tdd-kg\scripts\clarification_gate.py"),
        (Join-Path $RepoRoot "..\skills\java-spring-tdd-kg\scripts\clarification_gate.py")
    )
    $GateScript = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $GateScript) {
        throw "clarification_gate.py not found. Install or copy the java-spring-tdd-kg skill into skills/ or .agents/skills/."
    }
    $DesignPath = Join-Path $RepoRoot $DesignDoc
    python $GateScript $DesignPath
}

if ($SkipMaven) {
    return
}

if ($Module) {
    mvn -pl $Module -am test
} else {
    mvn test
}
