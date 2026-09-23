@echo off
setlocal
cd /d "%~dp0"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PSModulePath=%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules"

echo Preparing SpotiDown...
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo SpotiDown could not start. See the error above.
    pause
    exit /b 1
)

start "SpotiDown" /D "%~dp0" "%~dp0.runtime\python\pythonw.exe" "%~dp0main.py"
exit /b 0
