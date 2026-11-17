' Simpler: builds the app without showing any window and starts it.
' If the build fails it opens build.log (to copy and paste to Claude).
Option Explicit
Dim sh, fso, dir, rc
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
rc = sh.Run("cmd /c dotnet publish app\Simpler\Simpler.csproj -c Release -o dist --nologo --no-restore > build.log 2>&1", 0, True)
If rc <> 0 Then rc = sh.Run("cmd /c dotnet publish app\Simpler\Simpler.csproj -c Release -o dist --nologo > build.log 2>&1", 0, True)
If rc = 0 Then
    sh.Run """" & dir & "\dist\Simpler.exe""", 1, False
Else
    MsgBox "Build failed: build.log opens now, copy it and paste it to Claude.", 48, "Simpler"
    sh.Run "notepad """ & dir & "\build.log""", 1, False
End If
