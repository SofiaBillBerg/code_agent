# Generate output/archive_candidates.txt by filtering output/cleanup_report.csv
# This script writes candidate relative paths (one per line) for archival.
# It excludes entrypoints and reachable scripts; includes unreferenced_python, unreferenced_quarto_md_html, duplicate_same_basename.

$projRoot = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $projRoot

$report = Join-Path $projRoot 'output\cleanup_report.csv'
$out = Join-Path $projRoot 'output\archive_candidates.txt'

if (-Not (Test-Path $report))
{
    Write-Host "Missing report: $report" -ForegroundColor Red
    exit 1
}

$lines = Get-Content $report -Encoding UTF8 | Select-Object -Skip 1
$candidates = @()
foreach ($line in $lines)
{
    # CSV: path,size,sha1,category,notes
    $parts = $line -split ',', 5
    if ($parts.Length -lt 4)
    {
        continue
    }
    $path = $parts[0].Trim('"')
    $category = $parts[3].Trim('"')
    if ($category -in @('unreferenced_python', 'unreferenced_quarto_md_html', 'duplicate_same_basename'))
    {
        # extra safety: don't include _site or archive directories
        if ($path -like '_site/*' -or $path -like 'archive/*' -or $path -like 'output/*')
        {
            continue
        }
        $candidates += $path
    }
}

$candidates | Sort-Object | Get-Unique | Out-File -FilePath $out -Encoding UTF8
Write-Host "Wrote $( $candidates.Count ) candidate entries to $out" -ForegroundColor Green
