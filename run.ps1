<#
One-step PowerShell runner for the project.
Creates a virtual env in .venv (if missing), installs dependencies, and runs main.py.
#>
param()

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root '.venv'

if (-not (Test-Path $venv)) {
    Write-Host "Creating virtual environment in $venv..."
    python -m venv $venv
}

$py = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host "Virtual environment python not found; trying system python..."
    $py = "python"
}

Write-Host "Upgrading pip, setuptools, wheel..."
& $py -m pip install --upgrade pip setuptools wheel

Write-Host "Installing requirements from requirements.txt..."
& $py -m pip install -r (Join-Path $root 'requirements.txt')

Write-Host "Launching game (main.py)..."
& $py (Join-Path $root 'main.py')

Write-Host "Done. Close the game window or press Ctrl+C to exit." 
