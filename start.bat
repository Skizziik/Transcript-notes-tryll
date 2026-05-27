@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo .venv not found. Run setup.bat first.
    exit /b 1
)

.venv\Scripts\python -m app.main
endlocal
