# Wrapper invoked by Windows Task Scheduler each morning.
# Activates the project venv (if present) and runs the agent.

$ErrorActionPreference = "Stop"

# Project root = parent of the scripts/ folder this file lives in.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Make the src/ layout importable.
$env:PYTHONPATH = Join-Path $root "src"

# Prefer the project venv's python if it exists, else fall back to PATH python.
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $python = $venvPython
} else {
    $python = "python"
}

& $python -m personal_agent.main
exit $LASTEXITCODE
