@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PAIA_NO_PAUSE=1"
echo PAIA Engine - Build a standalone folder for this PC
echo.
call "%~dp0PAIA_Engine_Source.bat" --build
set "paia_result=%errorlevel%"
echo.
if not "%paia_result%"=="0" goto failed
echo BUILD COMPLETE. Read the output path above.
goto finished
:failed
echo BUILD FAILED. See logs\build.log and the detailed manual.
:finished
if not defined PAIA_NONINTERACTIVE pause
exit /b %paia_result%
