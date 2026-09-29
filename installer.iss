; Inno Setup script. Built in CI: iscc /DMyVersion=<ui.VERSION> installer.iss
#ifndef MyVersion
  #define MyVersion "0.0.0"
#endif
#define MyApp "Retail Price Tag Management"
#define MyExe MyApp + ".exe"

[Setup]
AppId={{8C1F2B7E-6D3A-4E59-9B1C-2F7A4D5E6C01}
AppName={#MyApp}
AppVersion={#MyVersion}
AppPublisher=Babel Mart
DefaultDirName={autopf}\{#MyApp}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename={#MyApp} Setup {#MyVersion}
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#MyExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#MyApp}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyApp}"; Filename: "{app}\{#MyExe}"
Name: "{autodesktop}\{#MyApp}"; Filename: "{app}\{#MyExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyExe}"; Description: "{cm:LaunchProgram,{#MyApp}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; App settings only, by exact name. Database files (.rptdb) are never touched, wherever they are.
Type: files; Name: "{userappdata}\RetailPriceTagManagement\config.json"
Type: files; Name: "{userappdata}\RetailPriceTagManagement\license.txt"
Type: dirifempty; Name: "{userappdata}\RetailPriceTagManagement"
