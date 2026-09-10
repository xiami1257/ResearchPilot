@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem NOTE: keep this file ASCII-only. cmd.exe parses .bat in the OEM codepage
rem (GBK here), so UTF-8 Chinese text gets byte-misaligned and lines merge.

set RP_PORT=8001
rem Absolute %~dp0 paths: this machine sets NoDefaultCurrentDirectoryInExePath,
rem so cmd does NOT search the current directory for commands.
set PY=%~dp0.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

echo ============================================
echo   ResearchPilot - Multi-Agent Research
echo --------------------------------------------
echo   Local  : http://127.0.0.1:8001
echo   Public : your Oray domain (client must be online)
echo   Close this window to stop the server.
echo ============================================
echo.

"%PY%" "%~dp0scripts\serve.py"

echo.
echo [Server exited] If the port is busy, close the other window and retry.
pause
