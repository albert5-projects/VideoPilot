Option Explicit
Dim shell, files, folder, python
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(folder, ".venv\Scripts\pythonw.exe")
If Not files.FileExists(python) Then
    MsgBox "Please run Setup.bat first.", vbExclamation, "VideoPilot"
    WScript.Quit 1
End If
shell.CurrentDirectory = folder
shell.Environment("PROCESS")("PYTHONUTF8") = "1"
shell.Run Chr(34) & python & Chr(34) & " -m videopilot.gui", 0, False
