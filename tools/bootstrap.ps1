[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$SdkSource,
    [switch]$RepairLinks,
    [switch]$InstallPinDependencies
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-NormalizedPath {
    param([Parameter(Mandatory)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Assert-ProjectRoot {
    param([Parameter(Mandatory)][string]$Path)
    $required = @('pyproject.toml', 'src\PyShiftAE\Win\PyShiftAE.vcxproj', 'extensions\pin-clicker\package.json')
    foreach ($relative in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $Path $relative))) {
            throw "Invalid AE2Claude project root; missing $relative in $Path"
        }
    }
}

$ProjectRoot = Get-NormalizedPath $ProjectRoot
Assert-ProjectRoot $ProjectRoot

$vendorRoot = Join-Path $ProjectRoot 'vendor\after-effects-sdk'
$sdkNames = @('Headers', 'Resources', 'Util')

if ($SdkSource) {
    $SdkSource = Get-NormalizedPath $SdkSource
    foreach ($name in $sdkNames) {
        $source = Join-Path $SdkSource $name
        $destination = Join-Path $vendorRoot $name
        if (-not (Test-Path -LiteralPath $source -PathType Container)) {
            throw "SDK source is missing $name`: $source"
        }
        if (Test-Path -LiteralPath $destination) {
            if (-not $RepairLinks) {
                throw "SDK destination already exists: $destination. Use -RepairLinks only after reviewing it."
            }
            if ($PSCmdlet.ShouldProcess($destination, 'Replace local SDK copy')) {
                Remove-Item -LiteralPath $destination -Recurse -Force
            }
        }
        if ($PSCmdlet.ShouldProcess($destination, "Copy SDK $name")) {
            New-Item -ItemType Directory -Path $vendorRoot -Force | Out-Null
            Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
        }
    }
}

$linkResults = @()
foreach ($name in $sdkNames) {
    $target = Join-Path $vendorRoot $name
    $link = Join-Path $ProjectRoot $name
    if (-not (Test-Path -LiteralPath $target -PathType Container)) {
        throw "Local Adobe SDK directory is missing: $target. Supply -SdkSource first."
    }

    $needsCreate = $true
    if (Test-Path -LiteralPath $link) {
        $item = Get-Item -LiteralPath $link -Force
        $actualTarget = if ($item.Target) { Get-NormalizedPath ([string]$item.Target) } else { '' }
        $expectedTarget = Get-NormalizedPath $target
        if ($item.LinkType -eq 'Junction' -and $actualTarget -eq $expectedTarget) {
            $needsCreate = $false
        } elseif (-not $RepairLinks) {
            throw "Unexpected SDK link at $link. Use -RepairLinks only after reviewing it."
        } elseif ($PSCmdlet.ShouldProcess($link, 'Replace SDK link')) {
            Remove-Item -LiteralPath $link -Force
        }
    }

    if ($needsCreate -and $PSCmdlet.ShouldProcess($link, "Create junction to $target")) {
        New-Item -ItemType Junction -Path $link -Target $target | Out-Null
    }

    $verified = Get-Item -LiteralPath $link -Force
    $linkResults += [pscustomobject]@{
        name = $name
        link = $link
        type = $verified.LinkType
        target = @($verified.Target)
    }
}

$pinRoot = Join-Path $ProjectRoot 'extensions\pin-clicker'
$pinDependencyState = 'not-requested'
if ($InstallPinDependencies) {
    $npm = Get-Command npm.cmd -ErrorAction Stop
    $lock = Join-Path $pinRoot 'package-lock.json'
    if (-not (Test-Path -LiteralPath $lock -PathType Leaf)) {
        throw 'PinClicker package-lock.json is missing; refusing a non-reproducible install.'
    }
    if ($PSCmdlet.ShouldProcess($pinRoot, 'Install locked PinClicker dependencies')) {
        & $npm.Source ci --omit=dev --no-audit --no-fund --prefix $pinRoot
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci failed with exit code $LASTEXITCODE"
        }
        $pinDependencyState = 'installed'
    }
}

[pscustomobject]@{
    ok = $true
    projectRoot = $ProjectRoot
    sdkRoot = $vendorRoot
    links = $linkResults
    pinDependencies = $pinDependencyState
} | ConvertTo-Json -Depth 5
