@echo off
rem === Simpler: builds Setup.exe (app + engine + Blender + wizard) in "Simpler setup\Output" ===
rem Needs: .NET 8 SDK, Inno Setup, the Blender used by Simpler (found by itself).
rem Optional: the folder with blender.exe as first argument; sign.cmd next to this file (see LEGGIMI.txt).
rem Everything is written in "Simpler setup\build.log" (Claude reads it); the window shows only the steps.
if "%~1"=="--inner" goto :inner
echo Simpler setup - building. It takes several minutes: the steps appear here.
echo (details in "%~dp0build.log")
echo.
call "%~f0" --inner %* > "%~dp0build.log" 2>&1
if errorlevel 1 (
  echo.
  echo *** SETUP NOT BUILT. Tell Claude "fatto": the reason is in build.log ***
) else (
  echo.
  echo DONE. The setup is in "%~dp0Output". Tell Claude "fatto".
)
pause
exit /b

:inner
setlocal
cd /d "%~dp0.."
set ROOT=%CD%
set SETUP=%ROOT%\Simpler setup
set BUILD=%ROOT%\setup-build
set STAGE=%BUILD%\stage
set PREREQ=%BUILD%\prereq
set EULA=%BUILD%\eula
set DECALS=%BUILD%\decals
echo [%TIME%] start

rem --- version (from the project file) and version of the licence agreement (LicenseWindow.cs)
for /f "usebackq delims=" %%v in (`powershell -NoProfile -Command "([xml](Get-Content '%ROOT%\app\Simpler\Simpler.csproj')).Project.PropertyGroup.Version | Where-Object { $_ } | Select-Object -First 1"`) do set VER=%%v
if "%VER%"=="" (echo *** Version not found in Simpler.csproj & goto :fail)
for /f "usebackq delims=" %%v in (`powershell -NoProfile -Command "if ((Get-Content '%ROOT%\app\Simpler\LicenseWindow.cs' -Raw) -match 'const string Version = .([0-9.]+).;') { $Matches[1] }"`) do set EULAVER=%%v
if "%EULAVER%"=="" (echo *** Version of the licence agreement not found in LicenseWindow.cs & goto :fail)
echo Simpler %VER%, licence agreement %EULAVER%
echo Step 1 of 7: Simpler %VER% >CON

rem --- Inno Setup
set ISCC=
for %%p in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" "%ProgramFiles%\Inno Setup 7\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe") do if exist %%p set ISCC=%%~p
if "%ISCC%"=="" (echo *** Inno Setup not found ^(ISCC.exe^) & goto :fail)
echo Inno Setup: %ISCC%

rem --- Blender (argument, or the one Simpler uses: BlenderPath in settings.json)
set BL=%~2
if "%BL%"=="" if defined BLENDER_DIR set BL=%BLENDER_DIR%
if "%BL%"=="" for /f "usebackq delims=" %%b in (`powershell -NoProfile -Command "try { Split-Path ((Get-Content (Join-Path $env:APPDATA 'Simpler\settings.json') -Raw | ConvertFrom-Json).BlenderPath) } catch { '' }"`) do set BL=%%b
if "%BL%"=="" if exist "%ProgramFiles%\Blender Foundation" for /d %%d in ("%ProgramFiles%\Blender Foundation\Blender *") do set BL=%%d
if not exist "%BL%\blender.exe" (echo *** Blender not found ^(BL=%BL%^) & goto :fail)
echo Blender: %BL%

rem --- clean and publish the app (self contained: no .NET to install)
echo Step 2 of 7: compiling Simpler >CON
if exist "%BUILD%" rmdir /s /q "%BUILD%"
mkdir "%STAGE%" "%PREREQ%" "%EULA%" "%DECALS%"
dotnet publish "%ROOT%\app\Simpler\Simpler.csproj" -c Release -r win-x64 --self-contained true -o "%STAGE%" --nologo
if errorlevel 1 (echo *** dotnet publish failed & goto :fail)
if not exist "%STAGE%\Simpler.exe" (echo *** Simpler.exe is not in the publish folder & goto :fail)
if not exist "%STAGE%\samples" (echo *** the sample projects are not in the publish folder & goto :fail)

rem --- engine, Blender
echo Step 3 of 7: engine and Blender >CON
robocopy "%ROOT%\engine" "%STAGE%\engine" /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (echo *** copy of the engine failed & goto :fail)
robocopy "%BL%" "%STAGE%\blender" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (echo *** copy of Blender failed & goto :fail)
copy /y "%ROOT%\LICENSE" "%STAGE%\LICENSE.txt" >nul
if not exist "%STAGE%\engine\start_engine.py" (echo *** engine missing & goto :fail)
if not exist "%STAGE%\blender\blender.exe" (echo *** Blender missing in the stage & goto :fail)

