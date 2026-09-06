@echo off
REM Kalibrierung mit der eigenen Stimme. Haelt die Tray-App an (sonst diktiert sie parallel mit), startet sie danach neu.
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo Tray-App wird fuer die Kalibrierung angehalten ...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" | Where-Object { $_.CommandLine -like '*whisperflow.py*' -and $_.CommandLine -notlike '*--calibrate*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo.
echo ==== KALIBRIERUNG ====
echo Rechte Strg gedrueckt halten, die angezeigten Begriffe vorlesen (gern als Satz), loslassen.
echo Dann pro fehlendem Begriff: j = Vorschlag uebernehmen, n = nicht, oder richtige Schreibweise tippen.
echo Enter = naechste Runde, w = Runde wiederholen, q = Ende.
echo.
py whisperflow.py --calibrate
echo.
echo Kalibrierung beendet. Tray-App wird neu gestartet ...
start "" wscript.exe "%~dp0start-whisperflow-silent.vbs"
echo Fertig. Fenster kann geschlossen werden.
pause
