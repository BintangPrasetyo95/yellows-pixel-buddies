; Script generated for Yellow's Pixel Buddies
; Uses Inno Setup (http://www.jrsoftware.org/isinfo.php)

#define MyAppName "Yellow's Pixel Buddies"
#define MyAppVersion "0.9.8"
#define MyAppPublisher "BintangPrasetyo95"
#define MyAppURL "https://github.com/BintangPrasetyo95/yellows-pixel-buddies"
#define MyAppExeName "Yellows-Pixel-Buddies.exe"

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
AppId={{5E2D07FE-15C2-4328-984F-B19F68E6B1D2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Modern Windows standard: Install per-user into %LOCALAPPDATA%\Programs without needing UAC / Admin password!
; This allows silent background updates!
DefaultDirName={localappdata}\Programs\Yellows Pixel Buddies
DisableDirPage=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; User privilege settings (no admin prompt needed)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Output file setup
OutputDir=dist
OutputBaseFilename=Yellows-Pixel-Buddies-Setup
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; Close running instance automatically before installing/updating
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Start Yellow's Pixel Buddies automatically when logging in"; GroupDescription: "Startup:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon; IconFilename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// Protect user memories and chat sessions during uninstallation
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\YellowsPixelBuddies');
    if DirExists(DataDir) then
    begin
      if MsgBox('Would you like to delete your saved pet memories, facts, and chat logs?' + #13#10 + #13#10 +
                '(Choose "No" if you plan to reinstall or keep your pet history)', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(DataDir, True, True, True);
      end;
    end;
  end;
end;
