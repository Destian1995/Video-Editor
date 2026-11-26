@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
    exit /b
)

where /q pythonw
if not errorlevel 1 (
    start "" pythonw "%~dp0main.py"
    exit /b
)

echo Python was not found. Install Python and the dependencies from requirements.txt.
pause
exit /b 1
