@echo off
setlocal EnableExtensions

set "SYNC_SCRIPT=%~dp0tools\sync-installation.ps1"
where pwsh.exe >nul 2>nul
if errorlevel 1 (
    set "POWERSHELL=powershell.exe"
) else (
    set "POWERSHELL=pwsh.exe"
)

if not exist "%SYNC_SCRIPT%" (
    echo ERROR: Sync script not found: %SYNC_SCRIPT%
    exit /b 1
)

if "%~1"=="" (
    "%POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%SYNC_SCRIPT%" -Mode Apply
) else (
    "%POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%SYNC_SCRIPT%" -Mode Apply -Target "%~1"
)

set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="3" (
    echo AE2Claude source and installation differ, but the target AE is running. Close AE and rerun.
)
exit /b %RESULT%
