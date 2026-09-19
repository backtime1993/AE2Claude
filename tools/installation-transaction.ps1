Set-StrictMode -Version Latest

function Assert-DeploymentAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Administrator privileges are required. No installation files have been changed. Run deploy.bat from an elevated terminal.'
    }
}

function Install-StagedFile {
    param([string]$Stage, [string]$Destination)
    if ([IO.File]::Exists($Destination)) {
        [IO.File]::Replace($Stage, $Destination, [System.Management.Automation.Language.NullString]::Value)
    } else {
        [IO.File]::Move($Stage, $Destination)
    }
}

function Invoke-DeploymentTransaction {
    param(
        [Parameter(Mandatory)][object[]]$Entries,
        [Parameter(Mandatory)][string]$PluginDirectory,
        [Parameter(Mandatory)][string]$BackupPath
    )
    $ErrorActionPreference = 'Stop'
    $root = [IO.Path]::GetFullPath($PluginDirectory).TrimEnd('\') + '\'
    $backupRoot = [IO.Path]::GetFullPath($BackupPath).TrimEnd('\') + '\'
    $records = [Collections.Generic.List[object]]::new()
    $touched = [Collections.Generic.List[object]]::new()
    $journal = Join-Path $BackupPath 'transaction.json'
    $phase = 'preflight'
    try {
        # Validate all sources, all original-file write access and all staging paths
        # before replacing even the first installed byte.
        foreach ($entry in $Entries) {
            $destination = [IO.Path]::GetFullPath($entry.destination)
            if (-not $destination.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Deployment destination escapes plugin directory: $destination"
            }
            $relative = $destination.Substring($root.Length)
            $backup = [IO.Path]::GetFullPath((Join-Path $BackupPath $relative))
            if (-not $backup.StartsWith($backupRoot, [StringComparison]::OrdinalIgnoreCase)) {
                throw 'Backup path escapes backup directory'
            }
            if (-not (Test-Path -LiteralPath $entry.source -PathType Leaf)) { throw "Missing source: $($entry.source)" }
            $expectedHash = (Get-FileHash -LiteralPath $entry.source -Algorithm SHA256).Hash
            $existed = [IO.File]::Exists($destination)
            $originalHash = $null
            if ($existed) {
                $handle = [IO.File]::Open($destination, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
                $handle.Dispose()
                $originalHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
            }
            $stage = Join-Path (Split-Path -Parent $destination) ('.ae2claude-' + [guid]::NewGuid().ToString('N') + '.tmp')
            $record = [pscustomobject]@{destination=$destination; backup=$backup; stage=$stage; existed=$existed; originalHash=$originalHash; expectedHash=$expectedHash}
            $records.Add($record)
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            Copy-Item -LiteralPath $entry.source -Destination $stage
            if ((Get-FileHash -LiteralPath $stage -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Staging hash mismatch' }
        }
        foreach ($record in $records) {
            if ($record.existed) {
                New-Item -ItemType Directory -Path (Split-Path -Parent $record.backup) -Force | Out-Null
                Copy-Item -LiteralPath $record.destination -Destination $record.backup
                if ((Get-FileHash -LiteralPath $record.backup -Algorithm SHA256).Hash -ne $record.originalHash) { throw 'Backup hash mismatch' }
            }
        }
        New-Item -ItemType Directory -Path $BackupPath -Force | Out-Null
        @{state='prepared'; files=@($records.ToArray())} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $journal -Encoding utf8
        $phase = 'commit'
        foreach ($record in $records) {
            # Include the current file even if replacement throws after changing it.
            $touched.Add($record)
            Install-StagedFile -Stage $record.stage -Destination $record.destination
        }
        foreach ($record in $records) {
            if ((Get-FileHash -LiteralPath $record.destination -Algorithm SHA256).Hash -ne $record.expectedHash) { throw 'Installed hash mismatch' }
        }
        @{state='committed'; files=@($records.ToArray())} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $journal -Encoding utf8
    } catch {
        $failure = $_.Exception.Message
        $rollbackErrors = [Collections.Generic.List[string]]::new()
        for ($i = $touched.Count - 1; $i -ge 0; $i--) {
            $record = $touched[$i]
            try {
                if ($record.existed) {
                    Copy-Item -LiteralPath $record.backup -Destination $record.destination -Force
                    if ((Get-FileHash -LiteralPath $record.destination -Algorithm SHA256).Hash -ne $record.originalHash) { throw 'Restored hash mismatch' }
                } elseif (Test-Path -LiteralPath $record.destination) {
                    # This exact file was created by this transaction; never remove directories.
                    Remove-Item -LiteralPath $record.destination -Force
                }
            } catch { $rollbackErrors.Add("$($record.destination): $($_.Exception.Message)") }
        }
        $state = if ($rollbackErrors.Count) { 'rollback-failed' } elseif ($touched.Count) { 'rolled-back' } else { 'not-started' }
        if (Test-Path -LiteralPath $BackupPath) {
            @{state=$state; phase=$phase; failure=$failure; rollbackErrors=@($rollbackErrors.ToArray()); files=@($records.ToArray())} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $journal -Encoding utf8
        }
        throw "Deployment failed ($state): $failure. Backup: $BackupPath. $($rollbackErrors -join '; ')"
    } finally {
        foreach ($record in $records) {
            if (Test-Path -LiteralPath $record.stage) {
                Remove-Item -LiteralPath $record.stage -Force -ErrorAction SilentlyContinue
            }
        }
    }
}
