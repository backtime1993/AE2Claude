[CmdletBinding()]
param(
    [ValidateSet('Verify', 'Apply')]
    [string]$Mode = 'Verify',
    [string[]]$Target,
    [switch]$AllSupported,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$sourceAex = Join-Path $ProjectRoot 'build\Release\AE2Claude.aex'
if (-not (Test-Path -LiteralPath $sourceAex -PathType Leaf)) {
    throw "Release build is missing: $sourceAex"
}

$supportedNames = @(
    'Adobe After Effects (Beta)',
    'Adobe After Effects 2025',
    'Adobe After Effects 2024',
    'Adobe After Effects 2023'
)

function Resolve-Targets {
    $selected = @()
    if ($Target) {
        $selected = @($Target)
    } elseif ($AllSupported) {
        foreach ($name in $supportedNames) {
            $support = Join-Path (Join-Path 'C:\Program Files\Adobe' $name) 'Support Files'
            $plugin = Join-Path $support 'Plug-ins\AE2Claude.aex'
            $python = Join-Path $support 'python312.dll'
            if ((Test-Path -LiteralPath $plugin -PathType Leaf) -or (Test-Path -LiteralPath $python -PathType Leaf)) {
                $selected += $name
            }
        }
    } else {
        $running = @(Get-Process -Name 'AfterFX*' -ErrorAction SilentlyContinue)
        foreach ($process in $running) {
            if ($process.Path) {
                $installName = Split-Path -Leaf (Split-Path -Parent (Split-Path -Parent $process.Path))
                if ($supportedNames -contains $installName) {
                    $selected += $installName
                }
            }
        }
        if ($selected.Count -eq 0) {
            $selected = @('Adobe After Effects (Beta)')
        }
    }

    $resolved = @()
    foreach ($name in @($selected | Select-Object -Unique)) {
        if ($supportedNames -notcontains $name) {
            throw "Unsupported or ambiguous target: $name"
        }
        $support = Join-Path (Join-Path 'C:\Program Files\Adobe' $name) 'Support Files'
        if (Test-Path -LiteralPath $support -PathType Container) {
            $resolved += [pscustomobject]@{ name = $name; support = $support }
        } elseif ($Target) {
            throw "Requested After Effects installation was not found: $support"
        }
    }
    if ($resolved.Count -eq 0) {
        throw 'No supported After Effects installation was found.'
    }
    return $resolved
}

function Get-FileDifference {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Destination -PathType Leaf)) {
        return [pscustomobject]@{ label = $Label; source = $Source; destination = $Destination; reason = 'missing' }
    }
    $sourceInfo = Get-Item -LiteralPath $Source
    $destinationInfo = Get-Item -LiteralPath $Destination
    if ($sourceInfo.Length -ne $destinationInfo.Length) {
        return [pscustomobject]@{ label = $Label; source = $Source; destination = $Destination; reason = 'size' }
    }
    $sourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash
    $destinationHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
    if ($sourceHash -ne $destinationHash) {
        return [pscustomobject]@{ label = $Label; source = $Source; destination = $Destination; reason = 'hash' }
    }
    return $null
}

