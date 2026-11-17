@echo off
rem === Simpler: full test of the engine (start Start-Engine.bat in another window first) ===
set BLENDER=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe
"%BLENDER%" --background --factory-startup --python "%~dp0tools\test_engine.py" -- "%~dp0tools\anello_test.fbx" "%~dp0test_out"
echo.
echo Test images in: %~dp0test_out
pause
