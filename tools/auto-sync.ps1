[CmdletBinding()]
param(
    [switch]$SkipFetch,
    [switch]$SkipNativeBuild,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonDir = 'C:\Users\kensei\scoop\apps\python312\current',
    [string]$VcpkgInstalled = 'F:\claude\deps\vcpkg-repo\installed',
    [string]$Pybind11Dir = 'F:\claude\deps\pybind11'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$stateRoot = Join-Path $ProjectRoot 'state'
New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
$startedAt = Get-Date

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$Label,
        [int[]]$AllowedExitCodes = @(0)
    )
    & $FilePath @Arguments
    $exitCode = $LASTEXITCODE
    if ($AllowedExitCodes -notcontains $exitCode) {
        throw "$Label failed with exit code $exitCode"
    }
    return $exitCode
}

try {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git'))) {
        throw "Not a Git worktree: $ProjectRoot"
    }
    $branch = (& git -C $ProjectRoot branch --show-current).Trim()
    if ($branch -ne 'master') {
        throw "Automatic sync only runs on master; current branch is $branch"
    }
    $dirty = @(& git -C $ProjectRoot status --porcelain)
    if ($dirty.Count -gt 0) {
        throw 'Automatic sync refuses a dirty worktree.'
    }

    $beforeHead = (& git -C $ProjectRoot rev-parse HEAD).Trim()
    if (-not $SkipFetch) {
        Invoke-Checked -FilePath 'git' -Arguments @('-C', $ProjectRoot, 'fetch', '--prune', 'origin', 'master') -Label 'git fetch' | Out-Null
        & git -C $ProjectRoot merge-base --is-ancestor $beforeHead origin/master
        $localAncestor = $LASTEXITCODE -eq 0
        & git -C $ProjectRoot merge-base --is-ancestor origin/master $beforeHead
        $remoteAncestor = $LASTEXITCODE -eq 0
        if (-not $localAncestor -and -not $remoteAncestor) {
            throw 'Local master and origin/master diverged; manual review is required.'
        }
        if ($localAncestor -and -not $remoteAncestor) {
            Invoke-Checked -FilePath 'git' -Arguments @('-C', $ProjectRoot, 'merge', '--ff-only', 'origin/master') -Label 'fast-forward master' | Out-Null
        }
    }

    $afterHead = (& git -C $ProjectRoot rev-parse HEAD).Trim()
    $updated = $beforeHead -ne $afterHead

    if ($updated) {
        $uv = (Get-Command uv -ErrorAction Stop).Source
        Invoke-Checked -FilePath $uv -Arguments @('sync', '--locked', '--project', $ProjectRoot) -Label 'uv sync' | Out-Null
        Invoke-Checked -FilePath $uv -Arguments @('run', '--project', $ProjectRoot, 'python', '-m', 'unittest', 'discover', '-s', (Join-Path $ProjectRoot 'tests'), '-v') -Label 'Python tests' | Out-Null

        $pinRoot = Join-Path $ProjectRoot 'extensions\pin-clicker'
        $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
        Invoke-Checked -FilePath $npm -Arguments @('ci', '--omit=dev', '--no-audit', '--no-fund', '--prefix', $pinRoot) -Label 'PinClicker npm ci' | Out-Null
        Invoke-Checked -FilePath $npm -Arguments @('run', 'check', '--prefix', $pinRoot) -Label 'PinClicker syntax check' | Out-Null

        if (-not $SkipNativeBuild) {
            $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
            if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
                throw "vswhere.exe was not found: $vswhere"
            }
            $msbuild = (& $vswhere -latest -products '*' -requires Microsoft.Component.MSBuild -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1)
            if (-not $msbuild) {
                throw 'MSBuild.exe was not found by vswhere.'
            }
            foreach ($dependency in @($PythonDir, $VcpkgInstalled, $Pybind11Dir)) {
                if (-not (Test-Path -LiteralPath $dependency)) {
                    throw "Native build dependency is missing: $dependency"
                }
            }
            $env:PYTHON_DIR = $PythonDir
            $env:VCPKG_INSTALLED = $VcpkgInstalled
            $env:PYBIND11_DIR = $Pybind11Dir
            Invoke-Checked -FilePath $msbuild -Arguments @(
                (Join-Path $ProjectRoot 'src\PyShiftAE\Win\PyShiftAE.vcxproj'),
                '/m',
                '/p:Configuration=Release',
                '/p:Platform=x64',
                '/v:minimal',
                '/nologo'
            ) -Label 'native Release build' | Out-Null
        }
    }

    $syncScript = Join-Path $PSScriptRoot 'sync-installation.ps1'
    $pwsh = (Get-Process -Id $PID).Path
    & $pwsh -NoProfile -File $syncScript -Mode Apply -AllSupported -ProjectRoot $ProjectRoot
    $syncExit = $LASTEXITCODE
    if (@(0, 3) -notcontains $syncExit) {
        throw "installation sync failed with exit code $syncExit"
    }

    $result = [pscustomobject]@{
        ok = $true
        updated = $updated
        beforeHead = $beforeHead
        afterHead = $afterHead
        installationPending = $syncExit -eq 3
        startedAt = $startedAt.ToString('o')
        finishedAt = (Get-Date).ToString('o')
    }
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $stateRoot 'last-auto-sync.json') -Encoding utf8
    $result | ConvertTo-Json -Depth 5
    if (-not $updated -and $syncExit -eq 0) { exit 2 }
    exit 0
} catch {
    $result = [pscustomobject]@{
        ok = $false
        error = $_.Exception.Message
        startedAt = $startedAt.ToString('o')
        finishedAt = (Get-Date).ToString('o')
    }
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $stateRoot 'last-auto-sync.json') -Encoding utf8
    $result | ConvertTo-Json -Depth 5
    exit 1
}
