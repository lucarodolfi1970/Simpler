@echo off
rem === Simpler: compila l'app Windows nella cartella dist e la avvia ===
rem (per compilare senza finestra: "Compila e avvia.vbs")
cd /d "%~dp0"
rem (prima senza restore: i pacchetti sono gia' sul PC; se manca qualcosa, con restore)
dotnet publish app\Simpler\Simpler.csproj -c Release -o dist --nologo --no-restore
if errorlevel 1 dotnet publish app\Simpler\Simpler.csproj -c Release -o dist --nologo
if errorlevel 1 (echo. & echo *** COMPILAZIONE FALLITA: copia il testo qui sopra e incollalo a Claude *** & pause & exit /b 1)
start "" "%~dp0dist\Simpler.exe"
exit /b 0
