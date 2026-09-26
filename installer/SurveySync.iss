#define MyAppName "SurveySync"
#define MyAppVersion "9.3.1"
#define MyAppPublisher "Clever Bird Development"
#define MyAppURL "https://github.com/cpaul1988/SurveySync"

[Setup]
AppId={{D7432040-46E5-4F2B-A9AC-97B2DB7BAF4B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\SurveySync
DefaultGroupName=SurveySync
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
MinVersion=10.0
ArchitecturesAllowed=x64compatible
OutputDir=output
OutputBaseFilename=SurveySync_Setup_9.3.1
SetupIconFile=..\branding\SurveySync.ico
UninstallDisplayIcon={app}\branding\SurveySync.ico
WizardStyle=modern
WizardImageFile=wizard_large.bmp
WizardSmallImageFile=wizard_small.bmp
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
VersionInfoVersion=9.3.1.0
VersionInfoTextVersion=9.3.1
VersionInfoCompany=Clever Bird Development
VersionInfoDescription=SurveySync Windows Setup
VersionInfoProductName=SurveySync
VersionInfoProductVersion=9.3.1

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce
Name: "fbsassoc"; Description: "Associate .fbs project files with SurveySync"; GroupDescription: "Integration:"; Flags: checkedonce
Name: "localai"; Description: "Run optional FieldBookSync Local AI setup after installation"; GroupDescription: "Local AI:"; Flags: unchecked

[Files]
Source: "..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".build-venv\*,.ruff_cache\*,.mypy_cache\*,.pytest_cache\*,.coverage,coverage.xml,installer\output\*,tests\*,legacy_tests\*,.venv\*,.paddleenv\*,runtime\*,dist\*,build\*,__pycache__\*,*.pyc,*.pyo"
Source: "provision_runtime.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion; AfterInstall: ProvisionRuntime

[Icons]
Name: "{autoprograms}\SurveySync"; Filename: "{app}\SurveySync.exe"; WorkingDir: "{app}"; IconFilename: "{app}\branding\SurveySync.ico"
Name: "{autoprograms}\SurveySync (Browser Fallback)"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\run_browser.py"""; WorkingDir: "{app}"; IconFilename: "{app}\branding\SurveySync.ico"
Name: "{autodesktop}\SurveySync"; Filename: "{app}\SurveySync.exe"; WorkingDir: "{app}"; IconFilename: "{app}\branding\SurveySync.ico"; Tasks: desktopicon

[InstallDelete]
; v9.3.1 is an in-place SurveySync feature update and retains the FieldBook Sync migration cleanup.
; Only legacy application binaries/shortcuts are removed. User data under
; %LOCALAPPDATA%\FieldBookSync and user-created .fbs files are intentionally untouched.
Type: files; Name: "{app}\FieldBookSync.exe"
Type: files; Name: "{app}\FieldBookSyncUpdater.exe"
Type: files; Name: "{app}\Force_Close_FieldBook_Sync.bat"
Type: files; Name: "{autoprograms}\FieldBook Sync.lnk"
Type: files; Name: "{autoprograms}\FieldBook Sync (Browser Fallback).lnk"
Type: files; Name: "{autoprograms}\FieldBook Sync - Local AI Setup.lnk"
Type: files; Name: "{autodesktop}\FieldBook Sync.lnk"

[Registry]
; Replace the legacy FieldBook Sync .fbs handler with SurveySync.
Root: HKCU; Subkey: "Software\Classes\FieldBookSync.Project"; Flags: deletekey
Root: HKCU; Subkey: "Software\Classes\.fbs"; ValueType: string; ValueName: ""; ValueData: "SurveySync.Project"; Flags: uninsdeletevalue; Tasks: fbsassoc
Root: HKCU; Subkey: "Software\Classes\SurveySync.Project"; ValueType: string; ValueName: ""; ValueData: "SurveySync Project"; Flags: uninsdeletekey; Tasks: fbsassoc
Root: HKCU; Subkey: "Software\Classes\SurveySync.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\branding\SurveySync.ico"; Tasks: fbsassoc
Root: HKCU; Subkey: "Software\Classes\SurveySync.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SurveySync.exe"" ""%1"""; Tasks: fbsassoc

[Run]
Filename: "{cmd}"; Parameters: "/C """"{app}\install_local_ai.bat"""""; WorkingDir: "{app}"; Description: "Configure optional FieldBookSync Local AI"; Flags: postinstall skipifsilent; Tasks: localai
Filename: "{app}\SurveySync.exe"; WorkingDir: "{app}"; Description: "Launch SurveySync"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\.paddleenv"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
procedure ProvisionRuntime;
var
  ResultCode: Integer;
  PowerShell: String;
  Args: String;
begin
  WizardForm.StatusLabel.Caption := 'Installing the private Python runtime and SurveySync dependencies...';
  PowerShell := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  Args := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\installer\provision_runtime.ps1') + '" -InstallDir "' + ExpandConstant('{app}') + '" -AppVersion "{#MyAppVersion}"';
  if not Exec(PowerShell, Args, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    RaiseException('Could not start the SurveySync runtime provisioner.')
  else if ResultCode <> 0 then
    RaiseException('SurveySync dependency setup failed. See %LOCALAPPDATA%\SurveySync\logs\setup_runtime.log for details.');
end;
