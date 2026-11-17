@echo off
rem === Simpler: test completo del motore (avvia prima Start-Engine.bat in un'altra finestra) ===
set BLENDER=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe
"%BLENDER%" --background --factory-startup --python "%~dp0tools\test_engine.py" -- "%~dp0tools\anello_test.fbx" "%~dp0test_out"
echo.
echo Immagini di prova in: %~dp0test_out
pause
