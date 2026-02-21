<#
.SYNOPSIS
    Remove ALL caches for the Data Compliance Agent project.

.DESCRIPTION
    Clears:
      - Python __pycache__ dirs (project only, skips .venv / node_modules)
      - .pytest_cache
      - Next.js .next build cache
      - Application logs  (logs/)
      - Temp artefacts    (temp/)
      - Redis document cache (FLUSHDB on db 0)
      - Qdrant vector-DB local storage (qdrant_db/)

    Run from the project root:
        .\scripts\clean_cache.ps1          # default - keeps qdrant and redis
        .\scripts\clean_cache.ps1 -All     # also wipes qdrant + redis

.PARAMETER All
    Also purge Qdrant vector DB and flush Redis cache.
#>
param(
    [switch]$All
)

$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent

Write-Host ""
Write-Host "[CLEAN] Data Compliance Agent - Cache Cleanup" -ForegroundColor Cyan
Write-Host ("=" * 50)

# 1. Python __pycache__
$pycaches = Get-ChildItem -Path $root -Recurse -Directory -Filter "__pycache__" |
    Where-Object { $_.FullName -notmatch '[\\/]\.venv[\\/]|[\\/]node_modules[\\/]' }

if ($pycaches -and $pycaches.Count -gt 0) {
    foreach ($d in $pycaches) {
        Remove-Item $d.FullName -Recurse -Force
    }
    Write-Host "  [OK] Removed $($pycaches.Count) __pycache__ directories" -ForegroundColor Green
}
else {
    Write-Host "  [--] No __pycache__ directories found" -ForegroundColor DarkGray
}

# 2. .pytest_cache
$pytestCache = Join-Path $root ".pytest_cache"
if (Test-Path $pytestCache) {
    Remove-Item $pytestCache -Recurse -Force
    Write-Host "  [OK] Removed .pytest_cache" -ForegroundColor Green
}
else {
    Write-Host "  [--] .pytest_cache not found" -ForegroundColor DarkGray
}

# 3. Next.js .next build cache
$nextCache = Join-Path $root "agent-chat-ui" | Join-Path -ChildPath ".next"
if (Test-Path $nextCache) {
    Remove-Item $nextCache -Recurse -Force
    Write-Host "  [OK] Removed agent-chat-ui\.next" -ForegroundColor Green
}
else {
    Write-Host "  [--] agent-chat-ui\.next not found" -ForegroundColor DarkGray
}

# 4. Logs
$logsDir = Join-Path $root "logs"
if (Test-Path $logsDir) {
    $logFiles = Get-ChildItem $logsDir -File -ErrorAction SilentlyContinue
    if ($logFiles) {
        $removed = 0
        foreach ($f in $logFiles) {
            try { Remove-Item $f.FullName -Force -ErrorAction Stop; $removed++ }
            catch { Write-Host "  [!!] Skipped locked file: $($f.Name)" -ForegroundColor DarkYellow }
        }
        Write-Host "  [OK] Cleared logs/ ($removed files removed)" -ForegroundColor Green
    }
}
else {
    Write-Host "  [--] logs/ not found" -ForegroundColor DarkGray
}

# 5. Temp artefacts
$tempDir = Join-Path $root "temp"
if (Test-Path $tempDir) {
    $tempFiles = Get-ChildItem $tempDir -File -ErrorAction SilentlyContinue
    if ($tempFiles) {
        foreach ($f in $tempFiles) { Remove-Item $f.FullName -Force }
    }
    Write-Host "  [OK] Cleared temp/" -ForegroundColor Green
}
else {
    Write-Host "  [--] temp/ not found" -ForegroundColor DarkGray
}

# 6. Stray .pyc files at project root
$rootPyc = Get-ChildItem -Path $root -Filter "*.pyc" -File -ErrorAction SilentlyContinue
if ($rootPyc -and $rootPyc.Count -gt 0) {
    foreach ($f in $rootPyc) { Remove-Item $f.FullName -Force }
    Write-Host "  [OK] Removed $($rootPyc.Count) stray .pyc files" -ForegroundColor Green
}

# 7. Qdrant vector DB (only with -All)
if ($All) {
    $qdrantDir = Join-Path $root "qdrant_db"
    if (Test-Path $qdrantDir) {
        Remove-Item $qdrantDir -Recurse -Force
        Write-Host "  [OK] Removed qdrant_db/" -ForegroundColor Yellow
    }

    # 8. Redis FLUSHDB (only with -All)
    try {
        $redisResult = & redis-cli FLUSHDB 2>&1
        if ($redisResult -match "OK") {
            Write-Host "  [OK] Redis FLUSHDB done" -ForegroundColor Yellow
        }
        else {
            Write-Host "  [!!] Redis FLUSHDB returned: $redisResult" -ForegroundColor DarkYellow
        }
    }
    catch {
        Write-Host "  [--] Redis not reachable (skipped)" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "[DONE] Cache cleanup complete." -ForegroundColor Cyan
Write-Host ""
