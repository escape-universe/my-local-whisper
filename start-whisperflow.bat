@echo off
REM whisperflow-local starten (Doppelklick). Sorgt fuer genau EINE laufende Instanz.
cd /d "%~dp0"

REM 1) Evtl. laufende alte Instanz beenden (kein Doppel-Diktat)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" | Where-Object { $_.CommandLine -like '*whisperflow.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

REM 2) Ollama-Server sicherstellen (lokales LLM fuer die Bereinigung)
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
if errorlevel 1 (
  start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
  REM kurze Wartezeit (ping statt timeout, funktioniert auch ohne interaktive Konsole)
  ping -n 4 localhost >nul
)

REM 3) Diktat-App fensterlos starten (nur Tray-Icon unten rechts)
start "" pyw whisperflow.py

echo whisperflow-local gestartet. Icon unten rechts im Tray (blau = bereit).
echo Rechte Strg gedrueckt halten + sprechen + loslassen. Hoher Ton = Text in der Zwischenablage, Strg+V fuegt ein.
ping -n 3 localhost >nul
