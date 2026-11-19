' Finch 启动器：双击即可，无控制台窗口
Option Explicit
Dim fso, shell, root, pyw
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then
    MsgBox "找不到 " & pyw & vbCrLf & "请先创建虚拟环境并安装依赖。", 16, "Finch"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
shell.Run """" & pyw & """ run.py", 0, False
