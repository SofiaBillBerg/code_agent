# Archive candidates listed in output/archive_candidates.txt
# Moves files to archive/cleanup_YYYYMMDD_HHMMSS/ preserving relative structure.
param()

$projRoot = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $projRoot

$srcfile = Join-Path $projRoot 'output\archive_candidates.txt'
if (-Not (Test-Path $srcfile))
{
    Write-Host "No file: $srcfile. Create output\archive_candidates.txt with one relative path per line (relative to project root)." -ForegroundColor Yellow
    exit 1
}

$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$destRoot = Join-Path $projRoot "archive\cleanup_$timestamp"
New-Item -ItemType Directory -Path $destRoot -Force | Out-Null

Get-Content $srcfile | ForEach-Object {
    $rel = $_.Trim()
    if ($rel -eq '')
    {
        return
    }
    $src = Join-Path $projRoot $rel
    if (-Not (Test-Path $src))
    {
        Write-Host "Missing: $rel" -ForegroundColor Red
        return
    }
    $dest = Join-Path $destRoot $rel
    $destDir = Split-Path -Parent $dest
    if (-Not (Test-Path $destDir))
    {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    Move-Item -Path $src -Destination $dest -Force
    Write-Host "Moved: $rel -> archive/cleanup_$timestamp/$rel"
}

Write-Host "Archive complete. Review archive/cleanup_$timestamp/ before deleting permanently." -ForegroundColor Green