function Get-DeploymentMap {
    param([Parameter(Mandatory)][string]$PluginDirectory)
    $map = @(
        [pscustomobject]@{ source = $sourceAex; destination = (Join-Path $PluginDirectory 'AE2Claude.aex'); label = 'AE2Claude.aex' },
        [pscustomobject]@{ source = (Join-Path $ProjectRoot 'ae2claude_server.py'); destination = (Join-Path $PluginDirectory 'ae2claude_server.py'); label = 'ae2claude_server.py' },
        [pscustomobject]@{ source = (Join-Path $ProjectRoot 'ae_bridge.py'); destination = (Join-Path $PluginDirectory 'ae_bridge.py'); label = 'ae_bridge.py' },
        [pscustomobject]@{ source = (Join-Path $ProjectRoot 'ae_native_protocol.py'); destination = (Join-Path $PluginDirectory 'ae_native_protocol.py'); label = 'ae_native_protocol.py' },
        [pscustomobject]@{ source = (Join-Path $ProjectRoot 'ae2claude'); destination = (Join-Path $PluginDirectory 'ae2claude'); label = 'ae2claude' }
    )
    foreach ($directoryName in @('scripts', 'presets')) {
        $sourceDirectory = Join-Path $ProjectRoot $directoryName
        foreach ($file in Get-ChildItem -LiteralPath $sourceDirectory -File -Recurse) {
            $relative = $file.FullName.Substring($sourceDirectory.Length).TrimStart('\')
            $map += [pscustomobject]@{
                source = $file.FullName
                destination = Join-Path (Join-Path $PluginDirectory $directoryName) $relative
                label = "$directoryName/$($relative.Replace('\', '/'))"
            }
        }
    }
    return $map
}

function Test-TargetRunning {
    param([Parameter(Mandatory)][string]$SupportPath)
    foreach ($process in @(Get-Process -Name 'AfterFX*' -ErrorAction SilentlyContinue)) {
        if ($process.Path -and $process.Path.StartsWith($SupportPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

$targets = Resolve-Targets
$results = @()
$hasMismatch = $false
$hasPending = $false

foreach ($targetInfo in $targets) {
    $pluginDirectory = Join-Path $targetInfo.support 'Plug-ins'
    $map = Get-DeploymentMap $pluginDirectory
    $differences = @()
    foreach ($entry in $map) {
        $difference = Get-FileDifference -Source $entry.source -Destination $entry.destination -Label $entry.label
        if ($null -ne $difference) {
            $differences += $difference
        }
    }

    $running = Test-TargetRunning $targetInfo.support
    $state = if ($differences.Count -eq 0) { 'aligned' } else { 'mismatch' }
    $backupPath = $null

    if ($Mode -eq 'Apply' -and $differences.Count -gt 0) {
        if ($running) {
            $state = 'pending-restart'
            $hasPending = $true
        } else {
            if (-not (Test-Path -LiteralPath (Join-Path $targetInfo.support 'python312.dll') -PathType Leaf)) {
                throw "python312.dll is missing from $($targetInfo.support)"
            }
            $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            $safeTarget = $targetInfo.name -replace '[^A-Za-z0-9._-]', '_'
            $backupPath = Join-Path $ProjectRoot "state\backups\$stamp\$safeTarget"
            foreach ($difference in $differences) {
                if (Test-Path -LiteralPath $difference.destination -PathType Leaf) {
                    $relative = $difference.destination.Substring($pluginDirectory.Length).TrimStart('\')
                    $backupFile = Join-Path $backupPath $relative
                    New-Item -ItemType Directory -Path (Split-Path -Parent $backupFile) -Force | Out-Null
                    Copy-Item -LiteralPath $difference.destination -Destination $backupFile -Force
                }
            }
            $changedLabels = @($differences | ForEach-Object { $_.label })
            foreach ($entry in $map | Where-Object { $changedLabels -contains $_.label }) {
                New-Item -ItemType Directory -Path (Split-Path -Parent $entry.destination) -Force | Out-Null
                Copy-Item -LiteralPath $entry.source -Destination $entry.destination -Force
            }
            $remaining = @()
            foreach ($entry in $map) {
                $difference = Get-FileDifference -Source $entry.source -Destination $entry.destination -Label $entry.label
                if ($null -ne $difference) {
                    $remaining += $difference
                }
            }
            if ($remaining.Count -gt 0) {
                throw "Post-copy verification failed for $($targetInfo.name)"
            }
            $state = 'applied-and-verified'
            $differences = @()
        }
    }

    if ($differences.Count -gt 0) {
        $hasMismatch = $true
    }
    $results += [pscustomobject]@{
        target = $targetInfo.name
        supportPath = $targetInfo.support
        running = $running
        state = $state
        mismatchCount = $differences.Count
        differences = @($differences | Select-Object label, reason, destination)
        backupPath = $backupPath
    }
}

$report = [pscustomobject]@{
    ok = -not $hasMismatch
    mode = $Mode
    source = $sourceAex
    sourceSha256 = (Get-FileHash -LiteralPath $sourceAex -Algorithm SHA256).Hash
    targets = $results
    pending = $hasPending
}

if ($Mode -eq 'Apply') {
    $stateRoot = Join-Path $ProjectRoot 'state'
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    $report | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $stateRoot 'last-sync.json') -Encoding utf8
}

$report | ConvertTo-Json -Depth 7
if ($Mode -eq 'Verify' -and $hasMismatch) { exit 2 }
if ($Mode -eq 'Apply' -and $hasPending) { exit 3 }
