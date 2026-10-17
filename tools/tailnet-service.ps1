[CmdletBinding()]
param(
    [ValidateSet('Install', 'Start', 'Stop', 'Status', 'Remove')][string]$Action = 'Status',
    [string]$Hostname,
    [string]$AllowedLogin
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$name = 'AE2Claude-Tailnet'
$python = Join-Path $root '.venv\Scripts\pythonw.exe'
$config = Join-Path $root 'state\tailnet-mcp.json'
$task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($task) {
    $owned = @($task.Actions | Where-Object { $_.Execute -eq $python -and $_.Arguments -eq ('-m ae2claude_mcp.tailnet --config "' + $config + '"') })
    if ($owned.Count -ne 1) { throw 'Existing task is not owned by this deployment; refusing to change it.' }
}
switch ($Action) {
    'Install' {
        if ($task) { throw 'Already installed. Use Start or Status; stop before changing configuration.' }
        if (-not (Test-Path -LiteralPath $python)) { throw "Missing runtime: $python" }
        if ($Hostname -notmatch '^[a-z0-9-]+\.[a-z0-9-]+\.ts\.net$' -or [string]::IsNullOrWhiteSpace($AllowedLogin)) {
            throw 'Hostname and AllowedLogin are required for installation.'
        }
        New-Item -ItemType Directory -Path (Split-Path $config -Parent) -Force | Out-Null
        if (Test-Path -LiteralPath $config) { Copy-Item -LiteralPath $config -Destination ($config + '.' + (Get-Date -Format yyyyMMddHHmmss) + '.bak') }
        @{ hostname=$Hostname; allowed_login=$AllowedLogin; port=18890; ae_port=18889 } | ConvertTo-Json | Set-Content -LiteralPath $config -Encoding utf8
        $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $run = New-ScheduledTaskAction -Execute $python -Argument ('-m ae2claude_mcp.tailnet --config "' + $config + '"') -WorkingDirectory $root
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $name -Action $run -Trigger $trigger -Principal $principal -Settings $settings -Description 'Private AE MCP loopback backend for Tailscale Serve; source and stop command in AE2Claude tools/tailnet-service.ps1.' | Out-Null
        Start-ScheduledTask -TaskName $name
    }
    'Start' {
        if (-not $task) { throw 'Service is not installed.' }
        Enable-ScheduledTask -TaskName $name | Out-Null
        Start-ScheduledTask -TaskName $name
    }
    'Stop' {
        if ($task) { Disable-ScheduledTask -TaskName $name | Out-Null; Stop-ScheduledTask -TaskName $name }
    }
    'Remove' {
        if ($task) {
            Disable-ScheduledTask -TaskName $name | Out-Null
            Stop-ScheduledTask -TaskName $name
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
        }
        # Keep configuration and bounded logs as recoverable evidence.
    }
}
Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue | Select-Object TaskName,State
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Get-ScheduledTaskInfo -TaskName $name | Select-Object LastRunTime,LastTaskResult
}
