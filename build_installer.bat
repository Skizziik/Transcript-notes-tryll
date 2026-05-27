@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

echo === Build TranscriptNotes-Setup.exe ===
echo.

if not exist "TranscriptNotes.exe" (
    echo [INFO] TranscriptNotes.exe missing -- running build_exe.bat first...
    call build_exe.bat
    if errorlevel 1 (
        echo [ERROR] Failed to build TranscriptNotes.exe
        exit /b 1
    )
)

if not exist "build\app.ico" (
    echo [INFO] Icon missing, generating...
    .venv\Scripts\python tools\make_icon.py
)

REM Locate Inno Setup Compiler.
set "ISCC="
for %%P in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
) do (
    if exist %%P set "ISCC=%%~P"
)

if "%ISCC%"=="" (
    echo [ERROR] Inno Setup Compiler not found.
    echo Install Inno Setup 6 from https://jrsoftware.org/isdl.php and re-run.
    exit /b 1
)

echo [INFO] Using: %ISCC%
echo.
"%ISCC%" "installer\TranscriptNotes.iss"
if errorlevel 1 (
    echo [ERROR] Inno Setup failed.
    exit /b 1
)

echo.
echo === Done ===
for %%F in (TranscriptNotes-Setup-*.exe) do echo Installer: %%F
endlocal
