; Kresorter's installer (decision 0015, item 15), made by Inno Setup on Windows from the folder
; kresorter.spec makes; from the repository's root, with the version of the package:
;
;     iscc /DAppVersion=0.1.0 packaging\windows\kresorter.iss
;
; It shows LICENSE, the MIT licence, before it installs (decision 0019, item 20), and installs for
; the current user, with no administrator rights, into %LOCALAPPDATA%\Programs\Kresorter. Its
; uninstaller removes what it installed and nothing
; else: Kresorter's data directory, with the journal and the quarantined files, stays.

#ifndef AppVersion
  #error Give the version of the package: iscc /DAppVersion=X.Y.Z kresorter.iss
#endif
#define Root SourcePath + "..\..\"
#define Folder Root + "dist\Kresorter"
#define Icon Root + "build\kresorter\kresorter.ico"

[Setup]
AppId={{C4423471-5A24-4030-806C-5E6549A5617E}
AppName=Kresorter
AppVersion={#AppVersion}
AppPublisher=KKrecker
AppPublisherURL=https://github.com/KKrecker/kresorter
AppSupportURL=https://github.com/KKrecker/kresorter/issues
AppUpdatesURL=https://github.com/KKrecker/kresorter/releases
VersionInfoVersion={#AppVersion}
VersionInfoCompany=KKrecker
VersionInfoDescription=Kresorter Setup
VersionInfoProductName=Kresorter
PrivilegesRequired=lowest
DefaultDirName={userpf}\Kresorter
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Root}dist
OutputBaseFilename=Kresorter-{#AppVersion}-setup
SetupIconFile={#Icon}
LicenseFile={#Root}LICENSE
UninstallDisplayName=Kresorter
UninstallDisplayIcon={app}\Kresorter.exe
WizardStyle=modern
Compression=lzma2
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#Folder}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Kresorter"; Filename: "{app}\Kresorter.exe"
Name: "{userdesktop}\Kresorter"; Filename: "{app}\Kresorter.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Kresorter.exe"; Description: "{cm:LaunchProgram,Kresorter}"; Flags: nowait postinstall skipifsilent
