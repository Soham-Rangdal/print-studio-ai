; Print Studio Setup.exe (Inno Setup 6). Built by .github/workflows/release.yml:
;   iscc /DAppVersion=1.0.0 installer\PrintStudio.iss   ->  installer\Output\PrintStudio-Setup.exe
; The exe holds only the app (a few MB). The 3D engine and the AI models are downloaded by install.ps1,
; which runs in a console window at the end so the user can watch the progress.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B0C1E2A-3F4D-4E8B-9A57-2C1D0E9F4A31}
AppName=Print Studio
AppVersion={#AppVersion}
AppPublisher=Soham-Rangdal
AppPublisherURL=https://github.com/Soham-Rangdal/print-studio-ai
DefaultDirName={localappdata}\PrintStudio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=PrintStudio-Setup
SetupIconFile=..\app\static\icon.ico
UninstallDisplayIcon={app}\app\static\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DiskSpanning=no

[Messages]
SelectDirDesc=Where should Print Studio be installed? The AI models need about 60 GB, so pick a drive with space.

[Tasks]
Name: "llm"; Description: "Idea helper: install Ollama and the Gemma model (about 8 GB) to turn short ideas into better pictures"; GroupDescription: "Optional:"

[Files]
Source: "..\app\*"; DestDir: "{app}\app"; Excludes: "__pycache__"; Flags: recursesubdirs ignoreversion
Source: "..\tools\*"; DestDir: "{app}\tools"; Excludes: "__pycache__"; Flags: recursesubdirs ignoreversion
Source: "..\worker\*"; DestDir: "{app}\worker"; Excludes: "__pycache__"; Flags: recursesubdirs ignoreversion
Source: "..\templates\*"; DestDir: "{app}\templates"; Flags: recursesubdirs ignoreversion
Source: "..\installer\install.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\installer\prefetch.py"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\installer\wangp_core.py"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\installer\engine_check.py"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\setup.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\install.ps1"" -FromSetupExe"; StatusMsg: "Downloading the 3D engine and AI models (watch the console window; this can take an hour)..."; Flags: waituntilterminated; Tasks: llm
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\install.ps1"" -FromSetupExe -NoLLM"; StatusMsg: "Downloading the 3D engine and AI models (watch the console window; this can take an hour)..."; Flags: waituntilterminated; Tasks: not llm
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\app\main.py"""; WorkingDir: "{app}\app"; Description: "Open Print Studio"; Flags: postinstall nowait skipifsilent; Check: Installed

[UninstallDelete]
; the environments, engine and models made by install.ps1 (her projects in jobs\ are kept)
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\engine"
Type: files; Name: "{app}\settings.json"
Type: files; Name: "{app}\.installed"
Type: files; Name: "{app}\install.log"
Type: files; Name: "{userdesktop}\Print Studio.lnk"
Type: files; Name: "{userprograms}\Print Studio.lnk"

[Code]
function Installed: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\.installed'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not Installed then
    MsgBox('Setup did not finish (see the console window or install.log).' + #13#10 +
           'Run setup.bat in ' + ExpandConstant('{app}') + ' to continue where it stopped.', mbError, MB_OK);
end;
