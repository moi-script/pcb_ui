; Inno Setup script: wraps dist\TraceWorks into TraceWorks-Setup-<version>.exe.
; build.ps1 runs it; to run by hand:
;   iscc /DAppVersion=0.1.0 desktop\installer.iss

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6F1C2B7E-4E0A-4F53-9C1B-7A3D5E2B9C41}
AppName=TraceWorks
AppVersion={#AppVersion}
AppPublisher=TraceWorks
DefaultDirName={autopf}\TraceWorks
DefaultGroupName=TraceWorks
DisableProgramGroupPage=yes
; Per-user install by default: no admin prompt, like installing a phone app.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=TraceWorks-Setup-{#AppVersion}
SetupIconFile=traceworks.ico
UninstallDisplayIcon={app}\TraceWorks.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\TraceWorks\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TraceWorks"; Filename: "{app}\TraceWorks.exe"
Name: "{autodesktop}\TraceWorks"; Filename: "{app}\TraceWorks.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TraceWorks.exe"; Description: "{cm:LaunchProgram,TraceWorks}"; Flags: nowait postinstall skipifsilent

; Boards and settings live in %LOCALAPPDATA%\TraceWorks and are deliberately
; kept on uninstall, so reinstalling or upgrading loses nothing.
