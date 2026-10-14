@echo off
REM ===================================================================
REM  Athenaeum MCP - uninstaller for Windows.
REM  Removes Athenaeum from every detected client configuration (backups
REM  are created automatically). Add  -Purge  to also delete the virtual
REM  environment and caches:
REM     uninstall.bat -Purge
REM ===================================================================
setlocal
set "SCRIPT_DIR=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install.ps1" -Uninstall %*
set "RC=%ERRORLEVEL%"

echo.
if "%~1"=="" pause
exit /b %RC%
