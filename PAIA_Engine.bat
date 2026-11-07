@echo off
title PAIA Engine
echo.
echo   Starting PAIA Engine...
echo   Your browser will open automatically.
echo   Keep this window open while using the app.
echo.

if exist "%~dp0dist-high-priority\PAIA_Engine\PAIA_Engine.exe" (
    "%~dp0dist-high-priority\PAIA_Engine\PAIA_Engine.exe"
) else if exist "%~dp0dist\PAIA_Engine\PAIA_Engine.exe" (
    "%~dp0dist\PAIA_Engine\PAIA_Engine.exe"
) else (
    echo ERROR: PAIA_Engine.exe not found.
    echo Please run build.bat first to create the executable.
    echo.
    pause
)
