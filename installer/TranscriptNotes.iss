; Inno Setup script for Transcript Notes (tryll).
; Build with:  iscc installer\TranscriptNotes.iss
; Or via:      build_installer.bat (handles iscc detection)

#define MyAppName "Transcript Notes"
#define MyAppShortName "TranscriptNotes"
#define MyAppVersion "1.0.2"
#define MyAppPublisher "tryll"
#define MyAppExeName "TranscriptNotes.exe"

[Setup]
AppId={{B7A4F1F8-7C5A-4E3B-9F1D-6E2E1A4C8B0F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppShortName}
DefaultGroupName={#MyAppName}
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\
OutputBaseFilename={#MyAppShortName}-Setup-{#MyAppVersion}
SetupIconFile=..\build\app.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian";  MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\TranscriptNotes.exe";  DestDir: "{app}"; Flags: ignoreversion
Source: "..\launcher.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt";      DestDir: "{app}"; Flags: ignoreversion
Source: "..\setup.bat";             DestDir: "{app}"; Flags: ignoreversion
Source: "..\start.bat";             DestDir: "{app}"; Flags: ignoreversion
Source: "..\build_exe.bat";         DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md";             DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\app\*";                 DestDir: "{app}\app";   Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\tools\*";               DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\app.ico";         DestDir: "{app}\build"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}";       Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\build\app.ico"
Name: "{group}\Открыть папку";      Filename: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\build\app.ico"; Tasks: desktopicon

[Run]
; Post-install: create .venv + install pip deps. Show progress in a window.
Filename: "{cmd}"; Parameters: "/C ""cd /d ""{app}"" && setup.bat"""; \
    StatusMsg: "Установка Python-зависимостей (это займёт 2–5 минут)…"; \
    Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Keep .venv between reinstalls — recreating it takes 2–5 min of pip install.
; If user really wants a clean slate, they can delete %LOCALAPPDATA%\Programs\TranscriptNotes\.venv manually.
Type: filesandordirs; Name: "{app}\build"
Type: filesandordirs; Name: "{app}\app\__pycache__"

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // Verify Python is on PATH — required by setup.bat to create the venv.
  if not Exec('cmd.exe', '/C where python >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    MsgBox('Не удалось проверить наличие Python.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if ResultCode <> 0 then
  begin
    if MsgBox(
        'В PATH не найден Python.'#13#10#13#10 +
        'Этому приложению нужен Python 3.10+ для создания виртуального окружения.'#13#10 +
        'Установи его с https://www.python.org/downloads/ ' +
        '(не забудь галочку "Add to PATH") и запусти инсталлятор снова.'#13#10#13#10 +
        'Открыть страницу загрузки сейчас?',
        mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', 'https://www.python.org/downloads/', '', '', SW_SHOW, ewNoWait, ResultCode);
    Result := False;
    Exit;
  end;

  // Soft warning about Claude CLI (not fatal — user can install later).
  if not Exec('cmd.exe', '/C where claude >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    ResultCode := 1;
  if ResultCode <> 0 then
    MsgBox(
      'Внимание: в PATH не найден Claude CLI.'#13#10#13#10 +
      'Без него транскрипция будет работать, но автоматические заметки нет. ' +
      'Установи Claude Code и войди (claude auth login).'#13#10#13#10 +
      'Установку можно продолжить — это просто предупреждение.',
      mbInformation, MB_OK);

  Result := True;
end;
