@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

echo === Build TranscriptNotes.exe ===
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run setup.bat first.
    exit /b 1
)

echo [1/3] Installing build deps (pyinstaller, pillow)...
.venv\Scripts\pip install --quiet pyinstaller pillow
if errorlevel 1 (
    echo [ERROR] pip install failed.
    exit /b 1
)

echo [2/3] Generating icon...
.venv\Scripts\python tools\make_icon.py
if errorlevel 1 (
    echo [WARN] icon generation failed, building without icon.
    set ICON_ARG=
) else (
    set ICON_ARG=--icon "%CD%\build\app.ico"
)

echo [3/3] Running PyInstaller...
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed ^
    --name "TranscriptNotes" ^
    %ICON_ARG% ^
    --distpath . ^
    --workpath build\pyinstaller ^
    --specpath build\pyinstaller ^
    launcher.py
if errorlevel 1 (
    echo [ERROR] PyInstaller failed.
    exit /b 1
)

echo.
echo === Done ===
echo TranscriptNotes.exe is in the project root. Double-click to launch.
endlocal
