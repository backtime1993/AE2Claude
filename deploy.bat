@echo off
setlocal enabledelayedexpansion

echo === AE2Claude Deployer ===

:: Auto-detect AE installations
set FOUND=0
for %%V in ("Adobe After Effects (Beta)" "Adobe After Effects 2025" "Adobe After Effects 2024" "Adobe After Effects 2023") do (
    if exist "C:\Program Files\Adobe\%%~V\Support Files" (
        set /a FOUND+=1
        set "AE_NAME=%%~V"
        set "AE_DIR=C:\Program Files\Adobe\%%~V\Support Files"
        echo   [!FOUND!] %%~V
    )
)

if %FOUND%==0 (
    echo ERROR: No After Effects installation found.
    exit /b 1
)

if %FOUND%==1 (
    echo Auto-selected: %AE_NAME%
) else (
    set /p CHOICE="Select [1-%FOUND%]: "
    set IDX=0
    for %%V in ("Adobe After Effects (Beta)" "Adobe After Effects 2025" "Adobe After Effects 2024" "Adobe After Effects 2023") do (
        if exist "C:\Program Files\Adobe\%%~V\Support Files" (
            set /a IDX+=1
            if "!IDX!"=="!CHOICE!" (
                set "AE_NAME=%%~V"
                set "AE_DIR=C:\Program Files\Adobe\%%~V\Support Files"
            )
        )
    )
)

set PLUGIN_DIR=%AE_DIR%\Plug-ins
echo Deploying to: %AE_NAME%

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

:: Ensure python DLLs are present
if not exist "%AE_DIR%\python312.dll" (
    echo WARNING: python312.dll not found in Support Files.
    echo Copy python312.dll + python3.dll from your Python 3.12 installation.
)

echo === Done. Restart AE to activate. ===
pause
