@echo off
REM whisperflow-local beenden (Doppelklick). Beendet alle laufenden Instanzen.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" | Where-Object { $_.CommandLine -like '*whisperflow.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
echo whisperflow-local beendet.
ping -n 2 localhost >nul
