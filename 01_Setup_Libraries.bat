@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PAIA_NO_PAUSE=1"
if not exist logs mkdir logs
echo PAIA Engine - Library setup
echo.
echo Please wait. The first setup needs an internet connection.
echo Details are saved in logs\setup.log
call "%~dp0PAIA_Engine_Source.bat" --setup-only >"%~dp0logs\setup.log" 2>&1
set "paia_result=%errorlevel%"
echo.
type "%~dp0logs\setup.log"
echo.
if not "%paia_result%"=="0" goto failed
echo READY. Double-click PAIA_Engine_Source.bat to start the app.
goto finished
:failed
echo SETUP FAILED. See logs\setup.log and the detailed manual.
:finished
if not defined PAIA_NONINTERACTIVE pause
exit /b %paia_result%
