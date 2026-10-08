@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
title PAIA Engine - Python 3.14

py -3.14 -c "import sys; assert sys.version_info[:2] == (3,14)" >nul 2>&1
if not errorlevel 1 goto run_py

python -c "import sys; assert sys.version_info[:2] == (3,14)" >nul 2>&1
if not errorlevel 1 goto run_python

python3.14 -c "import sys; assert sys.version_info[:2] == (3,14)" >nul 2>&1
if not errorlevel 1 goto run_python314

if exist "%LocalAppData%\Programs\Python\Python314\python.exe" goto run_local

echo Python 3.14 was not found.
echo Install 64-bit Python 3.14 from https://www.python.org/downloads/windows/
echo If Python 3.14 is installed elsewhere, run:
echo   "path\to\python.exe" bootstrap.py
echo.
pause
exit /b 1

:run_py
py -3.14 "%~dp0bootstrap.py" %*
goto finished

:run_python
python "%~dp0bootstrap.py" %*
goto finished

:run_python314
python3.14 "%~dp0bootstrap.py" %*
goto finished

:run_local
"%LocalAppData%\Programs\Python\Python314\python.exe" "%~dp0bootstrap.py" %*
goto finished

:finished
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo Setup or launch failed. Please check the messages above.
pause
exit /b 1
