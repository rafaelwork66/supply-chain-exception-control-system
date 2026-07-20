param(
    [string]$PythonCommand = "py -3.12"
)

$ErrorActionPreference = "Stop"

Write-Host "Checking Python launchers..."

try {
    py -3.12 --version
} catch {
    Write-Host "py -3.12 is not available. Install Python 3.12 or enable the Python launcher." -ForegroundColor Yellow
}

try {
    python --version
} catch {
    Write-Host "python is not available on PATH. This is acceptable if py -3.12 works." -ForegroundColor Yellow
}

Write-Host "Checking Docker..."
try {
    docker --version
    docker compose version
} catch {
    Write-Host "Docker is not available on PATH. Install Docker Desktop before running PostgreSQL locally." -ForegroundColor Yellow
}

Write-Host "Checking project tooling with $PythonCommand..."
try {
    Invoke-Expression "$PythonCommand -m pip --version"
} catch {
    Write-Host "Could not run pip with $PythonCommand. Check your Python 3.12 installation." -ForegroundColor Yellow
}

Write-Host "Environment verification finished."
