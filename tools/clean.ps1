[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$Apply,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'pyproject.toml') -PathType Leaf)) {
    throw "Invalid AE2Claude project root: $ProjectRoot"
}

$relativeCandidates = @(
    '__pycache__',
    '.ruff_cache',
    '.pytest_cache',
    'ae2claude.egg-info',
    'dist',
    'tests\__pycache__',
    'ae2claude_mcp\__pycache__',
    'extensions\pin-clicker\python\__pycache__',
    'extensions\pin-clicker\logs',
    'src\PyShiftAE\Win\x64'
)

$rows = @()
foreach ($relative in $relativeCandidates) {
    $path = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $relative))
    if (-not $path.StartsWith($ProjectRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup target escaped project root: $path"
    }
    if (-not (Test-Path -LiteralPath $path)) {
        continue
    }
    $item = Get-Item -LiteralPath $path -Force
    if ($item.LinkType) {
        throw "Cleanup refuses links: $path"
    }
    $files = @(Get-ChildItem -LiteralPath $path -File -Recurse -Force -ErrorAction SilentlyContinue)
    $bytes = [long](($files | Measure-Object -Property Length -Sum).Sum)
    $removed = $false
    if ($Apply -and $PSCmdlet.ShouldProcess($path, 'Remove generated residue')) {
        Remove-Item -LiteralPath $path -Recurse -Force
        $removed = -not (Test-Path -LiteralPath $path)
    }
    $rows += [pscustomobject]@{
        relative = $relative.Replace('\', '/')
        path = $path
        files = $files.Count
        bytes = $bytes
        action = if ($Apply) { if ($removed) { 'removed' } else { 'skipped' } } else { 'report-only' }
    }
}

[pscustomobject]@{
    ok = $true
    mode = if ($Apply) { 'apply' } else { 'report-only' }
    protected = @('.venv', 'build\Release', 'extensions\pin-clicker\node_modules', 'vendor\after-effects-sdk')
    candidates = $rows
    totalBytes = [long](($rows | Measure-Object -Property bytes -Sum).Sum)
} | ConvertTo-Json -Depth 5
