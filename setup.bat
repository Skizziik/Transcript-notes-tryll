@echo off
setlocal ENABLEDELAYEDEXPANSION
cd /d "%~dp0"

echo === Transcript Notes (tryll) — setup ===
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python не найден в PATH.
    echo Установи Python 3.10+ с https://www.python.org/downloads/ и поставь галочку "Add to PATH".
    exit /b 1
)

if not exist ".venv\" (
    echo [1/4] Создаю .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Не удалось создать venv.
        exit /b 1
    )
)

echo [2/4] Обновляю pip...
.venv\Scripts\python -m pip install --upgrade pip wheel

echo [3/4] Ставлю Python зависимости...
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install упал.
    exit /b 1
)

echo [4/4] Проверяю GPU...
.venv\Scripts\python -c "import ctranslate2; n=ctranslate2.get_cuda_device_count(); print(f'CUDA devices: {n}')"

echo.
where claude >nul 2>&1
if errorlevel 1 (
    echo [WARN] Claude CLI не найден в PATH.
    echo        Заметки не будут генерироваться. Установи Claude Code и залогинься: https://claude.ai/code
) else (
    echo [OK] Claude CLI найден.
)

echo.
echo === Установка завершена ===
echo Запусти приложение: start.bat
endlocal
