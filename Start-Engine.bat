@echo off
rem === Simpler: avvia il motore di render (Blender in background) ===
rem Se Blender 5.2 e' installato altrove, correggi la riga seguente
set BLENDER=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe
"%BLENDER%" --background --factory-startup --python "%~dp0engine\start_engine.py" -- --port 8787
pause
