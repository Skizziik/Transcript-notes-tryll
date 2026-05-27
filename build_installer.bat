@echo off
setlocal
cd /d "%~dp0"

echo === Сборка TranscriptNotes-Setup.exe ===
echo.

if not exist "TranscriptNotes.exe" (
    echo [INFO] TranscriptNotes.exe не найден — запускаю build_exe.bat...
    call build_exe.bat
    if errorlevel 1 (
        echo [ERROR] Не удалось собрать TranscriptNotes.exe
        exit /b 1
    )
)

if not exist "build\app.ico" (
    echo [INFO] Иконки нет, делаю...
    .venv\Scripts\python tools\make_icon.py
)

REM Locate Inno Setup Compiler
set "ISCC="
for %%P in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
) do (
    if exist %%P set "ISCC=%%~P"
)

if "%ISCC%"=="" (
    echo [ERROR] Не найден Inno Setup Compiler (ISCC.exe).
    echo Установи Inno Setup 6 отсюда: https://jrsoftware.org/isdl.php
    echo После установки запусти этот скрипт снова.
    exit /b 1
)

echo [INFO] Использую: %ISCC%
echo.
"%ISCC%" "installer\TranscriptNotes.iss"
if errorlevel 1 (
    echo [ERROR] Inno Setup упал.
    exit /b 1
)

echo.
echo === Готово ===
for %%F in (TranscriptNotes-Setup-*.exe) do echo Установщик: %%F
endlocal
