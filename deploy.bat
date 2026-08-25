@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "VERSION=4.2.0"
set "SOURCE_AEX=%~dp0build\Release\AE2Claude.aex"

echo === AE2Claude %VERSION% Deployer ===

if not exist "%SOURCE_AEX%" (
    echo ERROR: Release build not found: %SOURCE_AEX%
    echo Build Release x64 before deploying. The stale repository-root binary is never used.
    exit /b 1
)

if not "%~1"=="" (
    set "AE_NAME=%~1"
    set "AE_DIR=C:\Program Files\Adobe\%~1\Support Files"
    if not exist "!AE_DIR!" (
        echo ERROR: Requested After Effects target was not found: !AE_DIR!
        exit /b 1
    )
    goto target_selected
)

set "FOUND=0"
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

if not %FOUND%==1 (
    set "AE_NAME="
    set "AE_DIR="
    set /p CHOICE="Select [1-%FOUND%]: "
    set "IDX=0"
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

if not defined AE_DIR (
    echo ERROR: Invalid target selection.
    exit /b 1
)

:target_selected
set "PLUGIN_DIR=%AE_DIR%\Plug-ins"
echo Deploying to: %AE_NAME%

if not exist "!AE_DIR!\python312.dll" (
    echo ERROR: python312.dll is missing from !AE_DIR!
    exit /b 1
)

if exist "!PLUGIN_DIR!\AE2Claude.aex" if not exist "!PLUGIN_DIR!\AE2Claude.aex.bak-before-!VERSION!" (
    copy /Y "!PLUGIN_DIR!\AE2Claude.aex" "!PLUGIN_DIR!\AE2Claude.aex.bak-before-!VERSION!" >nul
    if errorlevel 1 (
        echo ERROR: Could not create plugin backup. Close After Effects and retry.
        exit /b 1
    )
)

copy /Y "!SOURCE_AEX!" "!PLUGIN_DIR!\AE2Claude.aex" >nul
if errorlevel 1 (
    echo ERROR: Could not deploy AE2Claude.aex. Close After Effects and retry.
    exit /b 1
)

fc /B "!SOURCE_AEX!" "!PLUGIN_DIR!\AE2Claude.aex" >nul
if errorlevel 1 (
    echo ERROR: Deployed AE2Claude.aex failed byte-for-byte verification.
    exit /b 1
)

for %%F in (ae2claude_server.py ae_bridge.py ae2claude) do (
    copy /Y "%~dp0%%F" "!PLUGIN_DIR!\%%F" >nul
    if errorlevel 1 (
        echo ERROR: Could not deploy %%F.
        exit /b 1
    )
)

if not exist "!PLUGIN_DIR!\scripts" mkdir "!PLUGIN_DIR!\scripts"
xcopy /Y /E /Q "%~dp0scripts\*" "!PLUGIN_DIR!\scripts\" >nul
if errorlevel 2 (
    echo ERROR: Could not deploy scripts.
    exit /b 1
)

if not exist "!PLUGIN_DIR!\presets" mkdir "!PLUGIN_DIR!\presets"
xcopy /Y /E /Q "%~dp0presets\*" "!PLUGIN_DIR!\presets\" >nul
if errorlevel 2 (
    echo ERROR: Could not deploy presets.
    exit /b 1
)

echo === Deploy verified. Restart After Effects to activate AE2Claude %VERSION%. ===
exit /b 0
