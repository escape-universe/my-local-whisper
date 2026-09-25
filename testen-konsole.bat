@echo off
REM Whisperflow mit sichtbarer Konsole starten (zum Testen): zeigt je Diktat live Zeiten, ob
REM eingefuegt oder nur in die Zwischenablage, Alias-Treffer, Guard-Meldungen und die ersten 120
REM Zeichen des gelieferten Texts, bei langen Diktaten auch die ersten 60 Zeichen jedes schon beim
REM Sprechen erkannten Abschnitts. Den Rohtext zeigt es nicht daneben; roh und bereinigt vergleicht
REM py whisperflow.py --clean-text fuer einen getippten Text. Haelt die fensterlose Tray-Instanz vorher an
REM und startet sie beim Schliessen wieder. Beenden: Tray-Icon -> Beenden oder Strg+C hier.
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo Fensterlose Instanz wird angehalten ...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" | Where-Object { $_.CommandLine -like '*whisperflow.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
echo.
echo ==== MY-LOCAL-WHISPER TESTMODUS ====
echo Rechte Strg halten, sprechen, loslassen. Hier erscheinen je Diktat Zeiten, Alias-Treffer, Guard-Meldungen
echo und der Anfang des gelieferten Texts (120 Zeichen; lange Diktate auch je Abschnitt 60), kein Rohtext daneben.
echo Kalibrieren (Begriffe vorlesen, Aliase bestaetigen): kalibrieren.bat
echo.
py whisperflow.py
echo.
echo Testmodus beendet. Fensterlose Instanz wird neu gestartet ...
start "" wscript.exe "%~dp0start-whisperflow-silent.vbs"
pause