rem --- the pictures of the models of the cloud (made by Pack Studio in ..\simpler-setup\thumbs): shown at once in the library
echo Step 4 of 7: pictures of the library, decals, licence agreement >CON
if exist "%ROOT%\..\simpler-setup\thumbs" (
  robocopy "%ROOT%\..\simpler-setup\thumbs" "%STAGE%\thumbs" /E /NFL /NDL /NJH /NJS /NP >nul
) else (
  echo WARNING: "%ROOT%\..\simpler-setup\thumbs" not found: the setup has no pictures of the cloud models
  echo WARNING: no pictures of the cloud models ^(simpler-setup\thumbs not found^) >CON
)

rem --- the decals of Simpler (the folder "Simpler" of the author's decals: paths.json, or the default place)
set DEC=
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "try { (Get-Content (Join-Path $env:APPDATA 'Simpler\paths.json') -Raw | ConvertFrom-Json).current.decals } catch { '' }"`) do set DEC=%%d
if "%DEC%"=="" set DEC=%APPDATA%\Simpler\decals
if exist "%DEC%\Simpler" (
  robocopy "%DEC%\Simpler" "%DECALS%" /E /NFL /NDL /NJH /NJS /NP >nul
  echo Decals of Simpler from: %DEC%\Simpler
) else (
  echo WARNING: "%DEC%\Simpler" not found: the setup has no decals
  echo WARNING: no decals of Simpler found >CON
)
rem (Inno Setup wants at least one file in a source folder)
echo Simpler decals> "%DECALS%\_simpler.txt"

rem --- the licence agreement, in the two languages, as text with the marks of the format taken away
powershell -NoProfile -Command "foreach ($p in @(@('%ROOT%\credits\Licenza.md','%EULA%\eula-it.txt'), @('%ROOT%\credits\en\License.md','%EULA%\eula-en.txt'))) { $t = Get-Content $p[0] -Encoding UTF8; $t = $t | ForEach-Object { ($_ -replace '^#+\s*','') -replace '\*\*','' }; Set-Content -Path $p[1] -Value $t -Encoding UTF8 }"
if not exist "%EULA%\eula-it.txt" (echo *** licence agreement ^(it^) not made & goto :fail)
if not exist "%EULA%\eula-en.txt" (echo *** licence agreement ^(en^) not made & goto :fail)

rem --- WebView2 bootstrapper (for the PCs that do not have the runtime)
echo Step 5 of 7: WebView2 installer >CON
curl.exe -L -s -o "%PREREQ%\MicrosoftEdgeWebview2Setup.exe" "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
if not exist "%PREREQ%\MicrosoftEdgeWebview2Setup.exe" (echo *** WebView2 bootstrapper not downloaded & goto :fail)

rem --- signature (only if sign.cmd exists: one line with the signtool command, $f is the file)
set SIGN=
set SIGNLINE=
if exist "%SETUP%\sign.cmd" for /f "usebackq delims=" %%s in ("%SETUP%\sign.cmd") do set SIGNLINE=%%s
if defined SIGNLINE set SIGN=/DSignCmd=1 "/Ssign=%SIGNLINE%"
if defined SIGNLINE (echo Step 6 of 7: the setup will be SIGNED >CON) else (echo Step 6 of 7: no sign.cmd, the setup is NOT signed >CON)

rem --- what is inside (for the log)
powershell -NoProfile -Command "Get-ChildItem '%STAGE%' | ForEach-Object { $s = if ($_.PSIsContainer) { (Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum } else { $_.Length }; '{0,8:N0} MB  {1}' -f ($s / 1MB), $_.Name } | Sort-Object -Descending | Select-Object -First 25"

rem --- the setup
echo Step 7 of 7: building Setup.exe ^(the longest step: 10-20 minutes, the window stays still^) >CON
"%ISCC%" /DAppVer=%VER% /DEulaVer=%EULAVER% "/DStage=%STAGE%" "/DPrereq=%PREREQ%" "/DEula=%EULA%" "/DDecals=%DECALS%" "/DImg=%SETUP%\img" "/DIcon=%ROOT%\app\Simpler\Simpler.ico" %SIGN% "%SETUP%\Simpler.iss"
if errorlevel 1 (echo *** Inno Setup failed & goto :fail)
echo.
echo [%TIME%] DONE: "%SETUP%\Output\Simpler-Setup-%VER%.exe"
for %%f in ("%SETUP%\Output\Simpler-Setup-%VER%.exe") do echo size: %%~zf bytes
exit /b 0

:fail
echo [%TIME%] SETUP NOT BUILT
exit /b 1
