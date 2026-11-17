' Simpler: compila l'app senza mostrare finestre e la avvia.
' Se la compilazione non riesce apre build.log (da copiare e incollare a Claude).
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
    MsgBox "Compilazione non riuscita: si apre build.log, copialo e incollalo a Claude.", 48, "Simpler"
    sh.Run "notepad """ & dir & "\build.log""", 1, False
End If
