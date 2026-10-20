$ErrorActionPreference = "Stop"

$DemoDir = Split-Path $PSScriptRoot -Parent
Set-Location $DemoDir

$ConfigReader = Join-Path $PSScriptRoot "runtime_config.py"
$VenvPython = Join-Path $DemoDir ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $Python = "python"
} else {
    Write-Host "[ERR] Python is required to load config\runtime.yaml. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

$RuntimeConfigJson = & $Python $ConfigReader --json
if ($LASTEXITCODE -ne 0) {
    exit 1
}
try {
    $RuntimeConfig = $RuntimeConfigJson | ConvertFrom-Json -ErrorAction Stop
} catch {
    Write-Host "[ERR] Could not parse runtime configuration emitted by $ConfigReader." -ForegroundColor Red
    exit 1
}

$BonsaiModel = [string]$RuntimeConfig.BONSAI_MODEL
$BonsaiFamily = [string]$RuntimeConfig.BONSAI_FAMILY
if ($BonsaiModel -eq "all" -or $BonsaiFamily -eq "all") {
    Write-Host "[ERR] BONSAI_FAMILY='all' / BONSAI_MODEL='all' is only valid for setup/download." -ForegroundColor Red
    exit 1
}

$HostAddress = [string]$RuntimeConfig.BONSAI_LLAMA_HOST
$Port = [int]$RuntimeConfig.BONSAI_LLAMA_PORT

try {
    $null = Invoke-WebRequest -Uri "http://localhost:$Port/health" -TimeoutSec 2
    Write-Host "[WARN] Health endpoint responded on port $Port; llama-server may already be running." -ForegroundColor Yellow
    exit 1
} catch {}

if ($BonsaiFamily -eq "ternary") {
    $ModelDir = Join-Path $DemoDir "models\ternary-gguf\$BonsaiModel"

    $FamilyDisplay = "Ternary-Bonsai"
} else {
    $ModelDir = Join-Path $DemoDir "models\gguf\$BonsaiModel"
    $FamilyDisplay = "Bonsai"
}

$Display = "$FamilyDisplay-$BonsaiModel"
$Model = Get-ChildItem -Path $ModelDir -Filter *.gguf -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $Model) {
    Write-Host "[ERR] GGUF model not found for $Display in $ModelDir" -ForegroundColor Red

    Write-Host "      Run .\setup.ps1 first." -ForegroundColor Yellow
    exit 1
}

$BinCandidates = @(
    "bin\cuda\llama-server.exe",
    "bin\hip\llama-server.exe",
    "bin\vulkan\llama-server.exe",
    "bin\cpu\llama-server.exe",
    "llama.cpp\build\bin\Release\llama-server.exe",
    "llama.cpp\build\bin\llama-server.exe"
)
$BinRel = $BinCandidates | Where-Object { Test-Path (Join-Path $DemoDir $_) } | Select-Object -First 1
if (-not $BinRel) {
    Write-Host "[ERR] llama-server.exe not found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

$Bin = Join-Path $DemoDir $BinRel
$BinDir = Split-Path $Bin -Parent
$env:Path = "$BinDir;$env:Path"

$Ngl = if ($env:BONSAI_NGL) {
    $env:BONSAI_NGL
} elseif ($BinRel -like "bin\cpu\*") {
    "0"
} else {
    "99"
}

Write-Host ""
Write-Host "=== llama.cpp server (GGUF) ==="
Write-Host "  Model:   $($Model.Name)"
Write-Host "  Binary:  $Bin"
Write-Host "  Context: auto-fit (-c 0)"
Write-Host ""
Write-Host "  Open http://localhost:$Port in your browser to chat."
Write-Host "  API:  http://localhost:$Port/v1/chat/completions"
Write-Host "  Press Ctrl+C to stop."
Write-Host ""

$ChatTemplateKwargs = if ($PSVersionTable.PSEdition -eq 'Desktop') { '{\"enable_thinking\": false}' } else { '{"enable_thinking": false}' }

$ServerArgs = @(
    "-m", $Model.FullName,
    "--host", $HostAddress,
    "--port", "$Port",
    "-ngl", $Ngl,
    "-c", "0",
    "--temp", "0.5",
    "--top-p", "0.85",
    "--top-k", "20",
    "--min-p", "0",
    "--reasoning-budget", "0",
    "--reasoning-format", "none",
    "--chat-template-kwargs", $ChatTemplateKwargs
)

& $Bin @ServerArgs @args
exit $LASTEXITCODE
