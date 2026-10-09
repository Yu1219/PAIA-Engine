@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PAIA_NO_PAUSE=1"
if not exist logs mkdir logs
echo PAIA Engine - Start and save a diagnostic log
echo.
echo Keep this window open while using the app.
echo If the browser does not open, visit http://localhost:8501
echo Startup details: logs\launch.log
call "%~dp0PAIA_Engine_Source.bat" %* >"%~dp0logs\launch.log" 2>&1
set "paia_result=%errorlevel%"
echo.
type "%~dp0logs\launch.log"
if not defined PAIA_NONINTERACTIVE pause
exit /b %paia_result%
