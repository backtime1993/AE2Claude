@echo off
setlocal

set AE_DIR=C:\Program Files\Adobe\Adobe After Effects (Beta)\Support Files
set PLUGIN_DIR=%AE_DIR%\Plug-ins

echo === AE2Claude Deployer ===

:: Check AE directory exists
if not exist "%AE_DIR%" (
    echo ERROR: AE directory not found: %AE_DIR%
    exit /b 1
)

:: Copy plugin
echo Copying AE2Claude.aex...
copy /Y "%~dp0AE2Claude.aex" "%PLUGIN_DIR%\AE2Claude.aex"
if errorlevel 1 (
    echo WARNING: Could not copy .aex - AE may be running. Close AE first.
) else (
    echo OK
)

:: Copy server script
echo Copying ae2claude_server.py...
copy /Y "%~dp0ae2claude_server.py" "%PLUGIN_DIR%\ae2claude_server.py"
echo OK

:: Ensure python312.dll is present
if not exist "%AE_DIR%\python312.dll" (
    echo WARNING: python312.dll not found in AE Support Files.
    echo Copy it from your Python 3.12 installation.
)

echo === Done. Restart AE to activate. ===
pause
