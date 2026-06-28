param(
    [int]$Port = 8501,
    [string]$Address = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return
    }

    foreach ($RawLine in Get-Content $Path) {
        $Line = $RawLine.Trim()
        if (-not $Line -or $Line.StartsWith("#") -or -not $Line.Contains("=")) {
            continue
        }

        $Parts = $Line -split "=", 2
        $Name = $Parts[0]
        $Value = $Parts[1]
        $Name = $Name.Trim().TrimStart([char]0xFEFF)
        $Value = $Value.Trim().Trim('"').Trim("'")
        if ($Name -and -not [Environment]::GetEnvironmentVariable($Name, "Process")) {
            Set-Item -Path "Env:$Name" -Value $Value
        }
    }
}

Import-DotEnv (Join-Path $ProjectRoot ".env")

if (-not $env:TASKRADAR_USE_OPENCODE) {
    $env:TASKRADAR_USE_OPENCODE = "1"
}
if (-not $env:TASKRADAR_REQUIRE_OPENCODE) {
    $env:TASKRADAR_REQUIRE_OPENCODE = "1"
}
if (-not $env:TASKRADAR_MODE) {
    $env:TASKRADAR_MODE = "demo"
}

$OpencodeCommand = if ($env:TASKRADAR_OPENCODE_COMMAND) { $env:TASKRADAR_OPENCODE_COMMAND } else { "opencode" }
if (-not (Get-Command $OpencodeCommand -ErrorAction SilentlyContinue)) {
    Write-Warning "opencode command was not found. Check TASKRADAR_OPENCODE_COMMAND or PATH before sharing the service."
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment is missing. Run .\scripts\setup_server.ps1 first."
}

& $Python -m streamlit run app.py --server.address $Address --server.port $Port --server.headless true
