#ifndef AppVersion
  #define AppVersion "1.6.0"
#endif
[Setup]
AppId={{D3F59318-2A4F-4C1A-900E-B83A85105E36}
AppName=NTE-AI 异环助手
AppVersion={#AppVersion}
AppPublisher=NTE-AI
DefaultDirName={localappdata}\Programs\NTE-AI
DefaultGroupName=NTE-AI 异环助手
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=NTE-AI-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\NTE-AI.exe
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\NTE-AI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\异环助手"; Filename: "{app}\NTE-AI.exe"; WorkingDir: "{app}"
Name: "{group}\异环助手"; Filename: "{app}\NTE-AI.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\NTE-AI.exe"; Description: "打开异环助手"; Flags: nowait postinstall skipifsilent
