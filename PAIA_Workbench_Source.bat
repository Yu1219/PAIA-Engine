@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" paia_desktop.py
) else (
  echo Run 01_Setup_Libraries.bat first, or use the standalone ZIP.
  pause
)
