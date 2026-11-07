@echo off
cd /d "%~dp0"
echo ============================================================
echo   PAIA Engine -- Build Standalone Executable
echo ============================================================
echo.

:: Check for PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
    echo.
)

:: Check for openpyxl (needed for Excel file support)
pip show openpyxl >nul 2>&1
if errorlevel 1 (
    echo Installing openpyxl...
    pip install openpyxl
    echo.
)

echo Building PAIA Engine...
echo.
pyinstaller paia.spec --noconfirm --distpath dist-high-priority --workpath build-high-priority
if errorlevel 1 goto build_failed

echo.
if exist "dist-high-priority\PAIA_Engine\PAIA_Engine.exe" (
    echo ============================================================
    echo   BUILD SUCCESSFUL!
    echo   Output: dist-high-priority\PAIA_Engine\PAIA_Engine.exe
    echo.
    echo   To distribute: zip the entire dist-high-priority\PAIA_Engine folder
    echo   and share it. Users just run PAIA_Engine.exe.
    echo ============================================================
) else (
    echo BUILD FAILED. Check the output above for errors.
)
echo.
pause
goto :eof

:build_failed
echo.
echo BUILD FAILED. Check the output above for errors.
pause
