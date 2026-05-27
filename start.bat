@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo .venv не найден. Сначала запусти setup.bat
    exit /b 1
)

.venv\Scripts\python -m app.main
endlocal
