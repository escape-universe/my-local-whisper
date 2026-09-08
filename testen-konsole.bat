@echo off
REM Whisperflow mit sichtbarer Konsole starten (zum Testen): zeigt Rohtext, bereinigten Text,
REM Zeiten, Alias-Treffer und Guard-Meldungen live. Haelt die fensterlose Tray-Instanz vorher an
REM und startet sie beim Schliessen wieder. Beenden: Tray-Icon -> Beenden oder Strg+C hier.
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo Fensterlose Instanz wird angehalten ...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" | Where-Object { $_.CommandLine -like '*whisperflow.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
echo.
echo ==== WHISPERFLOW TESTMODUS ====
echo Rechte Strg halten, sprechen, loslassen. Hier erscheinen ROH, BEREINIGT, Zeiten und Guard-Meldungen.
echo Kalibrieren (Begriffe vorlesen, Aliase bestaetigen): kalibrieren.bat
echo.
py whisperflow.py
echo.
echo Testmodus beendet. Fensterlose Instanz wird neu gestartet ...
start "" wscript.exe "%~dp0start-whisperflow-silent.vbs"
pause
