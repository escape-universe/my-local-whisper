' whisperflow-local unsichtbar starten (fuer den Autostart, kein Konsolenfenster).
' Ruft start-whisperflow.bat auf, das eine evtl. alte Instanz beendet und die Tray-App startet.
Dim sh, dir, q
Set sh = CreateObject("WScript.Shell")
q = Chr(34)
dir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
sh.CurrentDirectory = dir
sh.Run q & dir & "start-whisperflow.bat" & q, 0, False
