param(
    [switch]$NoInstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    if ($NoInstall) { throw "Python environment is missing. Run without -NoInstall." }
    python -m venv .venv
}

& $venvPython -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    if ($NoInstall) { throw "Console Python dependencies are missing. Run without -NoInstall." }
    & $venvPython -m pip install -r server\requirements.txt
}

if (-not (Test-Path "node_modules")) {
    if ($NoInstall) { throw "Console frontend dependencies are missing. Run without -NoInstall." }
    pnpm install
}

$api = Start-Process -FilePath $venvPython -ArgumentList "-m", "server" -PassThru -WindowStyle Hidden
try {
    Start-Sleep -Milliseconds 800
    pnpm --filter @workspace/marm-console dev
}
finally {
    if (-not $api.HasExited) {
        Stop-Process -Id $api.Id -Force
    }
}
