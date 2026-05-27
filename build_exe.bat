@echo off
setlocal
cd /d "%~dp0"

echo === Сборка TranscriptNotes.exe ===
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv не найден. Сначала запусти setup.bat
    exit /b 1
)

echo [1/3] Ставлю build-зависимости (pyinstaller, pillow)...
.venv\Scripts\pip install --quiet pyinstaller pillow
if errorlevel 1 (
    echo [ERROR] pip install упал.
    exit /b 1
)

echo [2/3] Генерирую иконку...
.venv\Scripts\python tools\make_icon.py
if errorlevel 1 (
    echo [WARN] не удалось сделать иконку, собираю без неё.
    set ICON_ARG=
) else (
    set ICON_ARG=--icon "%CD%\build\app.ico"
)

echo [3/3] Запускаю PyInstaller...
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed ^
    --name "TranscriptNotes" ^
    %ICON_ARG% ^
    --distpath . ^
    --workpath build\pyinstaller ^
    --specpath build\pyinstaller ^
    launcher.py
if errorlevel 1 (
    echo [ERROR] PyInstaller упал.
    exit /b 1
)

echo.
echo === Готово ===
echo TranscriptNotes.exe лежит в корне. Дважды кликни — откроется приложение.
endlocal
