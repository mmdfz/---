@echo off
REM ===================================================================
REM  Athenaeum MCP - one-click setup for Windows.
REM  Double-click this file, or run it from a terminal. It bootstraps a
REM  Python environment and configures Athenaeum in your AI coding clients.
REM
REM  Any arguments are passed straight through to install.ps1, e.g.:
REM     setup.bat -Scope user
REM     setup.bat -Clients vscode cursor
REM     setup.bat -DryRun
REM ===================================================================
setlocal
set "SCRIPT_DIR=%~dp0"

where powershell >nul 2>nul
if errorlevel 1 (
    echo PowerShell was not found. Please install it or run install.ps1 manually.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install.ps1" %*
set "RC=%ERRORLEVEL%"

REM Pause only when launched by double-click (no console args, interactive).
echo.
if "%~1"=="" pause
exit /b %RC%
