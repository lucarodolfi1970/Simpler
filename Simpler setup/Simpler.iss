; ============================================================================================================
;  Simpler - setup (Inno Setup 6/7). Built by Build-Setup.bat; do not run it by hand without the /D values below.
;  /DAppVer=1.79.0   version of the app (Build-Setup.bat reads it from Simpler.csproj)
;  /DStage=<folder>  what goes on the PC: Simpler.exe and its files, engine\, blender\, LICENSE.txt
;  /DPrereq=<folder> MicrosoftEdgeWebview2Setup.exe (the bootstrapper of the WebView2 runtime)
;  /DImg=<folder>    the wizard pictures (img\)
;  /DIcon=<file>     Simpler.ico
;  /DEula=<folder>   eula-it.txt, eula-en.txt (the licence agreement of Simpler, accepted in the setup)
;  /DEulaVer=2.0     version of the agreement (LicenseWindow.Version): written in license-accepted.txt, the app reads it
;  /DDecals=<folder> the decals of Simpler (go in the user's decals\Simpler)
;  /DSignCmd=1       with /Ssign="<command>": the setup and the uninstaller are signed
;  No models inside: they are downloaded on request from the Simpler cloud (the app does it).
; ============================================================================================================
#ifndef AppVer
  #define AppVer "0.0.0"
#endif
#ifndef EulaVer
  #define EulaVer "0"
#endif

[Setup]
AppId={{248D1F7A-E988-4A80-A4A2-8A2B9EF4F54A}
AppName=Simpler
AppVersion={#AppVer}
AppVerName=Simpler {#AppVer}
AppPublisher=Luca Rodolfi
AppPublisherURL=https://www.rodluc.com/simpler/en/
AppSupportURL=https://www.rodluc.com/simpler/en/
DefaultDirName={autopf}\Simpler
DefaultGroupName=Simpler
DisableProgramGroupPage=yes
; (14/11, Luca: «perche' non tutti?») no question at the start: always for the user who installs. No administrator password, and
; everything the setup prepares is of that user (licence accepted, folder of the content, decals, settings): with «all users»
; the other users of the PC would have found a program without them
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=Output
OutputBaseFilename=Simpler-Setup-{#AppVer}
SetupIconFile={#Icon}
UninstallDisplayIcon={app}\Simpler.exe
ShowLanguageDialog=auto
WizardStyle=modern
; the first page with the large picture (off by default in Inno Setup: the picture would be seen only at the end)
DisableWelcomePage=no
WizardImageFile={#Img}\wizard-164.bmp,{#Img}\wizard-192.bmp,{#Img}\wizard-246.bmp
WizardSmallImageFile={#Img}\small-55.bmp,{#Img}\small-64.bmp,{#Img}\small-83.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVer}
VersionInfoCompany=Luca Rodolfi
VersionInfoDescription=Simpler setup
VersionInfoProductName=Simpler
#ifdef SignCmd
SignTool=sign
SignedUninstaller=yes
#endif

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"; LicenseFile: "{#Eula}\eula-en.txt"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"; LicenseFile: "{#Eula}\eula-it.txt"

[CustomMessages]
it.ContentTitle=Contenuti di Simpler
it.ContentSub=Dove vuoi tenere modelli ed ecosistemi?
it.ContentInfo=Il setup non contiene modelli: Simpler li scarica dai suoi server solo quando li usi (serve la connessione e, per tutta la libreria, circa 11 GB). Scegli la cartella dove metterli; potrai cambiarla poi in Impostazioni > Cartelle.
it.ContentLabel=Cartella dei contenuti:
it.ContentSpace=Su questo disco ci sono circa %1 GB liberi e per tutta la libreria ne servono circa 11. Puoi continuare lo stesso (i contenuti si scaricano uno alla volta), oppure scegliere un altro disco.%n%nContinuare con questa cartella?
it.DesktopIcon=Crea un'icona sul desktop
it.WebView2=Installazione del componente WebView2 (vista 3D)...
it.LaunchApp=Avvia Simpler
it.ClauseTitle=Approvazione specifica
it.ClauseSub=Alcune clausole del contratto vanno approvate una per una
it.ClauseText=Ai sensi degli articoli 1341 e 1342 del Codice civile approvo specificamente le clausole 4 (nome, logo e uso corretto), 6 (contenuti di Simpler), 9 (esclusione di garanzia), 10 (limitazione di responsabilità), 11 (manleva), 12 (aggiornamenti e modifiche), 13 (risoluzione di diritto) e 15 (legge applicabile e foro competente).
it.ClauseCheck=Approvo specificamente queste clausole
it.ClauseNeeded=Per installare Simpler serve anche questa approvazione. Se non vuoi darla, chiudi il setup con Annulla.
it.ReqTitle=Il tuo computer
it.ReqSub=Simpler calcola le immagini con la scheda video
it.ReqIntro=Ecco cosa ha trovato il setup. Puoi installare Simpler in ogni caso.
it.ReqGpu=Scheda video
it.ReqGpuNone=non riconosciuta
it.ReqIdeal=Ideale: è una scheda NVIDIA RTX, Simpler la usa al massimo (OptiX).
it.ReqGood=Va bene: Simpler la usa per il calcolo. Con una NVIDIA RTX le immagini sono più veloci.
it.ReqWeak=Poco adatta: con questa scheda il calcolo delle immagini è molto lento (si usa il processore) e la vista 3D può andare a scatti. Simpler dà il meglio con una scheda NVIDIA RTX, AMD Radeon RX o Intel Arc.
it.ReqDisk=Spazio per il programma: circa 2 GB. I modelli si scaricano dopo, solo quelli che usi.
en.ClauseTitle=Specific approval
en.ClauseSub=Some clauses of the agreement must be approved one by one
en.ClauseText=Under articles 1341 and 1342 of the Italian Civil Code I specifically approve clauses 4 (name, logo and fair use), 6 (Simpler content), 9 (disclaimer of warranty), 10 (limitation of liability), 11 (indemnity), 12 (updates and changes), 13 (termination by operation of law) and 15 (governing law and jurisdiction).
en.ClauseCheck=I specifically approve these clauses
en.ClauseNeeded=This approval too is needed to install Simpler. If you do not want to give it, close the setup with Cancel.
en.ReqTitle=Your computer
en.ReqSub=Simpler computes its pictures with the graphics card
en.ReqIntro=This is what the setup found. You can install Simpler in any case.
en.ReqGpu=Graphics card
en.ReqGpuNone=not recognised
en.ReqIdeal=Ideal: an NVIDIA RTX card, Simpler uses it at its best (OptiX).
en.ReqGood=Fine: Simpler uses it to compute. With an NVIDIA RTX the pictures are faster.
en.ReqWeak=Not very suitable: with this card computing the pictures is very slow (the processor is used) and the 3D view may stutter. Simpler is at its best with an NVIDIA RTX, AMD Radeon RX or Intel Arc card.
en.ReqDisk=Space for the program: about 2 GB. The models are downloaded later, only the ones you use.
en.ContentTitle=Simpler content
en.ContentSub=Where do you want to keep models and ecosystems?
en.ContentInfo=The setup contains no models: Simpler downloads them from its servers only when you use them (a connection is needed and, for the whole library, about 11 GB). Choose the folder to keep them in; you can change it later in Settings > Folders.
en.ContentLabel=Content folder:
en.ContentSpace=This disk has about %1 GB free and the whole library needs about 11. You can go on anyway (the content is downloaded one item at a time), or choose another disk.%n%nContinue with this folder?
en.DesktopIcon=Create a desktop icon
en.WebView2=Installing the WebView2 component (3D view)...
en.LaunchApp=Start Simpler

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Excludes: "*.pdb,LICENSE.txt"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Stage}\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
; the decals of Simpler, in the decals of the user (never over a file that is there, never taken away with the program)
Source: "{#Decals}\*"; DestDir: "{userappdata}\Simpler\decals\Simpler"; Excludes: "_simpler.txt"; Flags: recursesubdirs createallsubdirs onlyifdoesntexist uninsneveruninstall skipifsourcedoesntexist
Source: "{#Prereq}\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2

[Icons]
Name: "{autoprograms}\Simpler"; Filename: "{app}\Simpler.exe"
Name: "{autodesktop}\Simpler"; Filename: "{app}\Simpler.exe"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "{cm:WebView2}"; Flags: waituntilterminated; Check: NeedsWebView2
Filename: "{app}\Simpler.exe"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[Code]
var
  ContentPage: TInputDirWizardPage;
  ClausePage: TWizardPage;
  ClauseCheck: TNewCheckBox;
  ReqPage: TOutputMsgMemoWizardPage;

// the graphics cards of this PC (WMI): their names, and how good the best one is for Simpler (2 ideal, 1 fine, 0 weak)
function GpuReport(var Level: Integer): String;
var
  Loc, Svc, Items, It: Variant;
  i, L: Integer;
  N, U: String;
begin
  Result := '';
  Level := -1;
  try
    Loc := CreateOleObject('WbemScripting.SWbemLocator');
    Svc := Loc.ConnectServer('.', 'root\CIMV2');
    Items := Svc.ExecQuery('SELECT Name FROM Win32_VideoController');
    for i := 0 to Items.Count - 1 do
    begin
      It := Items.ItemIndex(i);
      N := It.Name;
      U := Uppercase(N);
      if Pos('RTX', U) > 0 then L := 2
      else if (Pos('GTX', U) > 0) or (Pos('RADEON RX', U) > 0) or (Pos('ARC', U) > 0) or (Pos('QUADRO', U) > 0) or (Pos('RADEON PRO', U) > 0) then L := 1
      else L := 0;
      if L > Level then Level := L;
      if Result <> '' then Result := Result + ', ';
      Result := Result + N;
    end;
  except
    Result := '';
  end;
end;

function ReqText: String;
var
  Level: Integer;
  G, V: String;
begin
  G := GpuReport(Level);
  if G = '' then G := CustomMessage('ReqGpuNone');
  if Level = 2 then V := CustomMessage('ReqIdeal')
  else if Level = 1 then V := CustomMessage('ReqGood')
  else if Level = 0 then V := CustomMessage('ReqWeak')
  else V := '';
  Result := CustomMessage('ReqGpu') + ': ' + G + #13#10#13#10 + V + #13#10#13#10 + CustomMessage('ReqDisk');
end;

// the WebView2 runtime (Edge) draws the 3D view: present on Windows 11 and most Windows 10
function WebView2Version(Root: Integer; const Key: String): String;
begin
  if not RegQueryStringValue(Root, Key, 'pv', Result) then Result := '';
end;

function NeedsWebView2: Boolean;
var
  v: String;
begin
  v := WebView2Version(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}');
  if (v = '') or (v = '0.0.0.0') then
    v := WebView2Version(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}');
  Result := (v = '') or (v = '0.0.0.0');
end;

function PathsFile: String;
begin
  Result := ExpandConstant('{userappdata}\Simpler\paths.json');
end;

procedure InitializeWizard;
var
  T: TNewStaticText;
begin
  // after the agreement: the specific approval of some clauses (as the window of the app did at the first start)
  ClausePage := CreateCustomPage(wpLicense, CustomMessage('ClauseTitle'), CustomMessage('ClauseSub'));
  T := TNewStaticText.Create(ClausePage);
  T.Parent := ClausePage.Surface;
  T.AutoSize := False;
  T.WordWrap := True;
  T.Left := 0;
  T.Top := 0;
  T.Width := ClausePage.SurfaceWidth;
  T.Height := ScaleY(130);
  T.Caption := CustomMessage('ClauseText');
  ClauseCheck := TNewCheckBox.Create(ClausePage);
  ClauseCheck.Parent := ClausePage.Surface;
  ClauseCheck.Left := 0;
  ClauseCheck.Top := T.Top + T.Height + ScaleY(12);
  ClauseCheck.Width := ClausePage.SurfaceWidth;
  ClauseCheck.Height := ScaleY(20);
  ClauseCheck.Caption := CustomMessage('ClauseCheck');
  // then what the setup found on this PC
  ReqPage := CreateOutputMsgMemoPage(ClausePage.ID, CustomMessage('ReqTitle'), CustomMessage('ReqSub'), CustomMessage('ReqIntro'), ReqText);
  ContentPage := CreateInputDirPage(wpSelectDir, CustomMessage('ContentTitle'), CustomMessage('ContentSub'),
    CustomMessage('ContentInfo'), False, '');
  ContentPage.Add(CustomMessage('ContentLabel'));
  ContentPage.Values[0] := ExpandConstant('{userappdata}\Simpler');
end;

// an update (the folders are already chosen): it is not asked again
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = ContentPage.ID) and FileExists(PathsFile);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Free, Total: Int64;
  Drive: String;
begin
  Result := True;
  if (CurPageID = ClausePage.ID) and not ClauseCheck.Checked then
  begin
    MsgBox(CustomMessage('ClauseNeeded'), mbInformation, MB_OK);
    Result := False;
  end;
  if CurPageID = ContentPage.ID then
  begin
    Drive := ExtractFileDrive(ContentPage.Values[0]) + '\';
    if GetSpaceOnDisk64(Drive, Free, Total) and (Free < Int64(11) * 1024 * 1024 * 1024) then
      Result := MsgBox(FmtMessage(CustomMessage('ContentSpace'), [IntToStr(Free div (1024 * 1024 * 1024))]),
                       mbConfirmation, MB_YESNO) = IDYES;
  end;
end;

function JsonPath(const P: String): String;
begin
  Result := P;
  StringChangeEx(Result, '\', '\\', True);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Root, Def: String;
begin
  // the agreement was accepted here: the app does not ask again (LicenseWindow.Accepted reads this file)
  if CurStep = ssPostInstall then
  begin
    ForceDirectories(ExpandConstant('{userappdata}\Simpler'));
    SaveStringToFile(ExpandConstant('{userappdata}\Simpler\license-accepted.txt'),
      '{#EulaVer}|' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':') + '|setup {#AppVer}', False);
  end;
  if (CurStep = ssPostInstall) and not FileExists(PathsFile) then
  begin
    Root := RemoveBackslash(ContentPage.Values[0]);
    Def := ExpandConstant('{userappdata}\Simpler');
    // the default place needs no file: the app uses it by itself
    if CompareText(Root, Def) <> 0 then
    begin
      ForceDirectories(Root + '\models');
      ForceDirectories(Root + '\ecosystems');
      ForceDirectories(ExtractFilePath(PathsFile));
      SaveStringToFile(PathsFile,
        '{"current": {"models": "' + JsonPath(Root + '\models') + '", "ecosystems": "' + JsonPath(Root + '\ecosystems') +
        '"}, "history": {}}', False);
    end;
  end;
end;
