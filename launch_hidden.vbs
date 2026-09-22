Option Explicit

Dim shell, batPath, command, i
Set shell = CreateObject("WScript.Shell")

If WScript.Arguments.Count < 1 Then
    WScript.Quit 2
End If

batPath = WScript.Arguments(0)
command = QuoteArg(batPath) & " --hidden"

For i = 1 To WScript.Arguments.Count - 1
    command = command & " " & QuoteArg(WScript.Arguments(i))
Next

' Window style 0 = hidden.  Do not wait here: the visible bootstrap console
' should disappear immediately while the hidden batch owns the app lifetime.
shell.Run command, 0, False
WScript.Quit 0

Function QuoteArg(value)
    QuoteArg = Chr(34) & Replace(CStr(value), Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function
