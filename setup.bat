@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

echo === Transcript Notes (tryll) -- setup ===
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/ with "Add to PATH" enabled.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        exit /b 1
    )
) else (
    echo [1/3] .venv already exists -- reusing
)

REM Probe whether all required packages are already importable.
.venv\Scripts\python -c "import fastapi, uvicorn, faster_whisper, docx, webview, huggingface_hub, multipart" 1>nul 2>nul
if not errorlevel 1 (
    echo [2/3] Python dependencies already installed -- skipping pip
    goto :check_gpu
)

echo [2/3] Installing Python dependencies (2-5 minutes, downloads ~400 MB)...
.venv\Scripts\python -m pip install --upgrade pip wheel
if errorlevel 1 (
    echo [ERROR] pip upgrade failed.
    exit /b 1
)
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed.
    exit /b 1
)

:check_gpu
echo [3/3] Probing GPU...
.venv\Scripts\python -c "import ctranslate2; print('CUDA devices:', ctranslate2.get_cuda_device_count())"

echo.
where claude >nul 2>&1
if errorlevel 1 (
    echo [WARN] Claude CLI not found in PATH.
    echo        Notes generation will not work. Install Claude Code and log in: https://claude.ai/code
) else (
    echo [OK] Claude CLI found.
)

echo.
echo === Setup complete ===
echo Run start.bat or use the TranscriptNotes shortcut.
endlocal
