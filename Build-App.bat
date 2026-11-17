@echo off
rem === Simpler: builds the Windows app into the dist folder and starts it ===
rem (to build without a window: "Compila e avvia.vbs")
cd /d "%~dp0"
rem (first without restore: the packages are already on the PC; if something is missing, with restore)
dotnet publish app\Simpler\Simpler.csproj -c Release -o dist --nologo --no-restore
if errorlevel 1 dotnet publish app\Simpler\Simpler.csproj -c Release -o dist --nologo
if errorlevel 1 (echo. & echo *** BUILD FAILED: copy the text above and paste it to Claude *** & pause & exit /b 1)
start "" "%~dp0dist\Simpler.exe"
exit /b 0
