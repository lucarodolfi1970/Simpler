@echo off
rem === Simpler: starts the render engine (Blender in the background) ===
rem If Blender 5.2 is installed elsewhere, fix the next line
set BLENDER=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe
"%BLENDER%" --background --factory-startup --python "%~dp0engine\start_engine.py" -- --port 8787
pause
