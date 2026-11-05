; Script for building setup.exe installer with Inno Setup

#define nwAppDir "%%dist%%"
#define nwAppName "UmbraEdit"
#define nwAppVersion "%%version%%"
#define nwAppPublisher "UmbraEdit"
#define nwAppURL "https://UmbraEdit.io"

[Setup]
AppId={{459A75D0-951F-4932-9809-6002EC8E733E}
AppName={#nwAppName}
AppVersion={#nwAppVersion}
AppVerName={#nwAppName} {#nwAppVersion}
AppPublisher={#nwAppPublisher}
AppPublisherURL={#nwAppURL}
AppSupportURL={#nwAppURL}
AppUpdatesURL={#nwAppURL}
SetupIconFile=setup\icons\umbraedit.ico
UninstallDisplayIcon={app}\umbraedit.ico
DefaultDirName={autopf}\{#nwAppName}
LicenseFile=setup\iss_license.txt
DisableProgramGroupPage=yes
UsedUserAreasWarning=no
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#nwAppDir}
OutputBaseFilename=umbraedit-{#nwAppVersion}-amd64-setup
Compression=zip
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; Check: not IsAdminInstallMode

[InstallDelete]
Type: filesandordirs; Name: "{app}\lib\*"
Type: filesandordirs; Name: "{app}\umbraedit\*"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\lib\*"
Type: filesandordirs; Name: "{app}\umbraedit\*"

[Files]
Source: "{#nwAppDir}\UmbraEdit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#nwAppName}"; Filename: "{app}\UmbraEdit.exe"; IconFilename: "{app}\UmbraEdit.ico"
Name: "{autodesktop}\{#nwAppName}"; Filename: "{app}\UmbraEdit.exe"; IconFilename: "{app}\UmbraEdit.ico"; Tasks: desktopicon;

[Run]
Filename: "{app}\UmbraEdit.exe"; Description: "{cm:LaunchProgram,{#StringChange(nwAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKA; Subkey: "Software\Classes\.nwx\OpenWithProgids"; ValueType: string; ValueName: "UmbraEditProject.nwx"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\UmbraEditProject.nwx"; ValueType: string; ValueName: ""; ValueData: "UmbraEdit Project File"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\UmbraEditProject.nwx\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\umbraedit\assets\icons\x-umbraedit-project.ico"
Root: HKA; Subkey: "Software\Classes\UmbraEditProject.nwx\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\UmbraEdit.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\UmbraEdit.exe\SupportedTypes"; ValueType: string; ValueName: ".nwx"; ValueData: ""; Flags: uninsdeletekey
