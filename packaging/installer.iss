; Inno Setup 6 script for the Retroverse Terminal (built by packaging\build.ps1).
;
; - installs dist\RetroverseTerminal (PyInstaller folder)
; - asks for the NestrisLTM address and the API token and writes them into
;   %APPDATA%\NestrisTerminal\config.toml (via "nestris-terminal.exe configure")
; - optional: start the kiosk when this Windows user signs in (HKCU Run key)
; - stops a running kiosk before updating / uninstalling

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Retroverse Terminal"
#define KioskExe "RetroverseTerminal.exe"
#define CliExe "nestris-terminal.exe"

[Setup]
AppId={{6F1E3C2A-6D0B-4C1B-9B6B-2E7D4B9F7A51}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Retroverse
AppPublisherURL=https://retroverse.at
DefaultDirName={autopf}\Retroverse Terminal
DefaultGroupName=Retroverse
DisableProgramGroupPage=yes
; Autostart and config are per user: install for the kiosk user by default.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=RetroverseTerminal-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#KioskExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
de.AutostartTask=Terminal bei der Windows-Anmeldung automatisch starten (Kiosk)
en.AutostartTask=Start the terminal automatically when Windows signs in (kiosk)
de.DesktopTask=Desktop-Verknüpfung anlegen
en.DesktopTask=Create a desktop shortcut
de.HostTitle=Verbindung zu NestrisLTM
en.HostTitle=Connection to NestrisLTM
de.HostDesc=Adresse des Turnier-PCs und API-Token (Bereich "terminal", im NestrisLTM-Admin unter Einstellungen → API-Tokens). Leer lassen, um vorhandene Einstellungen zu behalten.
en.HostDesc=Address of the tournament PC and an API token (scope "terminal", NestrisLTM admin → Settings → API tokens). Leave empty to keep the current settings.
de.HostUrl=NestrisLTM-Adresse (z. B. http://192.168.1.10:7990):
en.HostUrl=NestrisLTM address (e.g. http://192.168.1.10:7990):
de.HostToken=API-Token:
en.HostToken=API token:
de.LaunchNow=Terminal jetzt starten
en.LaunchNow=Start the terminal now

[Tasks]
Name: "autostart"; Description: "{cm:AutostartTask}"
Name: "desktopicon"; Description: "{cm:DesktopTask}"; Flags: unchecked

[Files]
Source: "..\dist\RetroverseTerminal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\config.example.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\OPERATIONS.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#KioskExe}"
Name: "{autoprograms}\{#AppName} (Fenster)"; Filename: "{app}\{#KioskExe}"; Parameters: "--windowed"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#KioskExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#CliExe}"; Parameters: "{code:ConfigureParams}"; Flags: runhidden waituntilterminated; Check: HasConnectionInput
Filename: "{app}\{#CliExe}"; Parameters: "autostart on"; Flags: runhidden waituntilterminated; Tasks: autostart
Filename: "{app}\{#CliExe}"; Parameters: "autostart off"; Flags: runhidden waituntilterminated; Tasks: not autostart
Filename: "{app}\{#KioskExe}"; Description: "{cm:LaunchNow}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\{#CliExe}"; Parameters: "autostart off"; Flags: runhidden waituntilterminated; RunOnceId: "AutostartOff"

[Code]
var
  HostPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  HostPage := CreateInputQueryPage(wpSelectTasks, CustomMessage('HostTitle'), '', CustomMessage('HostDesc'));
  HostPage.Add(CustomMessage('HostUrl'), False);
  HostPage.Add(CustomMessage('HostToken'), False);
  HostPage.Values[0] := GetPreviousData('HostUrl', '');
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'HostUrl', Trim(HostPage.Values[0]));
end;

function HasConnectionInput: Boolean;
begin
  Result := (Trim(HostPage.Values[0]) <> '') or (Trim(HostPage.Values[1]) <> '');
end;

function ConfigureParams(Param: String): String;
begin
  Result := 'configure';
  if Trim(HostPage.Values[0]) <> '' then
    Result := Result + ' --host ' + AddQuotes(Trim(HostPage.Values[0]));
  if Trim(HostPage.Values[1]) <> '' then
    Result := Result + ' --token ' + AddQuotes(Trim(HostPage.Values[1]));
end;

procedure StopKiosk;
var
  Code: Integer;
begin
  { The kiosk ignores window close requests by design: end it hard. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#KioskExe}', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopKiosk;
  Result := '';
end;

function InitializeUninstall: Boolean;
begin
  StopKiosk;
  Result := True;
end;
