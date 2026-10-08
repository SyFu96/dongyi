Option Explicit
Dim shell, files, projectDir, pythonw, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
projectDir = files.GetParentFolderName(WScript.ScriptFullName)
pythonw = files.BuildPath(projectDir, ".venv\Scripts\pythonw.exe")
shell.CurrentDirectory = projectDir
command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & files.BuildPath(projectDir, "app.py") & Chr(34)
' SW_HIDE also hides the console created by the uv virtualenv redirector.
shell.Run command, 0, False
