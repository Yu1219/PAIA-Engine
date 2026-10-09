@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
if not exist logs mkdir logs
echo PAIA Engine - Read-only PC check
echo No libraries or system settings will be changed.
echo.
>"%~dp0logs\pc_check.txt" echo PAIA Engine - PC check
>>"%~dp0logs\pc_check.txt" echo Date: %date% %time%
ver >>"%~dp0logs\pc_check.txt" 2>&1
powershell.exe -NoProfile -Command "'OS version: ' + [Environment]::OSVersion.VersionString; '64-bit OS: ' + [Environment]::Is64BitOperatingSystem; 'CPU: ' + $env:PROCESSOR_IDENTIFIER; 'Architecture: ' + $env:PROCESSOR_ARCHITECTURE; $win=Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'; $win | Select-Object ProductName,DisplayVersion,CurrentBuild,UBR | Format-List" >>"%~dp0logs\pc_check.txt" 2>&1
>>"%~dp0logs\pc_check.txt" echo --- Port 8501 (LISTENING means the port is in use) ---
netstat -ano -p TCP | findstr ":8501 " >>"%~dp0logs\pc_check.txt" 2>&1
>>"%~dp0logs\pc_check.txt" echo --- Installed Python runtimes ---
py -0p >>"%~dp0logs\pc_check.txt" 2>&1
py -3.14 -c "import sys,struct,platform; print('Python:',sys.version); print('Executable:',sys.executable); print('Bits:',struct.calcsize('P')*8); print('Machine:',platform.machine())" >>"%~dp0logs\pc_check.txt" 2>&1
>>"%~dp0logs\pc_check.txt" echo --- Python on PATH ---
python -c "import sys,struct,platform; print('Python:',sys.version); print('Executable:',sys.executable); print('Bits:',struct.calcsize('P')*8); print('Machine:',platform.machine())" >>"%~dp0logs\pc_check.txt" 2>&1
type "%~dp0logs\pc_check.txt"
echo.
echo Saved: logs\pc_check.txt
if not defined PAIA_NONINTERACTIVE pause
exit /b 0
