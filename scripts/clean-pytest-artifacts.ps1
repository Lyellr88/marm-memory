param(
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$searchRoots = @(
    $root,
    (Join-Path $root "marm-mcp-server")
)

$targets = foreach ($searchRoot in $searchRoots) {
    if (-not (Test-Path -LiteralPath $searchRoot)) {
        continue
    }

    Get-ChildItem -LiteralPath $searchRoot -Force -Directory -Filter ".pytest_cache" -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $searchRoot -Force -Directory -Filter ".pytest_tmp*" -ErrorAction SilentlyContinue
}

$targets = $targets | Sort-Object FullName -Unique

if (-not $targets) {
    Write-Host "No pytest artifacts found."
    exit 0
}

foreach ($target in $targets) {
    if ($WhatIf) {
        Write-Host "Would remove: $($target.FullName)"
        continue
    }

    try {
        Remove-Item -LiteralPath $target.FullName -Recurse -Force
        Write-Host "Removed: $($target.FullName)"
    }
    catch {
        Write-Warning "Could not remove $($target.FullName): $($_.Exception.Message)"
    }
}
